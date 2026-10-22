"""Paths, activation, log and writing. Everything that touches disk inside a project.

Two rules that repeat across the codebase and start in this module:

1. Nothing here may raise towards a hook. A broken handoff cannot stop a session
   from starting.
2. Everything volatile hangs off `.baton/local/`, so the user has ONE line to put
   in their .gitignore.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

#: How far up we look for the project root. A cap stops an odd cwd from walking
#: the whole disk on every session start.
MAX_LEVELS = 20

#: Markers identifying a project root, in priority order.
ROOT_MARKERS = (".git", ".claude", ".baton")

#: The log is forensic evidence, not a log file: it is capped and never rotated.
LOG_MAX_LINES = 200

#: An orphaned lock (dead process, suspended laptop) must not block a project
#: forever. Past this age it is considered garbage.
LOCK_EXPIRY_SECONDS = 60

#: How many compaction summaries are kept. They are working material, not an
#: archive: the latest few are enough and the cost stays bounded.
SUMMARIES_MAX = 3

#: Only files matching EXACTLY this are ever deleted from the history. If
#: someone leaves their own notes in there, baton does not touch them.
RE_HISTORY = re.compile(r"^HANDOFF-\d{8}T\d{6}Z-(continue|memory)(?:-\d+)?\.md$")

_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class BusyError(RuntimeError):
    """Another session is writing the handoff right now."""


class StorageError(RuntimeError):
    """Cannot write: permissions, disk, impossible path."""


def project_root(cwd) -> Path:
    """Walk up from `cwd` until a project root marker appears.

    `.git` counts whether it is a directory or a file: in a git worktree it is a
    file pointing at the real repo, and treating it as a directory only would
    leave worktree users out.

    With no marker found it returns `cwd` itself: operating in the current
    directory beats failing. Never raises.
    """
    current = Path(cwd)
    try:
        current = current.resolve(strict=False)
    except OSError:
        pass
    for _ in range(MAX_LEVELS):
        for marker in ROOT_MARKERS:
            if (current / marker).exists():
                return current
        if current.parent == current:
            break
        current = current.parent
    try:
        return Path(cwd).resolve(strict=False)
    except OSError:
        return Path(cwd)


class Paths:
    """baton's paths inside a project. Computes them; creates nothing unasked."""

    def __init__(self, root, document_rel: str = ".baton/HANDOFF.md"):
        self.root = Path(root)
        self.document = self.root / document_rel
        # Volatile state ALWAYS hangs off .baton/local/, even when the document
        # was moved elsewhere, so the .gitignore stays one line.
        self.baton = self.root / ".baton"
        self.local = self.baton / "local"
        self.history = self.local / "history"
        self.auto = self.local / "auto"
        self.draft = self.local / "draft.md"
        self.deliveries = self.local / "deliveries.json"
        self.attempts = self.local / "attempts.json"
        self.pending = self.local / "pending.json"
        self.window = self.local / "window.json"
        self.compact_request = self.local / "compact-request.json"
        self.log = self.local / "log.jsonl"
        self.lock = self.local / ".lock"

    def ensure_local(self) -> None:
        self.local.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Paths({self.root!s})"


def is_enabled(root, document_rel: str = ".baton/HANDOFF.md") -> bool:
    """A project is enabled once its handoff document exists.

    baton installs at user level, so it runs in EVERY project. Seeding files
    into each repo someone opens would be intrusive, and the document itself is
    the cleanest signal that it was wanted here: no init command and no global
    registry to fall out of sync when folders move.
    """
    try:
        return Paths(root, document_rel).document.is_file()
    except OSError:
        return False


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime(_UTC_FORMAT)


def from_utc(text):
    """Parse a stamp written by `now_utc`. Returns None for anything else."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, _UTC_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _utc_stamp() -> str:
    """UTC on purpose: alphabetical order is chronological order, with no
    surprises from time zones or daylight saving."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path) -> dict:
    """Any garbage -- invalid JSON, valid JSON that is not an object, an empty
    file -- reads back as {}. State files can be touched by an editor, a merge
    or a session killed mid-write, and none of that may raise towards a hook."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path, data: dict) -> None:
    """Creates its own parent: `projects.py` writes state next to a Paths it does
    not build."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _free_name(folder: Path, base: str) -> Path:
    """Two writes in the same second must not overwrite each other."""
    target = folder / base
    suffix = 2
    stem, dot, ext = base.rpartition(".")
    while target.exists():
        target = folder / f"{stem}-{suffix}{dot}{ext}"
        suffix += 1
    return target


