"""The CLI: exit codes are the protocol with the model."""
import sys
import unittest

from tests.helpers import REPO_ROOT, BaseCase

OK, OVER_BUDGET, INVALID, ENVIRONMENT = 0, 1, 2, 3


class Base(BaseCase):
    def draft(self, text):
        local = self.project / ".baton" / "local"
        local.mkdir(parents=True, exist_ok=True)
        (local / "draft.md").write_text(text, encoding="utf-8")

    def handoff(self):
        return (self.project / ".baton" / "HANDOFF.md").read_text(encoding="utf-8")


class TestContext(Base):
    def test_is_short_and_useful(self):
        self.init_git()
        p = self.cli("context")
        self.assertEqual(p.returncode, OK, p.stderr)
        self.assertLessEqual(len(p.stdout.strip().split("\n")), 25,
                             "the context cannot eat the budget it protects")
        self.assertIn("branch", p.stdout)

    def test_says_where_to_write_the_draft(self):
        self.assertIn("draft.md", self.cli("context").stdout)

    def test_warns_about_the_missing_gitignore_line(self):
        self.init_git()
        self.assertIn(".baton/local/", self.cli("context").stdout)

    def test_works_without_git(self):
        self.assertEqual(self.cli("context").returncode, OK)


class TestWrite(Base):
    def test_happy_path(self):
        self.init_git()
        self.draft("## State\nMigration to PaymentIntents half done.\n")
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, OK, p.stderr + p.stdout)
        doc = self.handoff()
        self.assertIn("mode: memory", doc)
        self.assertIn("PaymentIntents", doc)
        self.assertIn("## Context", doc)

    def test_what_is_written_reads_back(self):
        sys.path.insert(0, str(REPO_ROOT))
        from lib import document
        self.init_git()
        self.draft("## State\nx\n## Next step\ndo Y in a.py:1\n")
        self.cli("write", "--mode", "continue")
        self.assertEqual(document.read_mode(self.handoff()), "continue")

    def test_no_draft_is_a_structure_error(self):
        self.assertEqual(self.cli("write", "--mode", "memory").returncode, INVALID)

    def test_a_draft_without_state_is_a_structure_error(self):
        self.draft("## Traps\nwatch out for X\n")
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, INVALID)
        self.assertIn("State", p.stderr)

    def test_filler_is_a_structure_error(self):
        self.draft("## State\nx\n## Blockers\nnone\n")
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, INVALID)
        self.assertIn("DELETE", p.stderr)

    def test_continue_without_a_next_step(self):
        self.draft("## State\nx\n")
        p = self.cli("write", "--mode", "continue")
        self.assertEqual(p.returncode, INVALID)
        self.assertIn("continue", p.stderr)

    def test_going_over_budget_is_exit_one(self):
        self.draft("## State\n" + "filler line\n" * 200)
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, OVER_BUDGET, p.stderr)
        self.assertIn("Attempt 1 of 3", p.stderr)

    def test_on_failure_nothing_is_written_and_the_previous_survives(self):
        self.init_git()
        self.draft("## State\ngood\n")
        self.cli("write", "--mode", "memory")
        before = self.handoff()
        self.draft("## State\n" + "x\n" * 300)
        self.cli("write", "--mode", "memory")
        self.assertEqual(self.handoff(), before, "the previous handoff must survive")

    def test_on_the_third_attempt_it_writes_a_minimum_and_says_so(self):
        sys.path.insert(0, str(REPO_ROOT))
        from lib import budget
        self.init_git()
        fat = "## State\n" + "a fairly long filler line\n" * 200
        for _ in (1, 2):
            self.draft(fat)
            self.assertEqual(self.cli("write", "--mode", "memory").returncode, OVER_BUDGET)
        self.draft(fat)
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, OK, p.stderr)
        doc = self.handoff()
        self.assertIn("trimmed by baton", doc)
        self.assertTrue(budget.evaluate(doc).fits, budget.measure(doc))

    def test_a_success_resets_the_attempt_counter(self):
        self.init_git()
        self.draft("## State\n" + "x\n" * 300)
        self.cli("write", "--mode", "memory")
        self.draft("## State\nbrief\n")
        self.assertEqual(self.cli("write", "--mode", "memory").returncode, OK)
        self.draft("## State\n" + "x\n" * 300)
        self.assertIn("Attempt 1 of 3", self.cli("write", "--mode", "memory").stderr,
                      "the counter did not reset after a success")

    def test_an_invalid_mode_is_rejected_with_an_explanation(self):
        self.draft("## State\nx\n")
        p = self.cli("write", "--mode", "whatever")
        self.assertEqual(p.returncode, INVALID)
        self.assertIn("continue", p.stderr)

    def test_writing_enables_the_project(self):
        sys.path.insert(0, str(REPO_ROOT))
        from lib import storage
        self.assertFalse(storage.is_enabled(self.project))
        self.draft("## State\nx\n")
        self.cli("write", "--mode", "memory")
        self.assertTrue(storage.is_enabled(self.project))

    def test_spanish_config_writes_spanish_sections(self):
        import json
        claude = self.project / ".claude"; claude.mkdir(exist_ok=True)
        (claude / "baton.json").write_text(json.dumps({"language": "es"}), encoding="utf-8")
        self.draft("## Estado\nvamos por aqui\n")
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, OK, p.stderr)
        doc = self.handoff()
        self.assertIn("## Estado", doc)
        self.assertIn("## Contexto", doc)
        self.assertIn("mode: memory", doc, "the mode enum stays English in every language")


