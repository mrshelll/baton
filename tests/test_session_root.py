"""The session's root: where the session started, not where its shell went.

A shell `cd` moves a hook's `cwd` (and the CLI's) into a subfolder, and that
subfolder may be a repo of its own: a `.git` there is a root marker, and baton
then read and wrote a project nobody opened.
"""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from tests.helpers import REPO_ROOT, BaseCase, clean_env

sys.path.insert(0, str(REPO_ROOT))
from lib import document, output, storage  # noqa: E402

S = output.load_strings("en")


class Base(BaseCase):
    def setUp(self):
        super().setUp()
        # The session's folder has the handoff; inside it, a repo of its own.
        self.write_handoff()
        self.nested = self.project / "app vault"
        (self.nested / ".git").mkdir(parents=True)

    def write_handoff(self, body="## State\nthis is where we are\n"):
        text = document.compose(body=body, mode="memory",
                                context="- branch `main`, working tree clean", strings=S,
                                date="2026-09-03T10:00:00-05:00", branch="main", commit="abc1234")
        paths = storage.Paths(self.project)
        paths.document.parent.mkdir(parents=True, exist_ok=True)
        paths.document.write_text(text, encoding="utf-8")


class TestSessionRoot(Base):
    def root(self, cwd, start=None, env=None):
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("CLAUDE_PROJECT_DIR", "BATON_PROJECT_DIR")}
        with mock.patch.dict(os.environ, {**clean, **(env or {})}, clear=True):
            return storage.session_root(cwd, start)

    def test_from_the_folder_the_session_started_in(self):
        self.assertEqual(self.root(self.nested, start=self.project), self.project)
        self.assertEqual(self.root(self.nested / "deep" / "er", start=self.project), self.project)

    def test_from_the_environment_when_no_start_is_given(self):
        self.assertEqual(self.root(self.nested, env={"CLAUDE_PROJECT_DIR": str(self.project)}),
                         self.project)
        self.assertEqual(self.root(self.nested, env={"BATON_PROJECT_DIR": str(self.project)}),
                         self.project)

    def test_the_hooks_own_variable_comes_before_baton_s_copy(self):
        other = self.nested
        self.assertEqual(self.root(self.nested / "x", env={
            "CLAUDE_PROJECT_DIR": str(self.project), "BATON_PROJECT_DIR": str(other)}), self.project)

    def test_without_a_start_it_is_the_cwd_s_root_as_always(self):
        self.assertEqual(self.root(self.nested), self.nested)
        self.assertEqual(self.root(self.project), self.project)

    def test_a_cwd_outside_the_start_folder_keeps_its_own_root(self):
        elsewhere = self.project.parent / "elsewhere"
        (elsewhere / ".git").mkdir(parents=True)
        self.assertEqual(self.root(elsewhere, start=self.project), elsewhere)
        self.assertEqual(self.root(elsewhere, env={"CLAUDE_PROJECT_DIR": str(self.project)}), elsewhere)

    def test_a_session_started_in_the_subfolder_stays_there(self):
        self.assertEqual(self.root(self.nested, start=self.nested), self.nested)

    def test_a_subproject_with_a_handoff_of_its_own_keeps_it(self):
        # `cd` into a project below the root that has its own handoff: that one
        # is where the session stands, as before; only a folder with none climbs.
        sub = self.project / "radar"
        storage.Paths(sub).document.parent.mkdir(parents=True)
        storage.Paths(sub).document.write_text("---\nbaton: 1\nmode: memory\n---\n## State\nx\n",
                                               encoding="utf-8")
        self.assertEqual(self.root(sub, start=self.project), sub)
        self.assertEqual(self.root(sub / "src", start=self.project), sub)
        self.assertEqual(self.root(sub, env={"CLAUDE_PROJECT_DIR": str(self.project)}), sub)

    def test_a_nested_folder_with_only_baton_s_local_state_still_climbs(self):
        # What a Stop logged there before this fix: `.baton/local/log.jsonl`.
        (self.nested / ".baton" / "local").mkdir(parents=True)
        self.assertEqual(self.root(self.nested, start=self.project), self.project)

    def test_a_moved_document_counts_as_a_handoff_of_its_own(self):
        sub = self.project / "radar"
        (sub / ".claude").mkdir(parents=True)
        (sub / ".claude" / "baton.json").write_text(json.dumps({"document": "docs/HANDOFF.md"}),
                                                    encoding="utf-8")
        (sub / "docs").mkdir()
        (sub / "docs" / "HANDOFF.md").write_text("---\nbaton: 1\nmode: memory\n---\n", encoding="utf-8")
        self.assertEqual(self.root(sub, start=self.project), sub)

    def test_an_empty_or_relative_start_is_ignored(self):
        self.assertEqual(self.root(self.nested, start=""), self.nested)
        self.assertEqual(self.root(self.nested, env={"CLAUDE_PROJECT_DIR": "relative/path"}), self.nested)


