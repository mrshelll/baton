"""Measure the handoff and decide whether it fits. The core requirement lives here.

The ceiling is not a design preference. Verified against the Claude Code 2.1.259
binary, the context a hook injects through `additionalContext` is truncated at
8,000 characters or 200 lines, whichever comes first -- and silently:

    hKr = {..., additionalContext: 8000}   # characters
    yKr = {..., additionalContext: 200}    # lines

That is why a 931-line handoff is not merely expensive: it does not fit. It
arrives cut in half and nobody says so. The default limits are derived backwards
from that ceiling, leaving room for the wrapper (mode instruction, freshness
notice, warnings) that travels in the same field.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CEILING_CHARACTERS = 8000
CEILING_LINES = 200

#: What the wrapper takes in the worst reasonable case: a long mode
#: instruction, a freshness notice, a repeat notice and the tags.
WRAPPER_RESERVE_CHARACTERS = 1800
WRAPPER_RESERVE_LINES = 60

DEFAULT_LIMITS = {
    # Binding: this is the unit the harness truncates by.
    "characters": 6000,
    # The only one a human can see and fix. It comes first in the error.
    "lines": 120,
    # Informational: what the handoff costs at startup. Never rejects alone.
    "tokens": 1700,
}

#: `tokens` does not reject: it is an estimate, and rejecting on an estimate
#: would be asking the model to guess the tokenizer.
REJECTING_MEASURES = ("characters", "lines")

_WORD = re.compile(r"\S+")
_SECTION = re.compile(r"^##[ \t]+(.+?)[ \t\r]*$", re.MULTILINE)


def estimate_tokens(text) -> int:
    """Deterministic, dependency-free and deliberately PESSIMISTIC.

    3.6 characters per token: BPE over prose with markdown lands around 3.7-4.2,
    so 3.6 overestimates by roughly 10%. The max() against words*1.3 covers
    short-word text -- lists, paths, code -- where dividing by characters
    underestimates.

    This is informational. The limit that rules is `characters`, which is exact
    and is what the harness measures.
    """
    if not isinstance(text, str) or not text:
        return 0
    return int(max(len(text) / 3.6, len(_WORD.findall(text)) * 1.3) + 0.5)


@dataclass(frozen=True)
class Measurement:
    lines: int
    characters: int
    tokens: int


def measure(text) -> Measurement:
    if not isinstance(text, str) or not text:
        return Measurement(0, 0, 0)
    # rstrip: a trailing newline is not one more line.
    return Measurement(
        lines=len(text.rstrip("\n").split("\n")),
        characters=len(text),
        tokens=estimate_tokens(text),
    )


@dataclass(frozen=True)
class Verdict:
    fits: bool
    measurement: Measurement
    limits: dict
    excess: dict = field(default_factory=dict)


def evaluate(text, limits=None) -> Verdict:
    limits = dict(limits or DEFAULT_LIMITS)
    m = measure(text)
    excess = {}
    for name in REJECTING_MEASURES:
        limit = limits.get(name)
        value = getattr(m, name)
        if limit and value > limit:
            excess[name] = value - limit
    return Verdict(fits=not excess, measurement=m, limits=limits, excess=excess)


def lines_per_section(text) -> dict:
    """How many lines each section takes. Used to point at the guilty one."""
    if not isinstance(text, str) or not text:
        return {}
    marks = list(_SECTION.finditer(text))
    counts = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        chunk = text[m.start():end].rstrip("\n")
        counts[m.group(1)] = len(chunk.split("\n"))
    return counts


def report(verdict: Verdict, text, attempt: int, maximum: int, strings: dict,
           previous_path: str = ".baton/HANDOFF.md") -> str:
    """The rejection message.

    Three things it has to achieve: make clear nothing was lost, point at WHERE
    the excess is, and say how many attempts remain. A visible counter breaks
    more loops than any instruction.
    """
    m, t = verdict.measurement, verdict.limits
    rows = [
        ("characters", m.characters, t.get("characters")),
        ("lines", m.lines, t.get("lines")),
        ("tokens~", m.tokens, t.get("tokens")),
    ]
    out = [strings["budget"]["header"].format(path=previous_path), ""]
    for name, value, limit in rows:
        if not limit:
            continue
        state = "ok" if value <= limit else strings["budget"]["over"].format(n=value - limit)
        out.append(f"  {name:<11} {value:>6} / {limit:<6} {state}")

    counts = lines_per_section(text)
    if counts:
        worst = max(counts, key=counts.get)
        out += ["", strings["budget"]["per_section"]]
        for name, n in counts.items():
            mark = strings["budget"]["worst"] if name == worst else ""
            out.append(f"  {name:<26} {n:>4}{mark}")

    out += ["", strings["budget"]["how_to_trim"],
            "", strings["budget"]["attempt"].format(attempt=attempt, maximum=maximum)]
    return "\n".join(out)


def trim_to_lines(text, max_characters: int, max_lines: int):
    """Trim on WHOLE LINE boundaries. Returns (text, was_trimmed).

    Never cuts mid-sentence: a handoff cut in half lies, and a lie shaped like
    the truth is worse than an absence. Whoever calls this must declare the trim
    inside the document itself.
    """
    if not isinstance(text, str) or not text:
        return "", False
    lines = text.split("\n")
    kept, total = [], 0
    for line in lines:
        cost = len(line) + 1
        if len(kept) >= max_lines or total + cost > max_characters:
            break
        kept.append(line)
        total += cost
    if len(kept) == len(lines):
        return text, False
    trimmed = "\n".join(kept)
    if trimmed and not trimmed.endswith("\n"):
        trimmed += "\n"
    return trimmed, True