def log_event(paths: Paths, event: str, result: str, **extra) -> None:
    """Record that a hook ran.

    This is the only thing that tells "the hook did not fire" apart from "it
    fired and stayed quiet because there was no document": identical from the
    outside, opposite causes. Hence it is written ALWAYS, silence included.

    Never raises: if it cannot be written, the entry is lost and that is that.
    """
    entry = {"ts": now_utc(), "event": event, "result": result}
    entry.update(extra)
    try:
        paths.ensure_local()
        previous = []
        if paths.log.exists():
            text = paths.log.read_text(encoding="utf-8", errors="replace")
            previous = [l for l in text.split("\n") if l.strip()]
        previous.append(json.dumps(entry, ensure_ascii=False))
        tmp = paths.log.with_suffix(f".jsonl.tmp-{os.getpid()}")
        tmp.write_text("\n".join(previous[-LOG_MAX_LINES:]) + "\n", encoding="utf-8")
        os.replace(tmp, paths.log)
    except Exception:
        pass


# --- writing the document -------------------------------------------------

_BUSY = "another session is writing the handoff; try again"


class _Lock:
    """Per-file lock with an expiry.

    O_CREAT|O_EXCL is atomic on POSIX and Windows, so two processes cannot
    create it at once. The expiry exists because a lock without one turns any
    dead process into a permanent block.
    """

    def __init__(self, path: Path):
        self.path = path
        self._mine = False

    def _take(self) -> bool:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            self._mine = True
            return True
        except FileExistsError:
            return False
        except OSError as exc:
            raise StorageError(f"cannot lock {self.path}: {exc}") from exc

    def _age(self) -> float:
        try:
            return time.time() - self.path.stat().st_mtime
        except OSError:
            return 0.0

    def __enter__(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"cannot create {self.path.parent}: {exc}") from exc
        if self._take():
            return self
        if self._age() <= LOCK_EXPIRY_SECONDS:
            raise BusyError(_BUSY)
        self.path.unlink(missing_ok=True)  # expired lock: steal it
        if not self._take():
            raise BusyError(_BUSY)
        return self

    def __exit__(self, *exc):
        if self._mine:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def _rotate(paths: Paths, history_max: int) -> None:
    """Archive the CURRENT document before replacing it.

    The mode in the name is read from the file being archived, not from the one
    coming in: someone looking for "the last continue handoff" wants the mode it
    was written with, not the mode of whatever replaced it.

    Only called with history_max > 0, so `_prune` never sees a zero.
    """
    if history_max <= 0 or not paths.document.is_file():
        return
    from lib import document
    try:
        mode = document.read_mode(paths.document.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        mode = document.SAFE_MODE
    paths.history.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths.document, _free_name(paths.history, f"HANDOFF-{_utc_stamp()}-{mode}.md"))
    _prune(paths, history_max)


def _prune(paths: Paths, history_max: int) -> None:
    for old in sorted(p for p in paths.history.glob("*.md")
                      if RE_HISTORY.match(p.name))[:-history_max]:
        try:
            old.unlink()
        except OSError:
            pass


def write_document(paths: Paths, content: str, history_max: int = 10) -> Path:
    """Write the handoff atomically, rotating the previous one.

    Order matters: nothing is touched until the content is ready, and the final
    file appears in one step through os.replace(). A concurrent reader sees the
    old document whole or the new one whole, never one half-written.
    """
    with _Lock(paths.lock):
        try:
            paths.document.parent.mkdir(parents=True, exist_ok=True)
            _rotate(paths, history_max)
            tmp = paths.document.with_name(f".{paths.document.name}.tmp-{os.getpid()}")
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, paths.document)
        except OSError as exc:
            raise StorageError(f"cannot write {paths.document}: {exc}") from exc
        try:
            paths.draft.unlink(missing_ok=True)
            paths.attempts.unlink(missing_ok=True)
        except OSError:
            pass
    return paths.document


# --- delivery register ----------------------------------------------------

