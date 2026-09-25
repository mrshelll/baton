"""How full the session's context window is, read from the session transcript.

Hooks receive no figure about the context: the payload carries `transcript_path`
and nothing else of use. The transcript does carry it -- every answer records the
`usage` of its request -- and the sum of its three input fields IS the context
that request occupied. It is the same sum the statusline paints as
`total_input_tokens`.

Two rules, the same ones as `storage`:

1. Nothing here may raise towards a hook. The transcript is Claude Code's
   internal format and WILL change; when this module does not understand what
   it reads, it answers "I do not know" and baton stays quiet.
2. Only the tail of the file is read. A transcript reaches tens of MB and this
   runs at the end of every turn.

The reading is one answer behind, always. Claude Code writes the transcript a
step after its hooks run -- observed in a real session: when the tool hooks
fire, the answer that called the tool is not written yet, and at the first Stop
the newest entry is still that tool call, not the final text. So the figure
trails the statusline, which has it live, by the last answer: a few thousand
tokens, nothing next to a threshold. The very first tool call of a session has
nothing to measure at all, and baton stays quiet.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from lib import storage

#: Bytes read from the end of the transcript. The newest answer sat at most
#: 108 KB from the end across 146 real transcripts; this leaves room for more.
TAIL_BYTES = 262_144

#: Bytes read from the start, only to find the model identity when the tail has
#: none: Claude Code records it once, near the top.
HEAD_BYTES = 1_048_576

#: Lines scanned backwards in the tail, on top of the byte cap.
MAX_LINES = 400

#: Outside this range a figure is not a context size: it is garbage, or a format
#: that changed under us.
MIN_CREDIBLE = 10_000
MAX_CREDIBLE = 10_000_000

#: The window assumed for a model the table does not know.
DEFAULT_WINDOW = 200_000

#: The sizes a context window really comes in. An observation is rounded up to
#: one of these, not chased to the exact figure.
WINDOW_SIZES = (200_000, 1_000_000, 2_000_000)
ONE_MILLION = 1_000_000

#: The alias suffix that opens a 200k model to 1M (`opus[1m]` in settings).
SUFFIX_1M = "[1m]"

#: Environment variables, in precedence order. The hook inherits Claude Code's
#: environment, so whatever the user set there is what the harness uses too.
ENV_VARIABLES = ("CLAUDE_CODE_MAX_CONTEXT_TOKENS", "CLAUDE_CODE_AUTO_COMPACT_WINDOW")

#: The fields whose sum is the context. `output_tokens` is NOT one of them.
INPUT_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")

#: Base window per model, extracted from Claude Code 2.1.282 (`context.window`).
#: THIS IS WHAT GOES STALE: a model released after that version is not here, and
#: falls back to DEFAULT_WINDOW plus calibration. The frontier does not follow the
#: family -- within Opus it moves at 4.7, within Sonnet at 5 -- which is why this is
#: a table and not a rule.
MODEL_WINDOWS = {
    "claude-opus-5-5": 1_000_000,
    "claude-opus-5": 1_000_000,
    "claude-opus-4-8": 1_000_000,
    "claude-opus-4-7": 1_000_000,
    "claude-sonnet-5": 1_000_000,
    "claude-fable-5-1": 1_000_000,
    "claude-fable-5": 1_000_000,
    "claude-mythos-5-1": 1_000_000,
    "claude-mythos-5": 1_000_000,
    "claude-opus-4-6": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-opus-4-1": 200_000,
    "claude-opus-4-0": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-sonnet-4-0": 200_000,
    "claude-haiku-4-5": 200_000,
}

_DATE = re.compile(r"-\d{8}$")


@dataclass(frozen=True)
class Usage:
    tokens: int
    model: str


@dataclass(frozen=True)
class Reading:
    """One measurement. `known=False` is the only "I do not know", so a caller
    cannot forget to check for it."""
    known: bool
    tokens: int = 0
    model: str = ""
    budget: int = 0
    source: str = ""

    @property
    def percent(self) -> int:
        if not self.known or self.budget <= 0:
            return 0
        return int(100 * self.tokens / self.budget + 0.5)

    def at_least(self, percent) -> bool:
        """Exact integer comparison: the edge must not wobble on a float."""
        return self.known and self.budget > 0 and 100 * self.tokens >= percent * self.budget


UNKNOWN = Reading(known=False)


# --- reading the transcript -----------------------------------------------

def _chunks(path):
    """Lines from the tail and, when the file is longer than that, from the head.

    The line cut in half at each seam needs no special care: the piece of a JSONL
    line is never valid JSON -- it always lacks the outer object's other brace --
    so it fails to parse and is skipped like any other garbage.

    Only a path is opened: open() also takes an int, as a file descriptor, and
    closes it on the way out -- a `transcript_path` of 1 would close the hook's
    own stdout."""
    if not isinstance(path, (str, os.PathLike)) or not path:
        return [], []
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            start = max(0, fh.tell() - TAIL_BYTES)
            fh.seek(start)
            tail = fh.read()
            fh.seek(0)
            head = fh.read(min(HEAD_BYTES, start))
    except (OSError, ValueError):
        return [], []
    return tail.split(b"\n"), head.split(b"\n")


def _entries(lines, marker: bytes):
    """Objects from `lines`, newest first, skipping without parsing every line
    that cannot be what the caller looks for -- a tool result can be 150 KB."""
    for raw in reversed(lines[-MAX_LINES:]):
        if marker not in raw:
            continue
        try:
            entry = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        if isinstance(entry, dict):
            yield entry


def _context(usage):
    """The sum of the input fields; None when a field is not a count, because a
    shape we do not understand means the format changed."""
    total = 0
    for field in INPUT_FIELDS:
        value = usage.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        total += value
    return total


def _answer(lines):
    """(tokens, model) of the newest main-thread answer, or None.

    Answers measuring zero are skipped, not trusted: Claude Code writes
    "No response requested." as an assistant entry with model <synthetic> and
    every counter at zero, and taking it as the latest would read 0%."""
    for entry in _entries(lines, b'"usage"'):
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        message = entry.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        tokens = _context(usage)
        if tokens is None or tokens > MAX_CREDIBLE:
            return None
        if tokens > 0:
            model = message.get("model")
            return tokens, model if isinstance(model, str) else ""
    return None


def _identity(lines) -> str:
    """The model id Claude Code records with its window suffix. The newest wins."""
    for entry in _entries(lines, b'"modelId"'):
        if entry.get("isSidechain"):
            continue
        attachment = entry.get("attachment")
        identity = attachment.get("identity") if isinstance(attachment, dict) else None
        model_id = identity.get("modelId") if isinstance(identity, dict) else None
        if isinstance(model_id, str) and model_id:
            return model_id  # _entries walks newest first
    return ""


def _base(model: str) -> str:
    """`claude-haiku-4-5-20251001[1m]` -> `claude-haiku-4-5`."""
    if model.lower().endswith(SUFFIX_1M):
        model = model[: -len(SUFFIX_1M)]
    return _DATE.sub("", model)


def read_usage(path):
    """The newest main-thread answer's context and model, or None.

    The model comes from the identity attachment when it names the same model
    that answered: only there does the `[1m]` suffix survive. When they differ
    the session switched models, and the one answering is the one that counts.
    """
    tail, head = _chunks(path)
    found = _answer(tail)
    if found is None:
        return None
    tokens, answering = found
    identity = _identity(tail) or _identity(head)
    if identity and (not answering or _base(identity) == _base(answering)):
        return Usage(tokens, identity)
    return Usage(tokens, answering or identity)


# --- deciding what 100% is ------------------------------------------------

def model_window(model) -> int:
    """The window for a model id, 0 when the table does not know it. Exact
    lookup after dropping the date: a prefix match would read a future
    `opus-4-10` as `opus-4-1`."""
    if not isinstance(model, str) or not model:
        return 0
    size = MODEL_WINDOWS.get(_base(model), 0)
    if size and model.lower().endswith(SUFFIX_1M):
        return max(size, ONE_MILLION)
    return size


def snap_up(tokens: int) -> int:
    for size in WINDOW_SIZES:
        if tokens <= size:
            return size
    return -(-tokens // ONE_MILLION) * ONE_MILLION


def _size(value) -> int:
    ok = (isinstance(value, int) and not isinstance(value, bool)
          and MIN_CREDIBLE <= value <= MAX_CREDIBLE)
    return value if ok else 0


def _env_size(value) -> int:
    # isdecimal, not isdigit: "²" is a digit, and int() refuses it.
    if not isinstance(value, str) or not value.strip().isdecimal():
        return 0
    return _size(int(value))


def calibrate(seen, model: str, tokens: int):
    """Raise the highest context observed for `model`; never lower it.

    Pure: returns (new mapping, changed). The key is the full model id, suffix
    included, so a 200k session and a 1M session of the same model do not share
    a mark."""
    marks = dict(seen) if isinstance(seen, dict) else {}
    if not model or not (MIN_CREDIBLE <= tokens <= MAX_CREDIBLE):
        return marks, False
    if _size(marks.get(model)) >= tokens:
        return marks, False
    marks[model] = tokens
    return marks, True


def resolve_budget(model, *, seen=0, env=None, budget_tokens=0, settings_window=0):
    """(budget, source). The first declared size wins, in the order below.

    Then the ratchet: an observation of N tokens is physical proof the window is
    at least N, so a bigger observation beats any declaration. It never lowers
    the budget, which is why no compaction bookkeeping is needed -- a compaction
    only shrinks what is observed."""
    env = env or {}
    declared = [(_env_size(env.get(name)), "env") for name in ENV_VARIABLES]
    declared += [(_size(budget_tokens), "config"), (_size(settings_window), "settings"),
                 (model_window(model), "model"), (DEFAULT_WINDOW, "default")]
    size, source = next((s, src) for s, src in declared if s)
    observed = snap_up(seen) if _size(seen) else 0
    if observed > size:
        return observed, "calibrated"
    return size, source


def settings_window(root, home=None) -> int:
    """`autoCompactWindow` from Claude Code's settings: local, then project, then
    user. 0 when none sets a credible number."""
    try:
        home = Path.home() if home is None else Path(home)
    except (RuntimeError, OSError):
        home = None
    candidates = [Path(root) / ".claude" / "settings.local.json",
                  Path(root) / ".claude" / "settings.json"]
    if home is not None:
        candidates.append(home / ".claude" / "settings.json")
    for path in candidates:
        size = _size(storage.read_json(path).get("autoCompactWindow"))
        if size:
            return size
    return 0


def assess(transcript_path, *, seen=None, env=None, budget_tokens=0, settings_window=0):
    """The single entry point for the hook: (Reading, marks, marks_changed)."""
    usage = read_usage(transcript_path)
    if usage is None:
        return UNKNOWN, seen, False
    marks, changed = calibrate(seen, usage.model, usage.tokens)
    budget, source = resolve_budget(
        usage.model, seen=marks.get(usage.model, 0), env=env,
        budget_tokens=budget_tokens, settings_window=settings_window)
    return Reading(True, usage.tokens, usage.model, budget, source), marks, changed


def tier_reached(reading: Reading, thresholds, fired, min_tokens: int = 0):
    """The highest threshold crossed, or None when it was already consumed.

    The highest, not the lowest: a session resumed at 88% must be interrupted
    once, not once for 65 and again for 85. The caller marks every threshold up
    to the one returned as consumed."""
    if not reading.known or reading.tokens < min_tokens:
        return None
    crossed = [t for t in thresholds if reading.at_least(t)]
    if not crossed:
        return None
    top = max(crossed)
    return None if top in fired else top
