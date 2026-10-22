"""The contract no path may break: the hook ALWAYS exits 0.

A broken handoff, a corrupt stdin or a full disk cannot stop a Claude Code
session from starting. These tests invoke the hook as a subprocess with JSON on
stdin, exactly like the harness.
"""
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests.helpers import REPO_ROOT, BaseCase, clean_env

EVENTS = ("session-start", "post-compact", "stop", "tool-batch", "pre-compact")


class TestAlwaysExitsZero(BaseCase):
    def test_every_event_is_silent_in_a_project_not_enabled(self):
        for event in EVENTS:
            with self.subTest(event=event):
                rc, out, err = self.run_hook(event, self.payload(event))
                self.assertEqual(rc, 0, err)
                self.assertIsNone(out, "a project that is not enabled must stay silent")

    def test_stdin_that_is_not_json(self):
        for event in EVENTS:
            with self.subTest(event=event):
                rc, _, err = self.run_hook(event, None, raw_input="{not json")
                self.assertEqual(rc, 0, err)

    def test_empty_stdin(self):
        for event in EVENTS:
            with self.subTest(event=event):
                rc, _, err = self.run_hook(event, None, raw_input="")
                self.assertEqual(rc, 0, err)

    def test_json_that_is_not_an_object(self):
        rc, _, err = self.run_hook("session-start", None, raw_input="[1, 2, 3]")
        self.assertEqual(rc, 0, err)

    def test_missing_cwd_directory(self):
        rc, _, err = self.run_hook("session-start", self.payload(
            "SessionStart", cwd=str(self.project / "no" / "such")))
        self.assertEqual(rc, 0, err)

    def test_cwd_absent_from_the_payload(self):
        rc, _, err = self.run_hook("session-start", {"session_id": "x"})
        self.assertEqual(rc, 0, err)

    def test_unknown_event_does_not_break(self):
        rc, _, err = self.run_hook("made-up-event", self.payload("X"))
        self.assertEqual(rc, 0, err)

    def test_no_event_argument_at_all(self):
        p = subprocess.run(
            [sys.executable, str(REPO_ROOT / "hooks" / "baton_hook.py")],
            input="{}", capture_output=True, text=True, env=clean_env(), timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)


class TestPreCompactSpeaksPlainText(BaseCase):
    """`pre-compact` stdout is handed verbatim to the summarizer and shown raw to
    the person, so neither JSON nor an error message may ever reach it."""

    def test_stdin_that_is_not_json_prints_nothing(self):
        rc, out, err = self.run_hook_text("pre-compact", None, raw_input="{not json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "")

    def test_an_exception_prints_nothing_and_logs_the_error(self):
        doc = self.project / ".baton" / "HANDOFF.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("---\nbaton: 1\nmode: memory\n---\n## State\nx\n", encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "baton_hook_under_test", REPO_ROOT / "hooks" / "baton_hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)

        def boom(*_):
            raise RuntimeError("disk on fire")

        stdin = io.StringIO(json.dumps(self.payload("PreCompact", trigger="auto")))
        captured = io.StringIO()
        with mock.patch.dict(hook.HANDLERS, {"pre-compact": boom}), \
                mock.patch.object(sys, "argv", ["baton_hook.py", "pre-compact"]), \
                mock.patch.object(sys, "stdin", stdin), redirect_stdout(captured):
            rc = hook.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue(), "")
        last = (self.project / ".baton" / "local" / "log.jsonl").read_text(
            encoding="utf-8").strip().splitlines()[-1]
        self.assertEqual(json.loads(last)["result"], "error")
        self.assertIn("disk on fire", json.loads(last)["error"])