def record_delivery(paths: Paths, fingerprint: str, count: bool = True):
    """Track how many times THIS handoff has been delivered.

    It exists so the model can be told "I already gave you this three times":
    without that notice, a handoff nobody replaced looks like news every session
    and the model repeats work already done.

    It never destroys the note on read. Plenty of sessions start and end without
    writing a new handoff -- a one-shot invocation, for instance -- and consuming
    the note there would leave the next human session with no context.

    Returns None the first time, or {"times": N, "when": "..."} on a repeat.
    """
    data = read_json(paths.deliveries)
    if data.get("fingerprint") != fingerprint:
        data = {"fingerprint": fingerprint, "times": 0, "first": now_utc(), "last": ""}

    previous = int(data.get("times") or 0)
    before = data.get("last") or data.get("first") or ""

    if count:
        data["times"] = previous + 1
        data["last"] = now_utc()
        write_json(paths.deliveries, data)

    if previous <= 0:
        return None
    return {"times": previous, "when": before or "earlier"}


# --- automatic cycle: compaction summary and pending flag -----------------

def save_summary(paths: Paths, summary: str, trigger: str = "auto") -> None:
    """Keep the `compact_summary` on disk so it can be used afterwards."""
    try:
        paths.auto.mkdir(parents=True, exist_ok=True)
        target = _free_name(paths.auto, f"summary-{_utc_stamp()}.md")
        target.write_text(
            f"<!-- compaction summary (trigger: {trigger}), saved by baton -->\n\n"
            + (summary or "(the compaction produced no summary)\n"),
            encoding="utf-8")
        for old in sorted(paths.auto.glob("summary-*.md"))[:-SUMMARIES_MAX]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def arm_pending(paths: Paths, session_id: str = "") -> None:
    """Flag that a compaction happened with no handoff written.

    `last_request` is preserved on purpose: the cooldown measures from the last
    time the user was interrupted, and clearing it here would let every new
    compaction reset it, so the cooldown would hold nothing back.
    """
    data = read_json(paths.pending)
    data.update({"armed": now_utc(), "session": session_id, "requested": False})
    write_json(paths.pending, data)


def cooldown_clear(paths: Paths, cooldown_minutes: int = 30) -> bool:
    """True when no handoff was requested within the cooldown.

    ONE clock for every reason to interrupt -- a compaction or a full window --
    because what it protects is the person, not a particular mechanism: two
    requests thirty seconds apart are the failure it exists to prevent, whoever
    makes them.
    """
    last = from_utc(read_json(paths.pending).get("last_request"))
    if not last or not cooldown_minutes:
        return True
    return (datetime.now(timezone.utc) - last).total_seconds() >= cooldown_minutes * 60


def has_pending(paths: Paths, cooldown_minutes: int = 30) -> bool:
    """True when the handoff should be requested.

    The cooldown measures from the LAST request, not from the compaction: what
    must be avoided is interrupting the user twice in a row, not missing a
    compaction.
    """
    data = read_json(paths.pending)
    # `armed`, not merely a file: a request for a full window leaves this file
    # holding only the cooldown stamp, and that is no compaction.
    if not data.get("armed") or data.get("requested"):
        return False
    return cooldown_clear(paths, cooldown_minutes)


def consume_pending(paths: Paths) -> None:
    """Mark the flag as used. At most one request per compaction."""
    data = read_json(paths.pending)
    data["requested"] = True
    data["last_request"] = now_utc()
    write_json(paths.pending, data)


def note_request(paths: Paths) -> None:
    """Stamp the cooldown clock and NOTHING else.

    It is what a request for a full window leaves behind. `armed` and
    `requested` belong to the compaction, and a request made for another reason
    says nothing about them."""
    data = read_json(paths.pending)
    data["last_request"] = now_utc()
    write_json(paths.pending, data)


#: How long a compaction note says "this session is ready to start over".
COMPACT_NOTE_HOURS = 12


def _note_age_ok(note: dict, max_age_hours: int) -> bool:
    when = from_utc(note.get("requested_at"))
    if when is None:
        return False
    age = (datetime.now(timezone.utc) - when).total_seconds()
    return 0 <= age <= max_age_hours * 3600


def compact_notes(paths: Paths) -> dict:
    """Every session's compaction note, keyed by session id, cleaned.

    One note per session: two sessions in one project compact on their own,
    and the second one's PreCompact must not erase that the first one's handoff
    is ready. A file in the single-note shape that preceded this reads as one
    entry. A note filed under another session's key is garbage."""
    data = read_json(paths.compact_request)
    sessions = data.get("sessions")
    if sessions is None and isinstance(data.get("session"), str):
        sessions = {data["session"]: data}
    if not isinstance(sessions, dict):
        return {}
    return {sid: note for sid, note in sessions.items()
            if isinstance(sid, str) and isinstance(note, dict) and note.get("session") == sid}


