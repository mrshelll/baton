#!/usr/bin/env python3
"""baton's CLI. Called by the skill, and by you when you want to look.

Subcommands:
  context   what the model needs to know before drafting (kept short)
  write     validate the draft, measure it, compose it and write it
  show      the current handoff and what injecting it costs
  load      deliver one project's handoff and make it the active one
  doctor    diagnose why baton is not doing what you expect
  panel     everything baton's mod draws, as JSON (always exit 0)

The exit codes are the protocol with the model, not decoration, and that is why
they differ: "does not fit" is fixed by trimming and "is put together wrong" is
fixed by changing its shape. With a single error code the model would try the
wrong remedy.

  0 written   1 over budget   2 invalid draft   3 environment
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import budget, config, document, gitinfo, handoff, output, projects, storage  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

OK, OVER_BUDGET, INVALID, ENVIRONMENT = 0, 1, 2, 3

#: Three attempts and baton takes over. A visible counter breaks more loops than
#: any instruction, and a low cap stops the model getting stuck exactly when you
#: were about to close the session.
MAX_ATTEMPTS = 3


@dataclass
class Ctx:
    """Everything a subcommand needs once the target project is known."""
    root: Path
    target: "projects.Target"
    cfg: config.Config
    paths: storage.Paths
    strings: dict
    found: "projects.Discovery"


def _session_root(args) -> Path:
    """The root `--cwd` (else the current folder) belongs to, found from
    `--root`, the folder the session started in, when it lies beneath it
    (`storage.session_root`)."""
    return storage.session_root(args.cwd or os.getcwd(), args.root)


def _resolve(args, allow_new: bool = False):
    """Root, target, config, paths and strings: the preamble to every subcommand.

    Returns `(ctx, code)`. A non-zero code means the caller returns it right
    away: the candidates have already gone to stderr, and picking one for the
    user is exactly what must not happen.
    """
    root = _session_root(args)
    root_cfg = config.load(root)
    found = projects.discover(root, depth=root_cfg["discovery"]["depth"],
                              max_dirs=root_cfg["discovery"]["max_dirs"],
                              document_rel=root_cfg["document"])
    name = getattr(args, "project", None)

    here = Path(args.cwd or os.getcwd())
    root_enabled = storage.Paths(root, document_rel=root_cfg["document"]).document.is_file()
    ask_where = False

    if name is None:
        # The same rule the unattended hooks follow; here a None becomes a
        # question on stderr instead of silence.
        target, why = projects.writable_target(root, found, here, root_enabled)
        ask_where = why == "ask_where"
        candidates = list(found.projects)
    else:
        target, candidates = projects.resolve(root, found, name, allow_new=allow_new)

    if ask_where:
        strings = output.load_strings(root_cfg["language"])
        rel = Path(here).resolve(strict=False).relative_to(Path(root).resolve(strict=False))
        print(strings["cli"]["which_target"].format(here=rel.as_posix(), root=root),
              file=sys.stderr)
        print(f"  --project {rel.as_posix()}", file=sys.stderr)
        print(f"  --project {projects.ROOT_NAME}", file=sys.stderr)
        return None, ENVIRONMENT

    if target is None:
        strings = output.load_strings(root_cfg["language"])
        key = "unknown_project" if name else "which_project"
        print(strings["cli"][key].format(name=name or ""), file=sys.stderr)
        for project in candidates:
            print(f"  {project.name}  ({project.rel})", file=sys.stderr)
        return None, ENVIRONMENT

    cfg = config.load(target.path, parent=root)
    paths = storage.Paths(target.path, document_rel=cfg["document"])
    return Ctx(root, target, cfg, paths, output.load_strings(cfg["language"]), found), OK


def _gitignore_covers(root: Path) -> bool:
    try:
        text = (root / ".gitignore").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(l.strip().rstrip("/") == ".baton/local" for l in text.split("\n"))


def cmd_context(args) -> int:
    """What the model needs BEFORE drafting. Short on purpose.

    If this command were long it would eat, in context, exactly what baton is
    trying to save.
    """
    # allow_new like `write`: this command is the question that precedes it, so a
    # project `write` could create has to be one `context` can describe. Without
    # it the cold start dies on the first command of the skill, before there is
    # even a draft path to answer with.
    ctx, code = _resolve(args, allow_new=True)
    if code:
        return code
    root, cfg, paths, strings = ctx.target.path, ctx.cfg, ctx.paths, ctx.strings
    snap = gitinfo.snapshot(root)
    limits = cfg["limits"]
    out = [
        f"project: {root}",
        f"document: {paths.document}",
        f"draft: write ONLY the body into {paths.draft}",
        f"budget: {limits['lines']} lines / {limits['characters']} characters (whole document)",
        "valid sections: " + ", ".join(strings["sections"].values()),
        f"required: {strings['sections'][strings['required_section']]}"
        " -- the rest only if they apply (never write 'none')",
        f"language: {cfg['language']}",
        "",
        "git context (baton adds this, do not write it yourself):",
    ]
    out += ["  " + l for l in gitinfo.context_block(snap, strings).split("\n")]

    if paths.document.is_file():
        try:
            current = paths.document.read_text(encoding="utf-8", errors="replace")
            m = budget.measure(current)
            out += ["", f"current handoff: {document.read_mode(current)} mode, {m.lines} lines, "
                        f"written {document.read_fields(current).get('date', '?')}"]
        except OSError:
            pass
    else:
        out += ["", "current handoff: none. This /baton enables baton in this project."]
        if (ctx.target.is_root and not ctx.found.projects
                and getattr(args, "project", None) is None):
            # A root with nothing at all looks exactly like a plain repo on its
            # first /baton, and for a plain repo that is the right answer. But
            # when the session's work was in a subfolder, writing here in
            # silence makes the root a project and the next /baton on another
            # subfolder overwrites it -- the failure 0.4.0 exists to prevent,
            # back in through the door marked "first time". The CLI cannot see
            # the conversation; the model can. So it is told, not asked: the
            # conversation decides whether there is a question, the user
            # decides the answer, and a plain repo never hears about it.
            out.append(strings["cli"]["cold_root"])

    if snap.has_git and not _gitignore_covers(root):
        out += ["", "missing from .gitignore (one line):  .baton/local/"]
    out += [f"config warning: {w}" for w in cfg.warnings]

    print("\n".join(out))
    return OK


def _attempts(paths: storage.Paths, fingerprint: str) -> int:
    """How many times in a row THIS draft has failed on budget."""
    try:
        data = json.loads(paths.attempts.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("fingerprint") != fingerprint:
            return 0
        when = storage.from_utc(data.get("ts"))
        if when is None or (datetime.now(timezone.utc) - when) > timedelta(minutes=30):
            return 0  # an old session does not drag attempts into today's
        return int(data.get("attempts", 0))
    except Exception:
        return 0


def _record_attempt(paths: storage.Paths, fingerprint: str, n: int) -> None:
    try:
        paths.ensure_local()
        paths.attempts.write_text(json.dumps(
            {"fingerprint": fingerprint, "attempts": n, "ts": storage.now_utc()}),
            encoding="utf-8")
    except OSError:
        pass


def _minimal_escape(parsed, strings, cfg, assemble, attempts):
    """Compose a minimal handoff when the draft will not fit after N attempts.

    Keeps the required section, trimmed on WHOLE LINE boundaries, and declares
    it inside the document itself. It is truncation, yes -- but truncation that
    says so, which is the opposite of leaving a half sentence looking whole.
    """
    slug = strings["required_section"]
    canonical, content = parsed.sections[slug]
    marker = strings["write_trim_marker"].format(attempts=attempts)
    fixed = len(assemble(f"## {canonical}\n\n{marker}\n"))
    room_chars = max(cfg["limits"]["characters"] - fixed, 200)
    room_lines = max(cfg["limits"]["lines"] - len(assemble("## x\n").split("\n")) - 2, 3)
    trimmed, _ = budget.trim_to_lines(content, room_chars, room_lines)
    return assemble(f"## {canonical}\n{trimmed.rstrip()}\n\n{marker}\n")


def cmd_write(args) -> int:
    """Validate, measure, compose and write. The model NEVER writes the file."""
    ctx, code = _resolve(args, allow_new=True)
    if code:
        return code
    root, cfg, paths, strings = ctx.target.path, ctx.cfg, ctx.paths, ctx.strings
    if args.mode not in document.MODES:
        print(strings["cli"]["invalid_mode"].format(
            mode=args.mode, valid=" or ".join(document.MODES)), file=sys.stderr)
        return INVALID

    draft_path = Path(args.draft) if args.draft else paths.draft
    try:
        raw = draft_path.read_text(encoding="utf-8")
    except OSError:
        print(strings["cli"]["no_draft"].format(path=draft_path), file=sys.stderr)
        return INVALID

    built = handoff.build(raw, args.mode, root, cfg, strings)
    final, parsed, verdict = built.final, built.parsed, built.verdict
    if not parsed.valid:
        print(strings["cli"]["invalid_draft"], file=sys.stderr)
        for e in parsed.errors:
            print(f"  - {e}", file=sys.stderr)
        return INVALID

    if not verdict.fits:
        fingerprint = document.fingerprint(final, strings["context_section"])
        attempt = _attempts(paths, fingerprint) + 1
        if attempt < MAX_ATTEMPTS:
            _record_attempt(paths, fingerprint, attempt)
            print(budget.report(verdict, parsed.body, attempt, MAX_ATTEMPTS, strings,
                                str(paths.document)), file=sys.stderr)
            return OVER_BUDGET
        assemble = handoff.assembler(args.mode, root, strings)
        final = _minimal_escape(parsed, strings, cfg, assemble, attempt)

    try:
        storage.write_document(paths, final, history_max=cfg["history_max"])
    except (storage.BusyError, storage.StorageError) as exc:
        print(f"baton: {exc}", file=sys.stderr)
        return ENVIRONMENT

    m = budget.measure(final)
    print(strings["cli"]["written"].format(path=paths.document))
    print(strings["cli"]["stats"].format(
        mode=args.mode, lines=m.lines, max_lines=cfg["limits"]["lines"],
        chars=m.characters, max_chars=cfg["limits"]["characters"], tokens=m.tokens))
    return OK


def cmd_show(args) -> int:
    """The current handoff and what injecting it would cost."""
    ctx, code = _resolve(args)
    if code:
        return code
    root, cfg, paths, strings = ctx.target.path, ctx.cfg, ctx.paths, ctx.strings
    if not paths.document.is_file():
        print(f"baton: this project has no handoff yet ({paths.document}).\n"
              "Run /baton to create one.")
        return OK
    text = paths.document.read_text(encoding="utf-8", errors="replace")
    m = budget.measure(text)
    fields = document.read_fields(text)
    print(f"{paths.document}")
    print(f"  {document.read_mode(text)} mode - {m.lines}/{cfg['limits']['lines']} lines, "
          f"{m.characters}/{cfg['limits']['characters']} characters (~{m.tokens} tokens)")
    print(f"  written {fields.get('date', '?')} on `{fields.get('branch', '?')}` "
          f"@ {fields.get('commit', '?')}")
    notice = gitinfo.freshness(root, fields.get("date"), fields.get("branch", ""),
                               fields.get("commit", ""), strings).notice()
    print(f"  {notice}" if notice else "  freshness: up to date")
    if args.full:
        print("\n" + text)
    return OK


def cmd_load(args) -> int:
    """Deliver one project's handoff and make it this session's active one.

    It prints exactly what the hook would have injected: same wrapper, same
    freshness, same repeat notice, same trim. A handoff has to carry identical
    guarantees whether it arrived through the hook or through this command --
    otherwise the mode instruction becomes something the model can be talked out
    of by taking the other route.
    """
    ctx, code = _resolve(args)
    if code:
        return code
    if not ctx.paths.document.is_file():
        print(ctx.strings["cli"]["no_handoff_yet"].format(
            name=ctx.target.label, path=ctx.paths.document), file=sys.stderr)
        return ENVIRONMENT

    text = ctx.paths.document.read_text(encoding="utf-8", errors="replace")
    fields = document.read_fields(text)
    notice = gitinfo.freshness(ctx.target.path, fields.get("date"), fields.get("branch", ""),
                               fields.get("commit", ""), ctx.strings).notice()
    repeat = storage.record_delivery(
        ctx.paths, document.fingerprint(text, ctx.strings["context_section"]))

    print(output.wrap(
        body=document.extract_body(text, ctx.strings["context_section"]) or text,
        mode=document.read_mode(text), written=fields.get("date", "?"),
        source=ctx.target.rel, freshness_notice=notice, repeat=repeat,
        strings=ctx.strings))

    if ctx.target.is_root:
        projects.clear_active(ctx.root)
    else:
        projects.set_active(ctx.root, ctx.target.project,
                            session=os.environ.get("CLAUDE_SESSION_ID", ""))
        print(ctx.strings["cli"]["loaded"].format(name=ctx.target.label), file=sys.stderr)
    return OK


def _last_log_entry(paths: storage.Paths):
    """Returns (stamp, hours since then) or (None, None)."""
    try:
        lines = [l for l in paths.log.read_text(encoding="utf-8").split("\n") if l.strip()]
        if not lines:
            return None, None
        ts = json.loads(lines[-1])["ts"]
        when = storage.from_utc(ts)
        if when is None:
            return None, None
        return ts, (datetime.now(timezone.utc) - when) / timedelta(hours=1)
    except Exception:
        return None, None


def _plugin_enabled():
    """True/False from ~/.claude/settings.json; None when it cannot be known."""
    try:
        settings = json.loads(
            (Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8"))
        enabled = settings.get("enabledPlugins") or {}
        return any(k.split("@")[0] == "baton" and v for k, v in enabled.items())
    except Exception:
        return None


def cmd_doctor(args) -> int:
    """A hook that does not fire gives no error: it gives nothing.

    This command exists to turn that silence into a diagnosis. It orders the
    causes by real likelihood, starting with the one that is almost always
    right: installing the plugin without restarting Claude Code.
    """
    ctx, code = _resolve(args)
    if code:
        # Several projects and none chosen: diagnose the ROOT anyway. A doctor
        # that refuses to speak is useless precisely when something is wrong.
        args.project = projects.ROOT_NAME
        ctx, code = _resolve(args)
        if code:
            return code
    root, cfg, paths = ctx.target.path, ctx.cfg, ctx.paths
    out = [f"baton doctor -- project: {root}", ""]

    hooks_json = PLUGIN_ROOT / "hooks" / "hooks.json"
    try:
        events = ", ".join(json.loads(hooks_json.read_text(encoding="utf-8"))["hooks"])
        out.append(f"  [ok] hooks.json valid       ({events})")
    except Exception as exc:
        out.append(f"  [!!] hooks.json UNREADABLE  {type(exc).__name__}: {exc}")

    out.append(f"  [ok] python3                {sys.version.split()[0]}")
    if shutil.which("git"):
        try:
            v = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=3)
            out.append(f"  [ok] git                    {v.stdout.strip()}")
        except Exception:
            out.append("  [--] git                    present but not responding")
    else:
        out.append("  [--] git                    missing (baton still works, without git data)")

    enabled = _plugin_enabled()
    if enabled is True:
        out.append("  [ok] plugin enabled         in ~/.claude/settings.json")
    elif enabled is False:
        out.append("  [!!] plugin NOT enabled     check it with /plugin")
    else:
        out.append("  [--] plugin                 could not read ~/.claude/settings.json")

    out.append(f"  [ok] language               {cfg['language']} "
               f"(available: {', '.join(output.available_languages())})")

    # "my project does not show up" must never be a mystery: how deep it looked,
    # what it found and whether it gave up are all one command away.
    out.append(f"  [ok] discovery              depth {ctx.cfg['discovery']['depth']}, "
               f"{len(ctx.found.projects)} project(s) found")
    for project in ctx.found.projects:
        card = projects.describe(project, ctx.cfg["document"])
        out.append(f"         - {project.rel}  ({card.mode}, {card.date or 'no date'})")
    if ctx.found.truncated:
        out.append("  [!!] the scan hit its limit; raise discovery.max_dirs to see the rest")
    active = projects.read_active(ctx.root, ctx.found)
    out.append(f"  [ok] active project         {active.rel}" if active
               else "  [--] active project         none loaded in this session")
    out.append("")

    if not paths.document.is_file():
        out += ["  This project does not use baton yet.",
                "  Run /baton once to enable it here; until then the hooks stay quiet",
                "  on purpose, and that is NOT a failure."]
        print("\n".join(out))
        return OK

    out.append(f"  Document: {paths.document}")
    ts, hours = _last_log_entry(paths)
    if ts is None:
        out += ["", "  The hook has left NO trace at all. Causes by likelihood:",
                "    1. You installed the plugin without restarting Claude Code",
                "       (hooks are loaded at startup).",
                "    2. The plugin is disabled -- check it with /plugin.",
                f"    3. python3 is not on the harness PATH (here it is: {sys.version.split()[0]})."]
    elif hours is not None and hours > 24:
        out += ["", f"  The hook has not fired since {ts} ({hours:.0f} h). Same causes as above."]
    else:
        out.append(f"  Last hook run: {ts}")

    out.append(_window_line(ctx))

    for w in cfg.warnings:
        out.append(f"  config warning: {w}")
    print("\n".join(out))
    return OK


def _window_line(ctx) -> str:
    """The last reading of the context window, so "why did it not warn me at
    80%?" is one command away. The state lives at the session root."""
    cw = ctx.cfg["context_window"]
    if not cw["enabled"]:
        return "  [--] context window: automatic handoff switched off"
    last = storage.read_json(storage.Paths(ctx.root).window).get("last")
    last = last if isinstance(last, dict) else {}
    numbers = [last.get(k) for k in ("percent", "tokens", "budget")]
    if not all(isinstance(n, int) and not isinstance(n, bool) for n in numbers):
        return "  [--] context window: not measured yet (it is read when a turn ends)"
    percent, tokens, budget = numbers
    return (f"  [ok] context window: {percent}% at the last turn -- {tokens:,} of {budget:,} "
            f"tokens ({last.get('model') or '?'}, size from {last.get('source') or '?'}); "
            f"asks at {', '.join(f'{t}%' for t in cw['thresholds'])}")