class TestPostCompactFailsInOneLine(BaseCase):
    """Claude Code shows `post-compact` stdout raw, never parsed as JSON: an
    unexpected error there must read as one line of text, not as a JSON blob."""

    def setUp(self):
        super().setUp()
        doc = self.project / ".baton" / "HANDOFF.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("---\nbaton: 1\nmode: memory\n---\n## State\nx\n", encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "baton_hook_under_test", REPO_ROOT / "hooks" / "baton_hook.py")
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)
        # The person's own ~/.claude/baton.json must not decide the language.
        home = mock.patch.dict("os.environ", {"HOME": self._tmp})
        home.start()
        self.addCleanup(home.stop)

    def run_main(self, event, *patches):
        def boom(*_):
            raise RuntimeError("disk on fire\nsecond line")

        stdin = io.StringIO(json.dumps(self.payload("PostCompact", trigger="auto")))
        captured = io.StringIO()
        with mock.patch.dict(self.hook.HANDLERS, {event: boom}), \
                mock.patch.object(sys, "argv", ["baton_hook.py", event]), \
                mock.patch.object(sys, "stdin", stdin), redirect_stdout(captured):
            for p in patches:
                p.start()
            try:
                rc = self.hook.main()
            finally:
                for p in patches:
                    p.stop()
        return rc, captured.getvalue()

    def assert_one_plain_line(self, out):
        self.assertTrue(out.strip(), "the person must be told something failed")
        with self.assertRaises(json.JSONDecodeError, msg=f"looks like JSON: {out!r}"):
            json.loads(out)
        self.assertEqual(len(out.rstrip("\n").splitlines()), 1, out)
        self.assertNotIn("{", out)

    def test_an_exception_prints_one_plain_line_and_exits_zero(self):
        rc, out = self.run_main("post-compact")
        self.assertEqual(rc, 0)
        self.assert_one_plain_line(out)
        self.assertEqual(out.rstrip("\n"), self.hook.output.load_strings("en")[
            "auto_handoff"]["failed"].format(error="RuntimeError"))
        last = (self.project / ".baton" / "local" / "log.jsonl").read_text(
            encoding="utf-8").strip().splitlines()[-1]
        self.assertEqual(json.loads(last)["result"], "error")
        self.assertIn("disk on fire", json.loads(last)["error"])

    def test_the_line_speaks_the_configured_language(self):
        cfg = self.project / ".claude" / "baton.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"language": "es"}), encoding="utf-8")
        rc, out = self.run_main("post-compact")
        self.assertEqual(rc, 0)
        self.assert_one_plain_line(out)
        self.assertEqual(out.rstrip("\n"), self.hook.output.load_strings("es")[
            "auto_handoff"]["failed"].format(error="RuntimeError"))

    def test_when_the_config_itself_blows_up_the_line_is_english(self):
        def broken(*_, **__):
            raise ValueError("corrupt config")

        rc, out = self.run_main(
            "post-compact", mock.patch.object(self.hook.config, "load", broken))
        self.assertEqual(rc, 0)
        self.assert_one_plain_line(out)
        self.assertEqual(out.rstrip("\n"), self.hook.output.load_strings("en")[
            "auto_handoff"]["failed"].format(error="ValueError"))

    def test_when_no_template_loads_there_is_still_one_english_line(self):
        def broken(*_, **__):
            raise OSError("templates gone")

        rc, out = self.run_main(
            "post-compact", mock.patch.object(self.hook.output, "load_strings", broken))
        self.assertEqual(rc, 0)
        self.assert_one_plain_line(out)
        self.assertIn("baton", out)
        self.assertIn("RuntimeError", out)

    def test_other_events_keep_their_json_message(self):
        rc, out = self.run_main("stop")
        self.assertEqual(rc, 0)
        self.assertIn("could not complete 'stop'", json.loads(out)["systemMessage"])


class TestHostileTranscripts(BaseCase):
    """In an ENABLED project, which is where the transcript actually gets read."""

    def test_whatever_the_transcript_is_the_exit_is_zero(self):
        doc = self.project / ".baton" / "HANDOFF.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("---\nbaton: 1\nmode: memory\n---\n## State\nx\n", encoding="utf-8")
        binary = self.project / "binary.jsonl"
        binary.write_bytes(bytes(range(256)) * 64)
        for transcript in (str(binary), str(self.project), str(self.project / "missing"),
                           "", 12345, None, ["a"]):
            for event in ("stop", "tool-batch"):
                with self.subTest(event=event, transcript=transcript):
                    rc, out, err = self.run_hook(event, self.payload(
                        event, transcript_path=transcript))
                    self.assertEqual(rc, 0, err)
                    self.assertIsNone(out)


class TestHookLog(BaseCase):
    def test_every_run_leaves_a_trace(self):
        # With no document the hook stays silent, but it MUST log: it is the
        # only thing telling "did not fire" apart from "fired and kept quiet".
        rc, out, _ = self.run_hook("session-start", self.payload("SessionStart"))
        self.assertEqual(rc, 0)
        self.assertIsNone(out)
        log = self.project / ".baton" / "local" / "log.jsonl"
        self.assertTrue(log.exists(), "the hook must log even when silent")
        self.assertEqual(json.loads(log.read_text(encoding="utf-8").strip())["event"],
                         "session-start")


class TestIsolation(BaseCase):
    """A test may not write outside its temporary directory."""

    def test_a_payload_without_cwd_does_not_touch_the_real_repo(self):
        real = REPO_ROOT / ".baton" / "local" / "log.jsonl"
        before = real.read_bytes() if real.exists() else None
        self.run_hook("session-start", {"session_id": "x"})
        after = real.read_bytes() if real.exists() else None
        self.assertEqual(before, after, "the suite has written into the real repo")


if __name__ == "__main__":
    unittest.main()