def _newest_written(notes: dict):
    written = [(from_utc(n.get("written_at")), sid) for sid, n in notes.items()
               if n.get("written") is True and from_utc(n.get("written_at")) is not None]
    return max(written)[1] if written else None


def _save_notes(paths: Paths, notes: dict) -> None:
    write_json(paths.compact_request, {"sessions": notes})


def note_compact_request(paths: Paths, session_id: str) -> None:
    """Record that this session's PreCompact asked the summarizer for the block.

    The SessionStart of `compact` runs before -- or alongside -- the PostCompact,
    so it cannot know whether the block came out. This note is what it can know:
    that one was asked for, by which session. It replaces this session's
    previous note, never another session's. Notes past their age are pruned
    here, except the newest written one: it may still describe the handoff on
    disk, and the panel reads who wrote it from there."""
    notes = compact_notes(paths)
    keep = _newest_written(notes)
    notes = {sid: n for sid, n in notes.items()
             if sid == keep or _note_age_ok(n, COMPACT_NOTE_HOURS)}
    notes[session_id] = {"session": session_id, "requested_at": now_utc(), "written": False}
    _save_notes(paths, notes)


def mark_compact_written(paths: Paths, session_id: str, fingerprint: str) -> None:
    """Record on this session's note that the block came out and was written.

    Only on a note that is this session's: marking another one would tell its
    SessionStart a handoff exists that nobody wrote for it."""
    notes = compact_notes(paths)
    if not session_id or session_id not in notes:
        return
    notes[session_id].update({"written": True, "written_at": now_utc(),
                              "fingerprint": fingerprint})
    _save_notes(paths, notes)


def read_compact_request(paths: Paths, session_id: str,
                         max_age_hours: int = COMPACT_NOTE_HOURS):
    """The note, only when it belongs to `session_id` and is recent; else None.

    An empty session id is no session: it would match any other note written
    without one. Garbage, a missing stamp or one from the future read as None,
    which is today's behaviour."""
    if not session_id:
        return None
    note = compact_notes(paths).get(session_id)
    if note is None or not _note_age_ok(note, max_age_hours):
        return None
    return note


# --- automatic handoff by context usage -----------------------------------

def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def read_window(paths: Paths, session_id: str) -> dict:
    """What the context trigger remembers, cleaned field by field.

    `marks` (the largest context seen per model) outlive the session: they are
    what was learnt about the window. `fired`, `announced` and `warned` belong to
    ONE session and start over when the session changes -- a /clear asks again.

    `announced` maps a tier, as text, to when it was announced: the panel
    compares it with the handoff's date to show whichever is newer. Records
    written before it existed have none, and the panel keeps its old order."""
    data = read_json(paths.window)
    marks = data.get("marks")
    marks = ({k: v for k, v in marks.items() if isinstance(k, str) and _is_count(v) and v > 0}
             if isinstance(marks, dict) else {})
    state = {"session": session_id, "marks": marks, "fired": [], "announced": {},
             "warned": False, "last": {}}
    if data.get("session") == session_id:
        fired = data.get("fired")
        if isinstance(fired, list):
            state["fired"] = sorted({n for n in fired if _is_count(n)})
        announced = data.get("announced")
        if isinstance(announced, dict):
            state["announced"] = {k: v for k, v in announced.items()
                                  if isinstance(k, str) and k.isdigit()
                                  and from_utc(v) is not None}
        state["warned"] = data.get("warned") is True
    if isinstance(data.get("last"), dict):
        state["last"] = data["last"]
    return state


def save_window(paths: Paths, state: dict) -> None:
    write_json(paths.window, state)


def stamp_announced(state: dict, tiers) -> None:
    """Record, in `state`, when each tier in `tiers` not yet stamped was
    announced. A tier keeps its first time: announcing 85 says nothing new
    about 65."""
    announced = dict(state.get("announced") or {})
    now = now_utc()
    for tier in tiers:
        announced.setdefault(str(tier), now)
    state["announced"] = announced


def last_announced(state: dict):
    """When the most recent of the session's fired tiers was announced, or None
    when none of them carries a time."""
    stamps = [from_utc(state.get("announced", {}).get(str(t))) for t in state.get("fired", [])]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None