#: The shape `panel --json` promises the mod. Bump only on an incompatible change.
PANEL_VERSION = 1


def _panel_target(args, root: Path, root_cfg, found):
    """The project the panel shows, or None. Never asks: the mod calls this
    every turn, so the question `_resolve` would print becomes `project: null`
    and the list of projects to open.

    Where `write` would have to ask, a root with a handoff of its own still
    shows it: the panel is the receipt, and the SessionStart injects and
    receipts that handoff whatever the root holds below it."""
    if args.project is not None:
        target, _ = projects.resolve(root, found, args.project)
        return target
    here = Path(args.cwd or os.getcwd())
    root_enabled = storage.Paths(root, document_rel=root_cfg["document"]).document.is_file()
    target, _ = projects.writable_target(root, found, here, root_enabled)
    if target is None and root_enabled:
        return projects.Target(root)
    return target


def _panel_threshold(root: Path, session: str):
    """`({percent, tier}, announced)` once THIS session crossed a threshold,
    else `(None, None)`. `announced` is when the latest tier was announced, None
    in a record written before that was kept. The window state lives at the
    session's root, not at the project shown."""
    if not session:
        return None, None
    state = storage.read_window(storage.Paths(root), session)
    if not state["fired"]:
        return None, None
    percent = state["last"].get("percent")
    if not isinstance(percent, int) or isinstance(percent, bool):
        percent = None
    return {"percent": percent, "tier": max(state["fired"])}, storage.last_announced(state)


