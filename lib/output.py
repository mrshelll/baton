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

    # The disabling is applied to the lines and NOT to the finished block: the
    # names come from directories and are untrusted, but the block's own closing
    # tag is ours and neutering it would leave the index open.
    lines = [
        _disable_closing_tag(
            i["line"].format(name=sanitize(card.name)[:MAX_NAME], mode=card.mode,
                             age=_age(card.date, s), rel=sanitize(card.rel)[:200]), tag)
        for card in cards
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
