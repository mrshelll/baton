"""From a file on disk to the model's context: sanitize, wrap, cap.

The handoff document is committed and travels with the repo. Anyone who clones
someone else's repo gets whatever that file says injected into their context, so
it is treated here as UNTRUSTED input: it is cleaned, it is prevented from
closing its own tag, and it is explicitly declared to be data rather than
instructions.

The other half of the job is staying under the harness ceiling (8,000 characters
/ 200 lines). If the document was hand-edited past it, baton trims on whole-line
boundaries and says so -- instead of letting the harness cut mid-sentence in
silence.
"""
from __future__ import annotations

import json
import os
import re
import textwrap
import unicodedata
from pathlib import Path

from lib import budget, document

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_LANGUAGE = "en"

#: Characters that must never reach the context: C0/C1 controls (except newline
#: and tab), direction overrides and zero-width spaces. The last two groups
#: exist to make text appear to say something other than what it says, which is
#: exactly what we do not want in a file that travels inside a repo.
_ALLOWED = {"\n", "\t"}
_INVISIBLE = {
    "​", "‌", "‍", "⁠", "﻿",
    "‪", "‫", "‬", "‭", "‮",
    "⁦", "⁧", "⁨", "⁩",
}
_DROPPED_CATEGORIES = ("Cc", "Cf", "Co", "Cs")


def available_languages() -> list:
    return sorted(p.stem for p in (PLUGIN_ROOT / "templates").glob("*.json"))


