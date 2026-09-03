"""The handoff document contract. Everything else depends on this module.

Structure, and who writes each part:

    YAML frontmatter   <- ALWAYS the code. 5 keys, no more, no less
    HTML comment       <- the code. Rewrite warning
    ## Context         <- the code, from git
    ## State, ...      <- the MODEL. State required, the rest optional

That the code owns the frontmatter is not an implementation detail: it is what
makes `read_mode` impossible to break from the model's side, because the model
never writes that line.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

#: Format version. Bump only on an incompatible change.
VERSION = 1

#: The answer to any ambiguity. This is the plugin's central safety decision:
#: an unreadable document must never authorise continuing work. Equivalent
#: plugins fail exactly the other way around.
SAFE_MODE = "memory"
MODES = ("continue", "memory")

#: Only the head of the file is inspected. A 1 MB handoff -- hand-edited,
#: corrupt, whatever -- must not cost time on every session start.
HEAD = 4096

# The \r in the trailing classes is not cosmetic: with MULTILINE, `$` matches
# BEFORE the \n, so in a CRLF file the \r stays inside the line and would break
# the match. A handoff written on Windows has to read the same.
RE_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
RE_MODE = re.compile(r"^mode:[ \t]*(continue|memory)[ \t\r]*$", re.MULTILINE)
RE_VERSION = re.compile(r"^baton:[ \t]*(\d+)[ \t\r]*$", re.MULTILINE)
RE_FIELD = re.compile(r"^(date|branch|commit):[ \t]*(\S.*?)[ \t\r]*$", re.MULTILINE)
RE_SECTION = re.compile(r"^##[ \t]+(.+?)[ \t\r]*$", re.MULTILINE)


def _frontmatter(text) -> str | None:
    """The frontmatter body, or None when there is no well-formed one."""
    if not isinstance(text, str) or not text:
        return None
    m = RE_FRONTMATTER.match(text[:HEAD])
    return m.group(1) if m else None


def read_mode(text) -> str:
    """Deterministic and garbage-proof.

    The value is a strict lowercase enum on purpose. Accepting variants -- other
    casing, near-misses -- would turn a control field into something you can
    write "almost right", and "almost right" here means a session starts working
    on its own when it should not have.
    """
    body = _frontmatter(text)
    if body is None:
        return SAFE_MODE
    m = RE_MODE.search(body)
    return m.group(1) if m else SAFE_MODE


def read_version(text):
    """Format version declared in the document, or None."""
    body = _frontmatter(text)
    if body is None:
        return None
    m = RE_VERSION.search(body)
    return int(m.group(1)) if m else None


def read_fields(text) -> dict:
    """date / branch / commit from the frontmatter. Missing keys stay missing."""
    body = _frontmatter(text)
    if body is None:
        return {}
    return {k: v for k, v in RE_FIELD.findall(body)}


def normalize_label(text: str) -> str:
    """Compare section labels ignoring accents and case.

    Here we ARE permissive, unlike with the mode: a label is prose aimed at a
    human, and the model writing "Decisions and why" against a configured
    "Decisions and Why" should not cost it a rejection.
    """
    plain = unicodedata.normalize("NFD", text or "")
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    return " ".join(plain.casefold().split())


# --- draft validation and final composition -------------------------------
#
# The model writes ONLY the body, into a separate draft. The code composes the
# final file. Four guarantees follow that do not depend on the model behaving:
# the rewrite is always whole, the frontmatter is always valid, the git fields
# are always right, and a failed attempt leaves the previous handoff untouched.


@dataclass
class ParsedDraft:
    valid: bool
    body: str = ""
    sections: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


def _strip_frontmatter(text: str) -> str:
    """The model does not write the frontmatter. If it sneaks one in, drop it."""
    m = RE_FRONTMATTER.match(text[:HEAD])
    return text[m.end():] if m else text


def _split_sections(text: str):
    """Returns (preamble, {label: content}) preserving order."""
    marks = list(RE_SECTION.finditer(text))
    if not marks:
        return text.strip(), {}
    preamble = text[:marks[0].start()].strip()
    sections = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sections[m.group(1)] = text[m.end():end].strip()
    return preamble, sections


def validate_draft(text, mode: str, strings: dict) -> ParsedDraft:
    """Check the draft's STRUCTURE. Size is `budget`'s job.

    They are two different questions and deserve different exit codes: "this
    does not fit" is fixed by trimming, "this is put together wrong" is fixed by
    changing its shape. Merging them makes the model try the wrong remedy.
    """
    errors = []
    body = _strip_frontmatter(text if isinstance(text, str) else "").strip()
    if not body:
        return ParsedDraft(False, errors=[strings["errors"]["empty_draft"]])

    valid_sections = strings["sections"]
    required = valid_sections[strings["required_section"]]
    by_label = {normalize_label(v): (k, v) for k, v in valid_sections.items()}
    filler = {normalize_label(x) for x in strings["filler_words"]}

    preamble, raw = _split_sections(body)
    if preamble:
        errors.append(strings["errors"]["loose_text"])

    sections = {}
    for label, content in raw.items():
        key = by_label.get(normalize_label(label))
        if key is None:
            errors.append(strings["errors"]["unknown_section"].format(
                label=label, valid=", ".join(valid_sections.values())))
            continue
        slug, canonical = key
        if not content or normalize_label(content) in filler:
            errors.append(strings["errors"]["filler_section"].format(label=canonical))
            continue
        sections[slug] = (canonical, content)

    if strings["required_section"] not in sections:
        errors.append(strings["errors"]["missing_required"].format(label=required))

    if mode == "continue" and "next" not in sections:
        errors.append(strings["errors"]["continue_needs_next"].format(
            label=valid_sections["next"]))

    if errors:
        return ParsedDraft(False, errors=errors)

    order = [s for s in valid_sections if s in sections]
    clean = "\n\n".join(f"## {sections[s][0]}\n{sections[s][1]}" for s in order)
    return ParsedDraft(True, body=clean + "\n", sections=sections)


def compose(body, mode, date, branch, commit, context, strings) -> str:
    """Assemble the final file. This is the ONLY place that writes it."""
    header = [
        "---",
        f"baton: {VERSION}",
        f"mode: {mode}",
        f"date: {date}",
        f"branch: {branch}",
        f"commit: {commit}",
        "---",
        f"<!-- {strings['generated_notice']} -->",
        "",
        f"## {strings['context_section']}",
        context.rstrip(),
        "",
        "",
    ]
    return "\n".join(header) + body.strip() + "\n"


def extract_body(text, context_section: str = "Context") -> str:
    """What the model wrote: no frontmatter and no git section."""
    rest = _strip_frontmatter(text if isinstance(text, str) else "")
    skip = normalize_label(context_section)
    for m in RE_SECTION.finditer(rest):
        if normalize_label(m.group(1)) != skip:
            return rest[m.start():].strip() + "\n"
    return ""


def fingerprint(text, context_section: str = "Context") -> str:
    """A handoff's identity: its body alone.

    Deliberately ignores the frontmatter and the git context. If git counted,
    every commit would make the same handoff look new, and the "I already gave
    you this" notice would be worthless.
    """
    return hashlib.sha256(
        extract_body(text, context_section).encode("utf-8")
    ).hexdigest()[:16]