class TestShow(Base):
    def test_no_handoff_is_stated_without_failing(self):
        p = self.cli("show")
        self.assertEqual(p.returncode, OK, p.stderr)
        self.assertIn("no handoff yet", p.stdout)

    def test_summarises_mode_size_and_freshness(self):
        d = self.project / ".baton"
        d.mkdir(parents=True)
        (d / "HANDOFF.md").write_text(
            "---\nbaton: 1\nmode: continue\ndate: 2020-01-01T00:00:00Z\n"
            "branch: main\ncommit: abc1234\n---\n\n## State\nx\n", encoding="utf-8")
        p = self.cli("show")
        self.assertIn("continue mode", p.stdout)
        self.assertIn("lines", p.stdout)
        self.assertIn("Freshness", p.stdout)


class TestDoctor(Base):
    def test_a_project_not_enabled_is_explained_and_exits_zero(self):
        p = self.cli("doctor")
        self.assertEqual(p.returncode, OK, p.stderr)
        self.assertIn("does not use baton yet", p.stdout)
        self.assertIn("NOT a failure", p.stdout)

    def test_checks_hooks_python_git_and_language(self):
        p = self.cli("doctor")
        for expected in ("hooks.json valid", "python3", "git", "language"):
            self.assertIn(expected, p.stdout)

    def test_an_enabled_project_with_no_trace_blames_the_restart(self):
        d = self.project / ".baton"; d.mkdir(parents=True)
        (d / "HANDOFF.md").write_text("---\nbaton: 1\n---\n", encoding="utf-8")
        p = self.cli("doctor")
        self.assertIn("NO trace at all", p.stdout)
        self.assertIn("without restarting Claude Code", p.stdout)

    def test_a_recent_trace_blames_nobody(self):
        sys.path.insert(0, str(REPO_ROOT))
        from lib import storage
        d = self.project / ".baton"; d.mkdir(parents=True)
        (d / "HANDOFF.md").write_text("---\nbaton: 1\n---\n", encoding="utf-8")
        storage.log_event(storage.Paths(self.project), event="session-start", result="ok")
        p = self.cli("doctor")
        self.assertIn("Last hook run:", p.stdout)
        self.assertNotIn("NO trace at all", p.stdout)


if __name__ == "__main__":
    unittest.main()