def load_strings(language: str = DEFAULT_LANGUAGE) -> dict:
    """User-facing strings live in templates/, never in the code.

    An unknown language falls back to English rather than failing: a typo in the
    config must not stop a handoff from being written.
    """
    path = PLUGIN_ROOT / "templates" / f"{language}.json"
    if not path.is_file():
        path = PLUGIN_ROOT / "templates" / f"{DEFAULT_LANGUAGE}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize(text) -> str:
    """Clean the document before it touches the context. Never raises."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if not isinstance(text, str):
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    clean = []
    for c in text:
        if c in _ALLOWED:
            clean.append(c)
        elif c in _INVISIBLE or unicodedata.category(c) in _DROPPED_CATEGORIES:
            continue
        else:
            clean.append(c)
    return "".join(clean)


def _disable_closing_tag(text: str, tag: str) -> str:
    """Stop the content from closing its own tag.

    Without this, a document containing the closing tag could push the rest of
    its text outside the block marked as data, and whatever followed would read
    as higher-level instructions.
    """
    return text.replace(f"</{tag}>", f"<⁄{tag}>")


#: A project name is a directory name, and directory names travel inside cloned
#: repos. Same treatment as the document body, plus a cap: one 300-character name
#: would push the whole listing out of the budget on its own.
MAX_NAME = 60


def _name_column(cards):
    """(names, width) for a project listing: cleaned, capped, ready to align.

    The index and the receipt list the same projects in two different places.
    The cap lives here once because a name capped on one side and not the other
    is the same 300-character directory name blowing up whichever side forgot.
    """
    names = [sanitize(card.name)[:MAX_NAME] for card in cards]
    return names, max((len(n) for n in names), default=0)


def _age(date: str, strings: dict) -> str:
    from lib import gitinfo
    days = gitinfo.days_since(date)
    if days is None:
        return strings["index"]["age_unknown"]
    if days >= 1:
        return strings["index"]["age_days"].format(n=int(days))
    hours = int(days * 24)
    return (strings["index"]["age_now"] if hours < 1
            else strings["index"]["age_hours"].format(n=hours))


def index_block(root, cards, strings=None, truncated: bool = False) -> str:
    """The index injected when the root holds several projects.

    It grants nothing. Receiving a list of what exists is not receiving context,
    and it is certainly not authorisation to work: the same decision the memory
    mode makes, one level up.
    """
    s = strings or load_strings()
    i = s["index"]
    tag = i["tag"]

    names, width = _name_column(cards)

    # The disabling is applied to the lines and NOT to the finished block: the
    # names come from directories and are untrusted, but the block's own closing
    # tag is ours and neutering it would leave the index open.
    lines = [
        _disable_closing_tag(
            i["line"].format(name=name.ljust(width), mode=card.mode.ljust(8),
                             age=_age(card.date, s), rel=sanitize(card.rel)[:200]), tag)
        for name, card in zip(names, cards)
    ]

    head = [f'<{tag} root="{sanitize(str(root))}" count="{len(cards)}">', "", i["header"], ""]
    tail = ["", i["footer"], ""] + ([i["truncated"], ""] if truncated else []) + [f"</{tag}>"]
    fixed = "\n".join(head + tail) + "\n"

    room_chars = budget.CEILING_CHARACTERS - len(fixed) - len(i["and_more"]) - 2
    room_lines = budget.CEILING_LINES - len(fixed.split("\n")) - 2
    shown, cut = budget.trim_to_lines("\n".join(lines), room_chars, room_lines)

    body = [shown.rstrip("\n")]
    if cut:
        body.append(i["and_more"].format(n=len(lines) - len(shown.rstrip("\n").split("\n"))))

    return "\n".join(head + body + tail)


#: Content lines the receipt may spend. Every line is reprinted by the harness
#: with its own "SessionStart:<source> says: " prefix, so this is a noise budget,
#: not a space one: five lines is a glance, twenty is a wall -- which is why the
#: config refuses anything past MAX_RECEIPT_LINES.
DEFAULT_RECEIPT_LINES = 8
MAX_RECEIPT_LINES = 20

#: Columns the receipt wraps to. The hook runs with no terminal -- no tty, no
#: COLUMNS -- so this cannot be measured, only chosen: a comfortable measure
#: that a narrow window soft-wraps once and loses nothing by it. COLUMNS is read
#: anyway in case a future harness sets it.
RECEIPT_WIDTH = 92

#: Enough of a label to name a section. Unlike the items, a label that does not
#: fit has nothing to lose by being cut: it is a heading, not a sentence.
MAX_RECEIPT_LINE = 110

#: A list marker the author wrote themselves. Kept as-is -- they numbered the
#: questions so an answer could name one, and renumbering breaks "answer 2".
RE_LIST_MARKER = re.compile(r"^\s*(?:[-*+\u2022]|\d{1,3}[.)])\s+")

#: Emphasis markers render as literal asterisks in a terminal, so they are noise
#: exactly where the text has to be scannable.
RE_EMPHASIS = re.compile(r"\*\*|__")


def _clip(text: str) -> str:
    text = " ".join(sanitize(text).split())
    return text if len(text) <= MAX_RECEIPT_LINE else text[:MAX_RECEIPT_LINE - 1] + "\u2026"


def _width() -> int:
    try:
        columns = int(os.environ.get("COLUMNS", "0"))
    except ValueError:
        return RECEIPT_WIDTH
    return columns - 4 if 60 <= columns <= 200 else RECEIPT_WIDTH


def _item(text: str) -> list:
    """One line of the document -> the display lines it takes.

    Wrapping instead of cutting is not decoration. baton's whole argument is
    that a handoff cut mid-sentence lies, and the first real use of the receipt
    cut a question at a fixed column exactly where the decision was: "do I carry
    on with the heavy one, do the four light ones fir...". The budget is spent in
    whole items for the same reason the document is trimmed in whole lines.

    The hanging indent is what makes the shape readable: the continuation of an
    item sits under its text, so a new marker at the left margin is visibly a new
    item and not more of the last one.
    """
    text = RE_EMPHASIS.sub("", " ".join(sanitize(text).split()))
    if not text:
        return []
    found = RE_LIST_MARKER.match(text)
    marker = text[found.start():found.end()].strip() + " " if found else "\u2022 "
    body = text[found.end():] if found else text
    width = max(_width() - len(marker), 24)
    wrapped = textwrap.wrap(body, width=width) or [""]
    return [marker + wrapped[0]] + [" " * len(marker) + line for line in wrapped[1:]]


def _labels_everywhere() -> tuple:
    """({slug: {normalised label in every language}}, {labels of the git section}).

    A handoff travels inside a repo, so the config that READS one is not
    necessarily the config that wrote it. Matching only the configured labels
    leaves a Spanish document unreadable to an English session: its git section
    survives `extract_body` and gets shown as if it were the work, and its
    `Bloqueos` stops being recognised as the blockers. Cheap to ask every
    language; there are two.
    """
    by_slug: dict = {}
    context = set()
    for language in available_languages():
        s = load_strings(language)
        for slug, label in s["sections"].items():
            by_slug.setdefault(slug, set()).add(document.normalize_label(label))
        context.add(document.normalize_label(s["context_section"]))
    return by_slug, context


def _what_was_left(sections: dict, mode: str):
    """(label, content, other labels) -- what the session left behind.

    The order differs by mode because "what was left" means different things:
    in continue mode the next step IS the leftover, and in memory mode what is
    open is. And the leftover is not always a question -- most often it is a
    step written down, or just a state that says what is still missing -- so
    this falls through all three rather than looking for questions.
    """
    order = ("next", "blockers", "state") if mode == "continue" else ("blockers", "next", "state")
    known, context_labels = _labels_everywhere()
    left = {label: content for label, content in sections.items()
            if document.normalize_label(label) not in context_labels}
    # Only a section with something LEFT TO SHOW can be what was left behind:
    # `_clip` is the same pass the receipt prints through, so a section that
    # survives `strip` but vanishes under it does not get picked and then
    # printed as a bare label with nothing after it.
    by_norm = {document.normalize_label(label): label
               for label, content in left.items() if _clip(content)}

    chosen = None
    for slug in order:
        chosen = next((by_norm[n] for n in known.get(slug, ()) if n in by_norm), None)
        if chosen is not None:
            break
    if chosen is None:
        # A handoff written in another language, or hand-edited: show the first
        # section there is. Showing something beats matching a label.
        chosen = next(iter(by_norm.values()), None)
    if chosen is None:
        return "", "", []
    return chosen, left[chosen], [label for label in left if label != chosen]


def _body(items, label, others, max_lines, r) -> list:
    """Fit whole items into the line budget, and account for what did not.

    The label owns a line and the tail owns another, so the shape is legible at a
    glance: heading, items, then one line saying what is not here. Both are given
    up when the budget is too small to afford them -- a receipt of two lines is
    better spent on the content than on its furniture.
    """
    room = max_lines
    head = []
    if room >= 3:
        head.append(r["section_label"].format(label=_clip(label)))
        room -= 1
    tail_slot = 1 if room >= 2 else 0
    room -= tail_slot

    shown, left_out = [], 0
    for item in items:
        if left_out or len(item) > room:
            left_out += 1   # once one does not fit, the rest keep their order
            continue
        shown += item
        room -= len(item)

    parts = []
    if left_out:
        parts.append(r["tail_left_out"].format(n=left_out))
    if others:
        parts.append(r["tail_sections"].format(rest=", ".join(_clip(o) for o in others)))

    out = head + [f"  {line}" for line in shown]
    if parts and tail_slot:
        out.append(r["tail"].format(parts=" \u00b7 ".join(parts)))
    return out


def receipt(document_text="", mode="", strings=None, cards=(), stale=False,
            max_lines=DEFAULT_RECEIPT_LINES, lines=0) -> str:
    """What baton puts in front of the HUMAN when a session starts.

    The handoff goes to the model's context and never to the screen, so whoever
    wrote it could not see what they had left without spending a turn asking for
    it back -- and that turn starts with "let's carry on", which is also what
    names the session in the resume list ever after. This is the one channel
    that reaches the person without a model turn.

    It EXTRACTS, it does not summarise: baton never writes prose about the work.
    """
    s = strings or load_strings()
    r = s["receipt"]
    cards = list(cards)
    out = []

    if document_text:
        fields = document.read_fields(document_text)
        out.append(r["handoff"].format(
            mode=mode, lines=lines or len(document_text.splitlines()),
            age=_age(fields.get("date", ""), s),
            extra=r["stale"] if stale else ""))
        if max_lines > 0:
            sections = document.read_sections(document_text, s["context_section"])
            label, content, others = _what_was_left(sections, mode)
            items = [lines for lines in (_item(line) for line in content.split("\n")) if lines]
            if items:
                out += _body(items, label, others, max_lines, r)
        if cards:
            out.append(r["also_projects"].format(n=len(cards)))
        return "\n".join(out)

    if cards:
        out.append(r["projects"].format(n=len(cards)))
        names, width = _name_column(cards)
        for name, card in zip(names[:max_lines], cards):
            out.append(r["project_line"].format(
                name=_clip(name).ljust(width), mode=card.mode.ljust(8),
                age=_age(card.date, s)))
        if len(cards) > max_lines:
            # Saying nothing here reads as "that is all of them", which is the
            # one thing a list of what exists must never get wrong.
            out.append(s["index"]["and_more"].format(n=len(cards) - max_lines))
    return "\n".join(out)


def wrap(body, mode, written, source, freshness_notice="", repeat=None,
         strings=None, index="") -> str:
    """Build the exact text injected as `additionalContext`.

    Deliberate order: the mode instruction first (it is the one thing that must
    not be lost), then the notices (they change how the document should be
    read), and the document last. That way what matters survives any trim.
    """
    s = strings or load_strings()
    tag = s["tag"]

    head = [
        f'<{tag} mode="{mode}" written="{written}" source="{source}">',
        "",
        s["instructions"].get(mode, s["instructions"][document.SAFE_MODE]),
        "",
    ]
    if freshness_notice:
        head += [freshness_notice, ""]
    if repeat:
        head += [s["repeat_notice"].format(**repeat), ""]
    head += [s["data_warning"], ""]

    tail = [s["document_close"], f"</{tag}>"]
    if index:
        # Inside `tail`, not concatenated by the caller: `fixed` below is what
        # decides how much room the document gets, and an index bolted on
        # afterwards would be room nobody measured.
        tail += ["", index]
    clean_body = _disable_closing_tag(sanitize(body), tag)

    # What is left for the document is the ceiling minus everything else,
    # computed with the wrapper already built rather than with a fixed reserve:
    # that way a long freshness notice cannot push the total over the top.
    fixed = "\n".join(head + [s["document_open"]] + tail) + "\n"
    trim_notice = s["trimmed_notice"]
    room_chars = budget.CEILING_CHARACTERS - len(fixed) - len(trim_notice) - 2
    room_lines = budget.CEILING_LINES - len(fixed.split("\n")) - 2

    shown, trimmed = budget.trim_to_lines(clean_body, room_chars, room_lines)

    parts = list(head)
    if trimmed:
        parts += [trim_notice, ""]
    parts += [s["document_open"], shown.rstrip("\n")] + tail
    return "\n".join(parts)
