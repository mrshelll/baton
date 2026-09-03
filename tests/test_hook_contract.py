"""The contract no path may break: the hook ALWAYS exits 0.

A broken handoff, a corrupt stdin or a full disk cannot stop a Claude Code
session from starting. These tests invoke the hook as a subprocess with JSON on
stdin, exactly like the harness.
"""
import json
import subprocess
import sys
import unittest

from tests.helpers import REPO_ROOT, BaseCase, clean_env

EVENTS = ("session-start", "post-compact", "stop")


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
