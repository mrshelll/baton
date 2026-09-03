#!/usr/bin/env python3
"""baton's CLI. Called by the skill, and by you when you want to look.

Subcommands:
  context   what the model needs to know before drafting (kept short)
  write     validate the draft, measure it, compose it and write it
  show      the current handoff and what injecting it costs
  doctor    diagnose why baton is not doing what you expect

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import budget, config, document, gitinfo, output, storage  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

OK, OVER_BUDGET, INVALID, ENVIRONMENT = 0, 1, 2, 3

#: Three attempts and baton takes over. A visible counter breaks more loops than
#: any instruction, and a low cap stops the model getting stuck exactly when you
#: were about to close the session.
MAX_ATTEMPTS = 3


def _project(args):
    """Root, config, paths and strings: the preamble to almost every subcommand."""
    root = storage.project_root(args.cwd or os.getcwd())
    cfg = config.load(root)
    paths = storage.Paths(root, document_rel=cfg["document"])
    return root, cfg, paths, output.load_strings(cfg["language"])


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
    root, cfg, paths, strings = _project(args)
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
    root, cfg, paths, strings = _project(args)
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

    parsed = document.validate_draft(raw, mode=args.mode, strings=strings)
    if not parsed.valid:
        print(strings["cli"]["invalid_draft"], file=sys.stderr)
        for e in parsed.errors:
            print(f"  - {e}", file=sys.stderr)
        return INVALID

    snap = gitinfo.snapshot(root)

    def assemble(body):
        return document.compose(
            body=body, mode=args.mode, date=gitinfo.now_iso(),
            branch=snap.branch, commit=snap.commit,
            context=gitinfo.context_block(snap, strings), strings=strings)

    final = assemble(parsed.body)
    verdict = budget.evaluate(final, cfg["limits"])

    if not verdict.fits:
        fingerprint = document.fingerprint(final, strings["context_section"])
        attempt = _attempts(paths, fingerprint) + 1
        if attempt < MAX_ATTEMPTS:
            _record_attempt(paths, fingerprint, attempt)
            print(budget.report(verdict, parsed.body, attempt, MAX_ATTEMPTS, strings,
                                str(paths.document)), file=sys.stderr)
            return OVER_BUDGET
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
    root, cfg, paths, strings = _project(args)
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
    root, cfg, paths, _ = _project(args)
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

    for w in cfg.warnings:
        out.append(f"  config warning: {w}")
    print("\n".join(out))
    return OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="baton", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def with_cwd(name, help_text, func):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--cwd", default=None, help="project directory (defaults to the current one)")
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
    with_cwd("doctor", "diagnose the installation and the project state", cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
