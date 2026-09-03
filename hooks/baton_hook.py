#!/usr/bin/env python3
"""Single dispatcher for baton's hooks.

Inviolable contract, and the reason this file exists instead of three: **this
process ALWAYS exits 0**. A corrupt handoff, a stdin that is not JSON or a full
disk cannot stop a Claude Code session from starting. All the logic sits inside
an `except BaseException` that degrades to a readable message.

The event arrives as argv[1] (`session-start`, `post-compact`, `stop`) because
hooks.json uses the `command: python3` + `args: [...]` form, which never goes
through a shell and is therefore immune to paths with spaces.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config, document, gitinfo, output, projects, storage  # noqa: E402


def _read_input() -> dict:
    """Read the payload from stdin. Any garbage becomes {}."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _emit(payload: dict) -> None:
    """Write the output JSON. An empty dict means silence."""
    if not payload:
        return
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


# --- handlers -------------------------------------------------------------
# Each one receives an already-enabled project and returns
# (output_payload, result_for_the_log).

def _session_start(entry: dict, paths: storage.Paths, cfg, root, found) -> tuple[dict, str]:
    """Inject the handoff, the index, or both."""
    source = entry.get("source") or "startup"
    if source not in cfg["inject_on"]:
        return {}, f"silent: '{source}' is not in inject_on"

    strings = output.load_strings(cfg["language"])

    index = ""
    if found.projects:
        cards = [projects.describe(p, cfg["document"]) for p in found.projects]
        index = output.index_block(root, cards, strings, truncated=found.truncated)

    if not paths.document.is_file():
        # Only the index: this root holds projects but has no handoff of its own.
        payload = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                          "additionalContext": index}}
        if cfg["receipt"]:
            payload["systemMessage"] = (
                f"baton: {len(found.projects)} project(s) available, none loaded")
        return payload, f"index injected: {len(found.projects)} projects"

    text = paths.document.read_text(encoding="utf-8", errors="replace")
    mode = document.read_mode(text)
    fields = document.read_fields(text)

    notice = gitinfo.freshness(paths.root, fields.get("date"), fields.get("branch", ""),
                               fields.get("commit", ""), strings).notice()

    # A compaction is not a new session: counting it would fire the "I already
    # gave you this" notice for something the user never did.
    repeat = storage.record_delivery(
        paths, document.fingerprint(text, strings["context_section"]),
        count=(source != "compact"),
    )

    context = output.wrap(
        body=document.extract_body(text, strings["context_section"]) or text,
        mode=mode, written=fields.get("date", "?"),
        source=str(paths.document.relative_to(paths.root)),
        freshness_notice=notice, repeat=repeat, strings=strings, index=index,
    )

    payload = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                      "additionalContext": context}}
    if cfg["receipt"]:
        # The receipt is the cheapest way to turn a silent failure into a
        # visible one: if this line is missing, the hook did not fire.
        payload["systemMessage"] = (
            f"baton: handoff injected -- {mode} mode, {len(context.splitlines())} lines"
            + (", with a freshness notice" if notice else "")
            + (f", plus {len(found.projects)} project(s) in the index" if index else "")
        )
    return payload, f"injected {mode} mode"


def _post_compact(entry: dict, paths: storage.Paths, cfg, root, found) -> tuple[dict, str]:
    """Save the compaction summary and arm the flag. Nothing else.

    Nothing can be drafted here: a compaction has no model turn, and the binary
    itself says so when it rejects `prompt`-type hooks -- "no conversation
    context is available". What it does have is `compact_summary`, the summary
    the harness just produced. It is kept as INPUT so the next Stop can ask for
    a properly written handoff.

    And it does not touch the handoff. Ever: a summary nobody wrote must not
    overwrite one written with judgement.
    """
    storage.save_summary(paths, entry.get("compact_summary") or "",
                         trigger=entry.get("trigger") or "auto")
    storage.arm_pending(paths, entry.get("session_id") or "")
    return {}, "summary saved, handoff pending"


def _stop(entry: dict, paths: storage.Paths, cfg, root, found) -> tuple[dict, str]:
    """Ask for the handoff, but only at the right moment.

    That moment is right after a compaction: the context has just been emptied,
    so drafting is the cheapest it will ever be in the session. Doing it before,
    at 70-80% of the window, would be expensive and the drafting itself could
    trigger the very compaction it was trying to pre-empt.

    Three gates before interrupting anyone: `stop_hook_active` false (the
    harness's own loop guard), an armed flag, and the cooldown.
    """
    if entry.get("stop_hook_active"):
        return {}, "silent: already inside a blocked Stop"
    if not storage.has_pending(paths, cfg["cooldown_minutes"]):
        return {}, "silent: nothing pending"

    # Consumed BEFORE asking: if something fails afterwards, at worst one
    # request is lost. The other way round it would ask in a loop, which is far
    # worse.
    storage.consume_pending(paths)

    return ({
        "decision": "block",
        "reason": (
            "baton: this session has just been compacted, so the compaction summary is "
            "still fresh in your context and this is the best moment to bring the "
            "handoff up to date.\n\n"
            "Write the handoff now following the `baton` skill: ask for the context with "
            "`baton.py context`, draft ONLY the body into the draft file, and write it "
            "with `baton.py write --mode <memory|continue>`. Distil the summary, do not "
            "copy it: there is a budget and it is enforced.\n\n"
            "When you are done, resume what you were doing or keep waiting for the user, "
            "whichever applies. baton will not ask again for this compaction."
        ),
    }, "handoff requested after compaction")


HANDLERS = {
    "session-start": _session_start,
    "post-compact": _post_compact,
    "stop": _stop,
}


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    entry = _read_input()
    paths = None
    try:
        handler = HANDLERS.get(event)
        if handler is None:
            # An event we do not know is not our error: stay quiet.
            return 0

        # Never from os.getcwd(): a hook's working directory is not reliable.
        # Never from CLAUDE_SESSION_ID either: it is not guaranteed.
        root = storage.project_root(entry.get("cwd") or os.getcwd())

        # Resolved before the config on purpose, so the log still gets written
        # if `config.load` blows up on a corrupt file.
        paths = storage.Paths(root)
        cfg = config.load(root)
        paths = storage.Paths(root, document_rel=cfg["document"])
        found = projects.discover(root, depth=cfg["discovery"]["depth"],
                                  max_dirs=cfg["discovery"]["max_dirs"],
                                  document_rel=cfg["document"])

        # Before the inject_on filter, not after: a root whose config drops
        # `startup` must still not carry yesterday's active project into today.
        if event == "session-start" and (entry.get("source") or "startup") in ("startup", "clear"):
            projects.clear_active(root)

        if not paths.document.is_file() and not found.projects:
            # The majority case in the world: every project where /baton was
            # never used. It cannot be noise.
            storage.log_event(paths, event=event, result="silent: project not enabled")
            return 0

        payload, result = handler(entry, paths, cfg, root, found)
        _emit(payload)
        storage.log_event(paths, event=event, result=result,
                          source=entry.get("source") or entry.get("trigger") or "")
    except BaseException as exc:  # noqa: BLE001 - degrading is the requirement
        _emit({"systemMessage": (
            f"baton: could not complete '{event}' ({type(exc).__name__}: {exc}). "
            "The session continues normally."
        )})
        if paths is not None:
            storage.log_event(paths, event=event, result="error",
                              error=f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
