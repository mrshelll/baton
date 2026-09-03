"""Paths, activation, log, atomic writing, locking and history rotation."""
import json
import os
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

from tests.helpers import REPO_ROOT, BaseCase, clean_env

sys.path.insert(0, str(REPO_ROOT))
from lib import storage  # noqa: E402


class TestProjectRoot(BaseCase):
    def test_finds_the_root_through_git(self):
        self.init_git()
        deep = self.project / "src" / "very" / "deep"
        deep.mkdir(parents=True)
        self.assertEqual(storage.project_root(deep), self.project)

    def test_git_as_a_file_is_a_valid_worktree(self):
        # In a worktree, .git is a FILE pointing at the real repo.
        (self.project / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        deep = self.project / "a" / "b"
        deep.mkdir(parents=True)
        self.assertEqual(storage.project_root(deep), self.project)

    def test_finds_the_root_through_the_claude_folder(self):
        (self.project / ".claude").mkdir()
        (self.project / "x").mkdir()
        self.assertEqual(storage.project_root(self.project / "x"), self.project)

    def test_the_baton_folder_marks_the_root_too(self):
        (self.project / ".baton").mkdir()
        (self.project / "x").mkdir()
        self.assertEqual(storage.project_root(self.project / "x"), self.project)

    def test_with_no_marker_it_returns_the_cwd(self):
        self.assertEqual(storage.project_root(self.project), self.project)

    def test_a_missing_cwd_does_not_break(self):
        ghost = self.project / "no" / "such"
        self.assertEqual(storage.project_root(ghost), ghost)


class TestEnabling(BaseCase):
    def test_a_new_project_is_not_enabled(self):
        self.assertFalse(storage.is_enabled(self.project))

    def test_the_document_is_the_enabling_signal(self):
        paths = storage.Paths(self.project)
        paths.document.parent.mkdir(parents=True, exist_ok=True)
        paths.document.write_text("---\nbaton: 1\n---\n", encoding="utf-8")
        self.assertTrue(storage.is_enabled(self.project))


class TestLog(BaseCase):
    def test_one_jsonl_line_per_run(self):
        paths = storage.Paths(self.project)
        storage.log_event(paths, event="session-start", result="silent")
        storage.log_event(paths, event="stop", result="quiet")
        lines = paths.log.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["event"], "session-start")

    def test_capped_at_two_hundred_lines(self):
        paths = storage.Paths(self.project)
        for i in range(260):
            storage.log_event(paths, event="session-start", result=str(i))
        lines = paths.log.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), storage.LOG_MAX_LINES)
        self.assertEqual(json.loads(lines[-1])["result"], "259", "the newest must survive")

    def test_never_raises_even_on_an_impossible_target(self):
        storage.log_event(storage.Paths(Path("/proc/never-writable")), event="stop", result="x")


class TestAtomicWrite(BaseCase):
    def paths(self):
        return storage.Paths(self.project)

    def test_the_first_write_creates_the_tree(self):
        p = self.paths()
        storage.write_document(p, "content\n", history_max=10)
        self.assertEqual(p.document.read_text(encoding="utf-8"), "content\n")
        self.assertFalse(any(p.history.glob("*.md")), "the first one rotates nothing")

    def test_the_second_sends_the_previous_to_history(self):
        p = self.paths()
        storage.write_document(p, "---\nbaton: 1\nmode: memory\n---\nfirst\n", history_max=10)
        storage.write_document(p, "---\nbaton: 1\nmode: continue\n---\nsecond\n", history_max=10)
        self.assertIn("second", p.document.read_text(encoding="utf-8"))
        kept = sorted(p.history.glob("*.md"))
        self.assertEqual(len(kept), 1)
        self.assertIn("first", kept[0].read_text(encoding="utf-8"))
        self.assertIn("memory", kept[0].name,
                      "the name carries the mode of the ARCHIVED document, not the new one")

    def test_exactly_the_last_ten_are_kept(self):
        p = self.paths()
        for i in range(12):
            storage.write_document(p, f"v{i}\n", history_max=10)
        self.assertEqual(len(list(p.history.glob("*.md"))), 10)

    def test_history_zero_keeps_nothing(self):
        p = self.paths()
        storage.write_document(p, "a\n", history_max=0)
        storage.write_document(p, "b\n", history_max=0)
        self.assertFalse(list(p.history.glob("*.md")))

    def test_never_deletes_other_peoples_files(self):
        # A plugin that deletes files needs to be incapable of getting it wrong.
        p = self.paths()
        p.history.mkdir(parents=True, exist_ok=True)
        intruder = p.history / "notes.md"
        intruder.write_text("my own notes\n", encoding="utf-8")
        for i in range(15):
            storage.write_document(p, f"v{i}\n", history_max=3)
        self.assertTrue(intruder.is_file(), "baton deleted a file that is not its own")
        self.assertEqual(intruder.read_text(encoding="utf-8"), "my own notes\n")

    def test_a_collision_in_the_same_second_does_not_overwrite(self):
        p = self.paths()
        storage.write_document(p, "one\n", history_max=10)
        for i in range(3):
            storage.write_document(p, f"n{i}\n", history_max=10)
        self.assertEqual(len({q.name for q in p.history.glob("*.md")}), 3)

    def test_the_draft_is_removed_on_a_successful_write(self):
        p = self.paths()
        p.ensure_local()
        p.draft.write_text("## State\nx\n", encoding="utf-8")
        storage.write_document(p, "final\n", history_max=10)
        self.assertFalse(p.draft.exists())


class TestLock(BaseCase):
    def test_two_writers_at_once_do_not_interleave(self):
        # The final file has to be one of the two WHOLE, never half of each.
        script = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from lib import storage
            p = storage.Paths({str(self.project)!r})
            try:
                storage.write_document(p, sys.argv[1] * 20000 + "\\n", history_max=5)
                print("ok")
            except storage.BusyError:
                print("busy")
        """)
        procs = [subprocess.Popen([sys.executable, "-c", script, letter],
                                  stdout=subprocess.PIPE, text=True, env=clean_env())
                 for letter in ("A", "B")]
        outs = [p.communicate()[0].strip() for p in procs]
        self.assertIn("ok", outs)
        final = storage.Paths(self.project).document.read_text(encoding="utf-8")
        self.assertIn(final, ("A" * 20000 + "\n", "B" * 20000 + "\n"),
                      "the document came out interleaved")

    def test_an_expired_lock_can_be_stolen(self):
        p = storage.Paths(self.project)
        p.ensure_local()
        p.lock.write_text("zombie process", encoding="utf-8")
        old = time.time() - (storage.LOCK_EXPIRY_SECONDS + 30)
        os.utime(p.lock, (old, old))
        storage.write_document(p, "I could write\n", history_max=5)
        self.assertEqual(p.document.read_text(encoding="utf-8"), "I could write\n")

    def test_a_live_lock_blocks(self):
        p = storage.Paths(self.project)
        p.ensure_local()
        p.lock.write_text("another process", encoding="utf-8")
        with self.assertRaises(storage.BusyError):
            storage.write_document(p, "should not\n", history_max=5)


class TestEnvironmentErrors(BaseCase):
    def test_without_permissions_it_raises_a_typed_error_not_a_traceback(self):
        p = storage.Paths(self.project)
        p.baton.mkdir(parents=True)
        os.chmod(p.baton, 0o500)
        self.addCleanup(os.chmod, p.baton, 0o700)
        with self.assertRaises(storage.StorageError):
            storage.write_document(p, "x\n", history_max=5)


if __name__ == "__main__":
    unittest.main()
