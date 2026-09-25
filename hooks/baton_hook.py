#!/usr/bin/env python3
"""Single dispatcher for baton's hooks.

Inviolable contract, and the reason this file exists instead of three: **this
process ALWAYS exits 0**. A corrupt handoff, a stdin that is not JSON or a full
disk cannot stop a Claude Code session from starting. All the logic sits inside
an `except BaseException` that degrades to a readable message.

The event arrives as argv[1] (`session-start`, `post-compact`, `stop`,
`tool-batch`) because hooks.json uses the `command: python3` + `args: [...]`
form, which never goes through a shell and is therefore immune to paths with
spaces.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config, document, gitinfo, output, projects, storage, window  # noqa: E402


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
    cards = []
    if found.projects:
        cards = [projects.describe(p, cfg["document"]) for p in found.projects]
        index = output.index_block(root, cards, strings, truncated=found.truncated)

    if not paths.document.is_file():
        # Only the index: this root holds projects but has no handoff of its own.
        payload = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                          "additionalContext": index}}
        if cfg["receipt"]:
            payload["systemMessage"] = output.receipt(
                strings=strings, cards=cards, max_lines=cfg["receipt_lines"])
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
        # visible one: if this line is missing, the hook did not fire. It also
        # carries what the session left behind, because this is the ONLY thing
        # baton shows the person: the handoff itself goes to the model and never
        # to the screen, so without this the author of the document cannot see
        # what they left without spending a turn asking for it back.
        payload["systemMessage"] = output.receipt(
            document_text=text, mode=mode, strings=strings, cards=cards,
            stale=bool(notice), max_lines=cfg["receipt_lines"],
            lines=len(context.splitlines()))
    return payload, f"injected {mode} mode"


def _hook_target(root, paths: storage.Paths, cfg, found):
    """Where an unattended hook writes: the active project, else the root.

    Returns `(paths, label)` with paths None when neither exists. Both hooks have
    to agree on this, because `post-compact` arms the flag that `stop` reads back:
    pointing them at different directories would arm a flag nobody reads.
    """
    active = projects.read_active(root, found)
    if active is not None:
        return storage.Paths(active.path, document_rel=cfg["document"]), active.name
    if paths.document.is_file():
        return paths, ""
    return None, ""


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
    target, _ = _hook_target(root, paths, cfg, found)
    if target is None:
        return {}, "silent: no target for the summary"
    storage.save_summary(target, entry.get("compact_summary") or "",
                         trigger=entry.get("trigger") or "auto")
    storage.arm_pending(target, entry.get("session_id") or "")

    # A compaction moves the baseline -- 90% becomes 20% -- so the thresholds
    # already met describe an occupation that no longer exists.
    state = storage.read_window(paths, entry.get("session_id") or "")
    if state["fired"] or state["warned"]:
        storage.save_window(paths, dict(state, fired=[], warned=False))
    return {}, "summary saved, handoff pending"


def _k(tokens: int) -> str:
    """Thousands, the way the statusline paints them: 231k, 1000k."""
    return f"{round(tokens / 1000)}k"


def _describe(reading) -> str:
    if not reading.known:
        return "context unknown"
    return f"context {reading.percent}% of {_k(reading.budget)} ({reading.source})"


def _measure(entry: dict, cfg, root, state: dict) -> tuple[window.Reading, dict]:
    """Read how full the window is and learn from it. Returns (reading, state).

    The state lives at the session's ROOT, not at the handoff's target: it
    describes this session and its window, and a /baton load mid-session must
    not make it forget what it already asked."""
    reading, marks, _ = window.assess(
        entry.get("transcript_path"), seen=state["marks"], env=os.environ,
        budget_tokens=cfg["context_window"]["budget_tokens"],
        settings_window=window.settings_window(root))
    state = dict(state, marks=marks)
    if reading.known:
        state["last"] = {"percent": reading.percent, "tokens": reading.tokens,
                         "budget": reading.budget, "model": reading.model,
                         "source": reading.source, "at": storage.now_utc()}
    return reading, state


def _window_request(target: storage.Paths, label: str, cfg, reading,
                    state: dict) -> tuple[dict, str]:
    """Ask for the handoff if the window crossed a threshold not yet asked.

    A threshold is marked as asked -- in `state`, which the caller saves -- ONLY
    when the request goes out. Held back by the cooldown, it is tried again at
    the next turn: postponed, not lost."""
    if not reading.known:
        return {}, "silent: context unknown"
    cw = cfg["context_window"]
    measured = _describe(reading)
    if not cw["enabled"]:
        return {}, f"silent: {measured}, trigger off"
    tier = window.tier_reached(reading, cw["thresholds"], state["fired"], cw["min_tokens"])
    if tier is None:
        return {}, f"silent: {measured}"
    if not storage.cooldown_clear(target, cfg["cooldown_minutes"]):
        return {}, f"silent: {measured}, {tier}% waits for the cooldown"

    again = bool(state["fired"])
    state["fired"] = sorted(set(state["fired"]) | {t for t in cw["thresholds"] if t <= tier})
    storage.note_request(target)

    strings = output.load_strings(cfg["language"])["auto_handoff"]
    numbers = {"percent": reading.percent, "used": _k(reading.tokens),
               "budget": _k(reading.budget)}
    action = strings["ask" if cw["confirm"] else "write"].format(**numbers)
    reason = strings["reason"].format(
        **numbers, action=action,
        project=strings["project"].format(label=label) if label else "",
        again=strings["again"] if again else "")
    notice = strings["notice_ask" if cw["confirm"] else "notice_write"].format(**numbers)
    return ({"decision": "block", "reason": reason, "systemMessage": notice},
            f"handoff requested at {reading.percent}% (threshold {tier})"
            f"{f' for {label}' if label else ''}")


def _stop(entry: dict, paths: storage.Paths, cfg, root, found) -> tuple[dict, str]:
    """Ask for the handoff at one of two moments, and never with work in flight.

    A Stop fires when the model has finished its turn: no tool is running and no
    subagent is alive, so it is the one moment a request cannot cut anything in
    half. There are two reasons to use it:

    1. Right after a compaction. The summary is fresh in the context and
       drafting is the cheapest it will ever be.
    2. When the session crosses a threshold of its context window -- BEFORE the
       harness compacts and decides by itself what survives. The thresholds stay
       at or below 95% on purpose: drafting costs a few thousand tokens, and at
       the very edge that alone could trigger the compaction being pre-empted.

    The compaction wins a tie: its summary is the better material, and the
    threshold is not consumed, so it stays available. Both reasons share one
    cooldown, because what it protects is the person.
    """
    if entry.get("stop_hook_active"):
        return {}, "silent: already inside a blocked Stop"
    if entry.get("agent_id"):
        return {}, "silent: subagent"

    # A hook cannot ask which project this was about, so with no resolvable
    # target it says nothing. Interrupting with a question it cannot answer on
    # its own is worse than silence.
    target, label = _hook_target(root, paths, cfg, found)
    if target is None:
        return {}, "silent: no resolvable target"

    # Measured on every turn, whatever happens next: that is what calibrates the
    # window and what puts the percentage in the log.
    reading, state = _measure(entry, cfg, root,
                              storage.read_window(paths, entry.get("session_id") or ""))

    if storage.has_pending(target, cfg["cooldown_minutes"]):
        storage.save_window(paths, state)
        # Consumed BEFORE asking: if something fails afterwards, at worst one
        # request is lost. The other way round it would ask in a loop, which is
        # far worse.
        storage.consume_pending(target)
        return ({
            "decision": "block",
            "reason": (
                "baton: this session has just been compacted, so the compaction summary is "
                "still fresh in your context and this is the best moment to bring the "
                "handoff up to date.\n\n"
                + (f"This session's active project is `{label}`; the handoff goes there, and "
                   "the commands below already target it.\n\n" if label else "")
                + "Write the handoff now following the `baton` skill: ask for the context with "
                "`baton.py context`, draft ONLY the body into the draft file, and write it "
                "with `baton.py write --mode <memory|continue>`. Distil the summary, do not "
                "copy it: there is a budget and it is enforced.\n\n"
                "When you are done, resume what you were doing or keep waiting for the user, "
                "whichever applies. baton will not ask again for this compaction."
            ),
        }, f"handoff requested after compaction{f' for {label}' if label else ''}; "
           f"{_describe(reading)}")

    payload, result = _window_request(target, label, cfg, reading, state)
    storage.save_window(paths, state)
    return payload, result


def _tool_batch(entry: dict) -> dict:
    """Tell the model, once per session, to wrap up instead of starting anew.

    It runs after EVERY batch of tools, so it has its own lean path: no project
    discovery and no log line unless it speaks -- one line per batch would push
    everything worth reading out of a 200-line log. It never blocks and never
    asks for the handoff: that is the Stop's job, at the end of the turn. What
    it adds is the case a Stop cannot see: one long turn that crosses the mark
    without ending.
    """
    if entry.get("agent_id"):
        return {}
    root = storage.project_root(entry.get("cwd") or os.getcwd())
    cfg = config.load(root)
    cw = cfg["context_window"]
    if not (cw["enabled"] and cw["watch_at"]):
        return {}
    paths = storage.Paths(root, document_rel=cfg["document"])
    if not (paths.document.is_file() or paths.window.is_file()):
        return {}
    state = storage.read_window(paths, entry.get("session_id") or "")
    if state["warned"] or state["fired"]:
        return {}
    reading, state = _measure(entry, cfg, root, state)
    if not reading.at_least(cw["watch_at"]) or reading.tokens < cw["min_tokens"]:
        return {}
    state["warned"] = True
    storage.save_window(paths, state)
    storage.log_event(paths, event="tool-batch",
                      result=f"early warning at {reading.percent}%")
    text = output.load_strings(cfg["language"])["auto_handoff"]["watch"]
    return {"hookSpecificOutput": {"hookEventName": "PostToolBatch",
                                   "additionalContext": text.format(percent=reading.percent)}}


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
        if event == "tool-batch":
            _emit(_tool_batch(entry))
            return 0

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
