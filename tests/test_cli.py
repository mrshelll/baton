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


class TestDoctorContextWindow(Base):
    """"Why did it not warn me at 80%?" has to have an answer one command away."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(REPO_ROOT))
        from lib import storage
        self.storage = storage
        d = self.project / ".baton"; d.mkdir(parents=True)
        (d / "HANDOFF.md").write_text("---\nbaton: 1\n---\n", encoding="utf-8")

    def remember(self, last):
        self.storage.save_window(self.storage.Paths(self.project), {"last": last})

    def test_it_shows_the_last_reading_and_where_the_size_came_from(self):
        self.remember({"percent": 23, "tokens": 231_000, "budget": 1_000_000,
                       "model": "claude-opus-5-5[1m]", "source": "model"})
        p = self.cli("doctor")
        self.assertEqual(p.returncode, OK, p.stderr)
        for expected in ("23%", "231,000", "1,000,000", "claude-opus-5-5[1m]", "model"):
            self.assertIn(expected, p.stdout)

    def test_before_the_first_turn_it_says_so(self):
        p = self.cli("doctor")
        self.assertIn("not measured yet", p.stdout)

    def test_a_garbage_reading_is_not_measured_yet(self):
        self.remember({"percent": "lots", "tokens": None, "budget": "x"})
        p = self.cli("doctor")
        self.assertEqual(p.returncode, OK, p.stderr)
        self.assertIn("not measured yet", p.stdout)

    def test_switched_off_it_says_so(self):
        (self.project / ".claude").mkdir()
        (self.project / ".claude" / "baton.json").write_text(
            '{"context_window": {"enabled": false}}', encoding="utf-8")
        p = self.cli("doctor")
        self.assertIn("switched off", p.stdout)


class TestPanel(Base):
    """`panel --json`: everything the mod draws, parsed here and only here.

    The mod calls it every turn, so it never asks and never fails loudly: any
    situation it can describe comes back as JSON with exit code 0."""

    BODY = ("## Estado\nMigración a medias.\n\n"
            "## Decisiones y su porqué\n- usar X -- porque Y\n\n"
            "## Bloqueos\n1. ¿seguimos con A o con B?\n2. falta la clave de **staging**\n\n"
            "## Siguiente paso\nterminar pay.ts:40\n\n"
            "## Trampas\n- no tocar el seed\n")

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(REPO_ROOT))
        import json
        from lib import document, storage
        self.json, self.document, self.storage = json, document, storage

    def spanish(self, where=None):
        claude = (where or self.project) / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "baton.json").write_text('{"language": "es"}', encoding="utf-8")

    def write(self, body=None, mode="memory"):
        self.draft(body or self.BODY)
        p = self.cli("write", "--mode", mode)
        self.assertEqual(p.returncode, OK, p.stderr)
        return self.handoff()

    def panel(self, *args, session="s1"):
        extra = ("--session", session) if session is not None else ()
        p = self.cli("panel", "--json", *extra, *args)
        self.assertEqual(p.returncode, OK, p.stderr)
        self.assertEqual(p.stderr, "", "the mod calls this every turn: nothing on stderr")
        return self.json.loads(p.stdout)

    def note_compaction(self, session, text):
        paths = self.storage.Paths(self.project)
        self.storage.note_compact_request(paths, session)
        self.storage.mark_compact_written(
            paths, session, self.document.fingerprint(text, "Contexto"))

    def sub(self, rel):
        d = self.project / rel
        local = d / ".baton"
        local.mkdir(parents=True)
        (local / "HANDOFF.md").write_text(
            "---\nbaton: 1\nmode: continue\ndate: 2026-09-03T10:00:00-05:00\n"
            "branch: main\ncommit: abc1234\n---\n\n## State\nx\n", encoding="utf-8")

    # -- states ----------------------------------------------------------------
    def test_normal_carries_the_whole_handoff_in_panel_order(self):
        self.init_git()
        self.spanish()
        self.write()
        out = self.panel()
        self.assertEqual(out["version"], 1)
        self.assertEqual(out["language"], "es")
        self.assertEqual(out["state"], "normal")
        self.assertIsNone(out["error"])
        self.assertIsNone(out["threshold"])
        self.assertEqual(out["project"]["path"], str(self.project))
        self.assertEqual(out["project"]["name"], self.project.name)
        h = out["handoff"]
        self.assertEqual(h["mode"], "memory")
        self.assertEqual(h["written_by"], "manual")
        self.assertFalse(h["stale"])
        self.assertTrue(h["date"])
        self.assertEqual(h["age"], "recién")
        self.assertEqual(h["lines"], len(self.handoff().rstrip("\n").split("\n")))
        self.assertEqual([s["slug"] for s in h["sections"]],
                         ["blockers", "next", "state", "decisions", "traps"])
        self.assertEqual([s["urgent"] for s in h["sections"]],
                         [True, False, False, False, False])
        blockers = h["sections"][0]
        self.assertEqual(blockers["label"], "Bloqueos")
        self.assertEqual(blockers["items"],
                         ["1. ¿seguimos con A o con B?", "2. falta la clave de staging"])
        self.assertEqual(h["sections"][1]["items"], ["• terminar pay.ts:40"])
        self.assertNotIn("Contexto", [s["label"] for s in h["sections"]],
                         "the git section is baton's, not the work")

    def test_items_are_not_trimmed(self):
        self.init_git()
        long_line = "palabra " * 60
        self.spanish()
        self.write("## Estado\n" + long_line + "\n")
        items = self.panel()["handoff"]["sections"][0]["items"]
        self.assertEqual(items, ["• " + long_line.strip()], "the mod trims, not Python")

    def test_ready_after_this_sessions_compaction_wrote_the_current_handoff(self):
        self.init_git()
        self.spanish()
        text = self.write()
        self.note_compaction("s1", text)
        out = self.panel()
        self.assertEqual(out["state"], "ready")
        self.assertEqual(out["handoff"]["written_by"], "compaction")

    def test_another_sessions_compaction_is_not_ready_but_still_wrote_it(self):
        self.init_git()
        self.spanish()
        text = self.write()
        self.note_compaction("other-session", text)
        out = self.panel(session="s1")
        self.assertNotEqual(out["state"], "ready")
        self.assertEqual(out["handoff"]["written_by"], "compaction")

    def test_a_handoff_rewritten_by_hand_after_the_compaction_is_not_ready(self):
        self.init_git()
        self.spanish()
        self.note_compaction("s1", self.write())
        self.write("## Estado\notra cosa\n")
        out = self.panel()
        self.assertEqual(out["state"], "normal")
        self.assertEqual(out["handoff"]["written_by"], "manual")

    def test_without_a_session_nothing_is_ready_and_no_threshold_shows(self):
        self.init_git()
        text = self.write("## State\nx\n")
        self.note_compaction("", text)
        out = self.panel(session=None)
        self.assertEqual(out["state"], "normal")
        self.assertIsNone(out["threshold"])

    def test_threshold_when_this_session_crossed_one(self):
        self.init_git()
        self.write("## State\nx\n")
        self.storage.save_window(self.storage.Paths(self.project), {
            "session": "s1", "fired": [65, 80], "last": {"percent": 82}})
        out = self.panel()
        self.assertEqual(out["state"], "threshold")
        self.assertEqual(out["threshold"], {"percent": 82, "tier": 80})

    def test_another_sessions_threshold_does_not_count(self):
        self.init_git()
        self.write("## State\nx\n")
        self.storage.save_window(self.storage.Paths(self.project), {
            "session": "old", "fired": [65], "last": {"percent": 70}})
        out = self.panel()
        self.assertEqual(out["state"], "normal")
        self.assertIsNone(out["threshold"])

    def test_none_without_a_handoff(self):
        out = self.panel()
        self.assertEqual(out["state"], "none")
        self.assertIsNone(out["handoff"])
        self.assertEqual(out["project"]["path"], str(self.project))
        self.assertEqual(out["others"], [])
        self.assertEqual(out["language"], "en")

    @unittest.skipIf(getattr(__import__("os"), "geteuid", lambda: 1)() == 0,
                     "root reads anything")
    def test_an_unreadable_handoff_is_an_error_state_with_exit_zero(self):
        import os
        self.init_git()
        self.write("## State\nx\n")
        doc = self.project / ".baton" / "HANDOFF.md"
        os.chmod(doc, 0)
        self.addCleanup(os.chmod, doc, 0o644)
        out = self.panel()
        self.assertEqual(out["state"], "error")
        self.assertIsNone(out["handoff"])
        self.assertIn(str(doc), out["error"])

    def test_stale_when_the_code_moved_since(self):
        self.init_git()
        self.write("## State\nx\n")
        self.git("checkout", "-q", "-b", "other")
        self.assertTrue(self.panel()["handoff"]["stale"])

    # -- where -----------------------------------------------------------------
    def test_an_ambiguous_root_shows_no_project_and_lists_the_others(self):
        self.init_git()
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        out = self.panel()
        self.assertIsNone(out["project"])
        self.assertEqual(out["state"], "none")
        self.assertIsNone(out["handoff"])
        self.assertEqual([o["name"] for o in out["others"]], ["instrumentos", "radar"])
        self.assertEqual(out["others"][0]["mode"], "continue")
        self.assertTrue(out["others"][0]["age"].endswith("ago"))

    def test_a_named_project_is_shown_and_the_rest_are_others(self):
        self.init_git()
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        out = self.panel("--project", "radar")
        self.assertEqual(out["project"]["name"], "radar")
        self.assertEqual(out["state"], "normal")
        self.assertEqual([o["name"] for o in out["others"]], ["instrumentos"])

    def test_an_unknown_project_name_is_no_project_not_a_failure(self):
        self.init_git()
        self.sub("proyectos/radar")
        out = self.panel("--project", "nope")
        self.assertIsNone(out["project"])
        self.assertEqual(out["state"], "none")

    # -- untrusted input and failures -----------------------------------------
    def test_an_unknown_language_reports_the_english_it_fell_back_to(self):
        claude = self.project / ".claude"; claude.mkdir()
        (claude / "baton.json").write_text('{"language": "klingon"}', encoding="utf-8")
        out = self.panel()
        self.assertEqual(out["language"], "en")
        self.assertEqual(out["strings"]["action_write"], "Write handoff")

    def test_terminal_escapes_in_the_document_do_not_reach_the_mod(self):
        d = self.project / ".baton"; d.mkdir(parents=True)
        (d / "HANDOFF.md").write_text(
            "---\nbaton: 1\nmode: memory\ndate: 2026-01-01\x1b[2J\nbranch: main\n"
            "commit: abc1234\n---\n\n## State\nx\x1b]0;pwned\x07y\n", encoding="utf-8")
        out = self.panel()
        self.assertEqual(out["handoff"]["date"], "2026-01-01[2J")
        self.assertEqual(out["handoff"]["sections"][0]["items"], ["• x]0;pwnedy"])

    def test_an_unexpected_failure_is_still_json_and_exit_zero(self):
        import contextlib
        import importlib.util
        import io
        spec = importlib.util.spec_from_file_location(
            "baton_cli_under_test", REPO_ROOT / "scripts" / "baton.py")
        cli = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cli   # @dataclass looks its module up there
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(cli)

        def broken(args):
            raise RuntimeError("boom")
        cli._panel = broken
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["panel", "--json", "--cwd", str(self.project)])
        self.assertEqual(code, OK)
        out = self.json.loads(buf.getvalue())
        self.assertEqual(out["state"], "error")
        self.assertIsNone(out["project"])
        self.assertIn("RuntimeError: boom", out["error"])
        self.assertIn("action_write", out["strings"])

    # -- strings ---------------------------------------------------------------
    def test_strings_carry_the_band_and_panel_texts_in_the_configured_language(self):
        self.init_git()
        self.spanish()
        self.write()
        s = self.panel()["strings"]
        self.assertTrue(all(isinstance(v, str) for v in s.values()))
        self.assertEqual(s["action_new_session"], "Sesión nueva")
        self.assertEqual(s["action_write"], "Escribir traspaso")
        self.assertIn("✓ traspaso listo", s["band_ready"])
        self.assertIn("sin traspaso en este proyecto", s["band_none"])
        self.assertIn("Aún no hay traspaso en este proyecto", s["empty_title"])


if __name__ == "__main__":
    unittest.main()