def _parse_date(text):
    """A handoff's `date`, as an aware datetime; None for anything else."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _panel_handoff(target, paths: storage.Paths, strings: dict, session: str):
    """`(handoff, ready, written)` from the document on disk. `written` is when
    it was written -- this session's compaction note when it wrote it, the
    document's date otherwise -- or None when neither can be read. Raises
    OSError when it exists and cannot be read; the caller turns that into the
    error state."""
    text = paths.document.read_text(encoding="utf-8", errors="replace")
    fields = document.read_fields(text)
    fingerprint = document.fingerprint(text, strings["context_section"])
    # Who wrote it is the note's business whatever session it belongs to; being
    # ready to start over is only this session's.
    by_compaction = any(note.get("written") is True and note.get("fingerprint") == fingerprint
                        for note in storage.compact_notes(paths).values())
    mine = storage.read_compact_request(paths, session) or {}
    ready = mine.get("written") is True and mine.get("fingerprint") == fingerprint
    notice = gitinfo.freshness(target.path, fields.get("date"), fields.get("branch", ""),
                               fields.get("commit", ""), strings).notice()
    return {
        "mode": document.read_mode(text),
        "date": output.sanitize(fields["date"]) if "date" in fields else None,
        "age": output.age(fields.get("date", ""), strings),
        "lines": budget.measure(text).lines,
        "written_by": "compaction" if by_compaction else "manual",
        "stale": bool(notice),
        "sections": output.panel_sections(text, strings),
    }, ready, ((storage.from_utc(mine.get("written_at")) if ready else None)
               or _parse_date(fields.get("date")))


def _panel(args) -> dict:
    """The JSON `panel --json` prints, version `PANEL_VERSION`."""
    root = _session_root(args)
    root_cfg = config.load(root)
    found = projects.discover(root, depth=root_cfg["discovery"]["depth"],
                              max_dirs=root_cfg["discovery"]["max_dirs"],
                              document_rel=root_cfg["document"])
    target = _panel_target(args, root, root_cfg, found)
    cfg = config.load(target.path, parent=root) if target else root_cfg
    strings = output.load_strings(cfg["language"])
    # The language the strings are in: an unknown one fell back to English.
    language = (cfg["language"] if cfg["language"] in output.available_languages()
                else output.DEFAULT_LANGUAGE)
    session = args.session or ""

    others = [project for project in found.projects
              if target is None or target.project != project]
    cards = [projects.describe(project, root_cfg["document"]) for project in others]
    out = {
        "version": PANEL_VERSION, "language": language, "state": "none",
        "project": None, "handoff": None, "threshold": None,
        # Directory names travel inside cloned repos: cleaned and capped like
        # the index's, before the mod puts them on a terminal.
        # `rel` stays raw: it is what `--project` matches first, so it is the one
        # name that opens the right project when two folders share a name. The
        # mod draws `where`, never `rel`.
        "others": [{"name": output.sanitize(card.name)[:output.MAX_NAME], "rel": card.rel,
                    "where": output.sanitize(card.rel), "mode": card.mode,
                    "age": output.age(card.date, strings)}
                   for card in cards],
        "strings": {k: v for k, v in strings["panel"].items() if not k.startswith("_")},
        "error": None,
    }
    if target is None:
        return out

    paths = storage.Paths(target.path, document_rel=cfg["document"])
    out["project"] = {"name": output.sanitize(target.path.name)[:output.MAX_NAME],
                      "path": str(target.path)}
    out["threshold"], announced = _panel_threshold(root, session)
    ready, written = False, None
    if paths.document.is_file():
        try:
            out["handoff"], ready, written = _panel_handoff(target, paths, strings, session)
        except OSError:
            out["error"] = output.sanitize(
                strings["panel"]["error_read"].format(path=paths.document))
    # Between a threshold and a handoff the most recent one wins: a handoff
    # written after the warning answers it, a threshold crossed after the
    # handoff -- the compaction's included -- is news. A tie goes to the
    # handoff. Without both times (a record from before they were kept, a
    # date nobody can read) the old order stands: ready, then threshold.
    if out["threshold"] and announced and written:
        threshold_first = announced > written
    else:
        threshold_first = bool(out["threshold"]) and not ready
    if threshold_first:
        out["state"] = "threshold"
    elif ready:
        out["state"] = "ready"
    elif out["error"]:
        out["state"] = "error"
    elif out["handoff"]:
        out["state"] = "normal"
    return out


def cmd_panel(args) -> int:
    """Everything baton's mod draws, as JSON: the mod draws and launches, the
    handoff is read and understood here, once.

    Exit 0 whenever JSON can be written: the mod calls this every turn, and a
    situation it can describe -- no project, no handoff, an unreadable one --
    is a state to draw, not a failure."""
    try:
        out = _panel(args)
    except Exception as exc:  # noqa: BLE001 - the panel draws the failure instead
        language, panel = output.DEFAULT_LANGUAGE, {}
        try:
            language = config.load(_session_root(args))["language"]
            panel = {k: v for k, v in output.load_strings(language)["panel"].items()
                     if not k.startswith("_")}
        except Exception:  # noqa: BLE001 - an English line beats no JSON at all
            pass
        detail = f"{type(exc).__name__}: {exc}"
        out = {"version": PANEL_VERSION, "language": language,
               "state": "error", "project": None, "handoff": None, "threshold": None,
               "others": [], "strings": panel,
               "error": output.sanitize(
                   panel.get("error_unexpected", "baton: {detail}").format(detail=detail))}
    # ASCII escapes: a stdout that cannot encode `✓` (a cp1252 pipe,
    # PYTHONIOENCODING=ascii) must still get the JSON, and JSON decodes them back.
    try:
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 - nobody left to read it; still no traceback
        pass
    return OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="baton", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def with_cwd(name, help_text, func, project_flag=True):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--cwd", default=None, help="project directory (defaults to the current one)")
        sp.add_argument("--root", default=None,
                        help="the folder the session started in, when --cwd lies beneath it "
                             "(defaults to CLAUDE_PROJECT_DIR, then BATON_PROJECT_DIR)")
        if project_flag:
            sp.add_argument("--project", default=None,
                            help="which project in this root (name, relative path, or `.`)")
        sp.set_defaults(func=func)
        return sp

    with_cwd("context", "what the model needs before drafting", cmd_context)
    write = with_cwd("write", "validate the draft and write the handoff", cmd_write)
    # No `choices`: cmd_write validates the mode so it can explain the
    # difference between the two instead of emitting an argparse error.
    write.add_argument("--mode", required=True,
                       help="continue (a task is half done) or memory (context only)")
    write.add_argument("--draft", default=None,
                       help="draft path (defaults to .baton/local/draft.md)")
    show = with_cwd("show", "the current handoff and what injecting it costs", cmd_show)
    show.add_argument("--full", action="store_true", help="also print the whole document")
    load = with_cwd("load", "deliver a project's handoff and make it active", cmd_load,
                    project_flag=False)
    load.add_argument("project", help="project name, relative path, or `.` for the root")
    with_cwd("doctor", "diagnose the installation and the project state", cmd_doctor)
    panel = with_cwd("panel", "everything baton's mod draws, as JSON", cmd_panel)
    panel.add_argument("--json", action="store_true", required=True,
                       help="the only output there is; required so a later one can differ")
    panel.add_argument("--session", default="",
                       help="the session asking: what is ready or crossed is per session")

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