class TestHooksReadTheSessionRoot(Base):
    def env(self):
        return {"CLAUDE_PROJECT_DIR": str(self.project)}

    def test_session_start_from_a_nested_repo_injects_the_session_s_handoff(self):
        payload = self.payload("SessionStart", source="clear", cwd=str(self.nested))
        rc, out, err = self.run_hook("session-start", payload, env=self.env())
        self.assertEqual(rc, 0, err)
        self.assertIn("this is where we are", out["hookSpecificOutput"]["additionalContext"])

    def test_without_the_variable_it_is_the_nested_repo_as_before(self):
        payload = self.payload("SessionStart", source="clear", cwd=str(self.nested))
        rc, out, _ = self.run_hook("session-start", payload, env={"CLAUDE_PROJECT_DIR": None})
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_stop_from_a_nested_repo_logs_in_the_session_s_project(self):
        payload = self.payload("Stop", stop_hook_active=False, cwd=str(self.nested))
        rc, _, err = self.run_hook("stop", payload, env=self.env())
        self.assertEqual(rc, 0, err)
        log = storage.Paths(self.project).local / "log.jsonl"
        self.assertTrue(log.is_file())
        self.assertFalse((self.nested / ".baton").exists())


class TestSubprojectsUnderTheSessionRoot(Base):
    """A root holding projects, the session started at it, its shell in one."""

    def setUp(self):
        super().setUp()
        storage.Paths(self.project).document.unlink()
        for name in ("a", "b"):
            paths = storage.Paths(self.project / name)
            paths.document.parent.mkdir(parents=True)
            paths.document.write_text(f"---\nbaton: 1\nmode: memory\n---\n## State\nproject {name}\n",
                                      encoding="utf-8")

    def test_the_panel_shows_the_subproject_the_shell_stands_in(self):
        p = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "baton.py"), "panel", "--json",
             "--cwd", str(self.project / "a"), "--root", str(self.project)],
            capture_output=True, text=True, env=clean_env(), timeout=60)
        data = json.loads(p.stdout)
        self.assertEqual(data["state"], "normal", p.stderr)
        self.assertIsNotNone(data["handoff"])

    def test_session_start_from_the_subproject_injects_its_handoff(self):
        payload = self.payload("SessionStart", source="clear", cwd=str(self.project / "a"))
        _, out, err = self.run_hook("session-start", payload, env={"CLAUDE_PROJECT_DIR": str(self.project)})
        self.assertIn("project a", out["hookSpecificOutput"]["additionalContext"], err)


class TestSessionStartPassesTheRootToBash(Base):
    """The skill runs `baton.py` from the Bash tool, which gets no
    CLAUDE_PROJECT_DIR: the SessionStart hands it on through CLAUDE_ENV_FILE."""

    def test_it_exports_the_session_root_quoted(self):
        env_file = self.project.parent / "session env" / "sessionstart-hook-0.sh"
        env_file.parent.mkdir()
        env_file.write_text("export OTHER=1\n", encoding="utf-8")
        payload = self.payload("SessionStart", source="startup")
        rc, _, err = self.run_hook("session-start", payload, env={
            "CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_ENV_FILE": str(env_file)})
        self.assertEqual(rc, 0, err)
        lines = env_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "export OTHER=1")
        self.assertEqual(lines[1], f"export BATON_PROJECT_DIR='{self.project}'")

    def test_even_where_baton_is_not_enabled_yet(self):
        storage.Paths(self.project).document.unlink()
        env_file = self.project.parent / "env.sh"
        rc, out, err = self.run_hook("session-start", self.payload("SessionStart", source="startup"), env={
            "CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_ENV_FILE": str(env_file)})
        self.assertEqual(rc, 0, err)
        self.assertIsNone(out)
        self.assertIn("BATON_PROJECT_DIR", env_file.read_text(encoding="utf-8"))

    def test_no_variable_no_file_and_nothing_breaks(self):
        rc, out, err = self.run_hook("session-start", self.payload("SessionStart", source="startup"),
                                     env={"CLAUDE_PROJECT_DIR": str(self.project)})
        self.assertEqual(rc, 0, err)
        self.assertIn("this is where we are", out["hookSpecificOutput"]["additionalContext"])

    def test_an_env_file_that_cannot_be_written_does_not_stop_the_injection(self):
        missing = self.project.parent / "no such dir" / "env.sh"
        rc, out, err = self.run_hook("session-start", self.payload("SessionStart", source="startup"), env={
            "CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_ENV_FILE": str(missing)})
        self.assertEqual(rc, 0, err)
        self.assertIn("this is where we are", out["hookSpecificOutput"]["additionalContext"])


class TestCliReadsTheSessionRoot(Base):
    def run_cli(self, *args, env=None):
        import subprocess
        from tests.helpers import clean_env
        environment = clean_env()
        environment.update(env or {})
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "baton.py"), *args],
            capture_output=True, text=True, env=environment, cwd=str(self.nested), timeout=60)

    def test_panel_with_root_shows_the_session_s_handoff(self):
        p = self.run_cli("panel", "--json", "--cwd", str(self.nested), "--root", str(self.project))
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertNotEqual(data["state"], "none")
        self.assertIsNotNone(data["handoff"])

    def test_panel_without_root_is_the_nested_repo_as_before(self):
        p = self.run_cli("panel", "--json", "--cwd", str(self.nested))
        self.assertEqual(json.loads(p.stdout)["state"], "none")

    def test_context_from_bash_reads_baton_project_dir(self):
        p = self.run_cli("context", env={"BATON_PROJECT_DIR": str(self.project)})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(str(storage.Paths(self.project).draft), p.stdout)
        self.assertFalse((self.nested / ".baton").exists())


if __name__ == "__main__":
    unittest.main()
