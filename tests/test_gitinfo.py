"""git: deterministic snapshot and freshness notice. Always degrade, never raise."""
import os
import shutil
import sys
import tempfile
import unittest

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import gitinfo, output  # noqa: E402

S = output.load_strings("en")


class NoGit:
    """Leaves PATH without `git`, to exercise the degraded path for real."""

    def __enter__(self):
        self._path = os.environ.get("PATH", "")
        self._empty = tempfile.mkdtemp(prefix="baton-no-git-")
        os.environ["PATH"] = self._empty
        gitinfo.clear_git_cache()
        return self

    def __exit__(self, *exc):
        os.environ["PATH"] = self._path
        shutil.rmtree(self._empty, ignore_errors=True)
        gitinfo.clear_git_cache()


class TestSnapshot(BaseCase):
    def test_clean_repo(self):
        self.init_git()
        s = gitinfo.snapshot(self.project)
        self.assertTrue(s.has_git)
        self.assertEqual(s.branch, "main")
        self.assertEqual(len(s.commit), 7)
        self.assertEqual(s.dirty, [])

    def test_uncommitted_files_show_up(self):
        self.init_git()
        for name in ("a.txt", "b.txt", "c.txt"):
            (self.project / name).write_text("x", encoding="utf-8")
        s = gitinfo.snapshot(self.project)
        self.assertEqual(len(s.dirty), 3)
        self.assertIn("a.txt", s.dirty)

    def test_names_with_spaces_and_accents(self):
        self.init_git()
        (self.project / "a file with ñ and tildé.txt").write_text("x", encoding="utf-8")
        self.assertIn("a file with ñ and tildé.txt", gitinfo.snapshot(self.project).dirty)

    def test_many_dirty_files_are_summarised(self):
        self.init_git()
        for i in range(30):
            (self.project / f"f{i:02d}.txt").write_text("x", encoding="utf-8")
        block = gitinfo.context_block(gitinfo.snapshot(self.project), S)
        self.assertLessEqual(len(block.split("\n")), 7, block)
        self.assertIn("+20 more", block)

    def test_repo_without_commits_does_not_break(self):
        self.init_git(commit=False)
        s = gitinfo.snapshot(self.project)
        self.assertTrue(s.has_git)
        self.assertEqual(s.commit, "no-commits")

    def test_directory_that_is_not_a_repo(self):
        s = gitinfo.snapshot(self.project)
        self.assertFalse(s.has_git)
        self.assertEqual(s.branch, "no-git")

    def test_no_git_on_the_path(self):
        self.init_git()
        with NoGit():
            s = gitinfo.snapshot(self.project)
        self.assertFalse(s.has_git)
        self.assertEqual(s.commit, "no-git")

    def test_the_context_block_never_exceeds_six_lines(self):
        self.init_git()
        block = gitinfo.context_block(gitinfo.snapshot(self.project), S)
        self.assertLessEqual(len(block.split("\n")), 6)

    def test_batons_own_files_are_not_the_users_work(self):
        self.init_git()
        (self.project / ".baton" / "local").mkdir(parents=True)
        (self.project / ".baton" / "HANDOFF.md").write_text("x", encoding="utf-8")
        (self.project / "code.py").write_text("y", encoding="utf-8")
        self.assertEqual(gitinfo.snapshot(self.project).dirty, ["code.py"])


class TestFreshness(BaseCase):
    def freshness(self, date, branch, commit):
        return gitinfo.freshness(self.project, date, branch, commit, S)

    def test_up_to_date_document_says_nothing(self):
        self.init_git()
        s = gitinfo.snapshot(self.project)
        self.assertEqual(self.freshness(gitinfo.now_iso(), s.branch, s.commit).notice(), "")

    def test_new_commits_are_counted(self):
        self.init_git()
        old = gitinfo.snapshot(self.project).commit
        for i in range(3):
            (self.project / f"n{i}.txt").write_text("x", encoding="utf-8")
            self.git("add", "-A")
            self.git("commit", "-q", "-m", f"c{i}")
        f = self.freshness(gitinfo.now_iso(), "main", old)
        self.assertEqual(f.new_commits, 3)
        self.assertIn("3 new commits", f.notice())

    def test_freshness_ignores_batons_own_files(self):
        self.init_git()
        old = gitinfo.snapshot(self.project).commit
        (self.project / ".baton").mkdir()
        (self.project / ".baton" / "HANDOFF.md").write_text("x", encoding="utf-8")
        (self.project / "code.py").write_text("y", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "changes")
        f = self.freshness(gitinfo.now_iso(), "main", old)
        self.assertEqual(f.changed_files, 1, "only code.py is the user's work")

    def test_different_branch_names_both(self):
        self.init_git()
        s = gitinfo.snapshot(self.project)
        notice = self.freshness(gitinfo.now_iso(), "other-branch", s.commit).notice()
        self.assertIn("other-branch", notice)
        self.assertIn("main", notice)

    def test_lost_commit_warns_about_a_rebase(self):
        self.init_git()
        f = self.freshness(gitinfo.now_iso(), "main", "0" * 7)
        self.assertTrue(f.commit_lost)
        self.assertIn("no longer exists", f.notice())

    def test_old_document_states_its_age(self):
        self.init_git()
        s = gitinfo.snapshot(self.project)
        self.assertIn("days ago", self.freshness("2020-01-01T00:00:00Z", s.branch, s.commit).notice())

    def test_without_git_it_can_only_talk_about_age(self):
        notice = self.freshness("2020-01-01T00:00:00Z", "main", "abc1234").notice()
        self.assertIn("days ago", notice)
        self.assertIn("not a git repository", notice)

    def test_unparseable_date_does_not_raise(self):
        self.init_git()
        self.assertIsInstance(self.freshness("yesterday afternoon", "main", "abc1234").notice(), str)

    def test_every_notice_carries_the_same_marker(self):
        # One marker to look for, not three wordings saying the same thing.
        self.init_git()
        s = gitinfo.snapshot(self.project)
        for args in (("2020-01-01T00:00:00Z", s.branch, s.commit),
                     (gitinfo.now_iso(), "other", s.commit),
                     (gitinfo.now_iso(), "main", "0" * 7)):
            with self.subTest(args=args):
                self.assertIn("Freshness notice", self.freshness(*args).notice())


if __name__ == "__main__":
    unittest.main()
