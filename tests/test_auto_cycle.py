"""PostCompact captures, Stop asks. The automation covering what you don't control."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import document, output, projects, storage  # noqa: E402


class Base(BaseCase):
    def enable(self, content="---\nbaton: 1\nmode: memory\n---\n## State\nx\n"):
        p = storage.Paths(self.project)
        p.document.parent.mkdir(parents=True, exist_ok=True)
        p.document.write_text(content, encoding="utf-8")
        return p

    def compact(self, summary="Conversation summary: Stripe was migrated.", trigger="auto"):
        return self.run_hook("post-compact", self.payload(
            "PostCompact", trigger=trigger, compact_summary=summary))

    def stop(self, active=False, **extra):
        return self.run_hook("stop", self.payload("Stop", stop_hook_active=active, **extra))

    def pending(self):
        p = storage.Paths(self.project)
        return json.loads(p.pending.read_text(encoding="utf-8")) if p.pending.exists() else None


class TestPostCompact(Base):
    def test_does_nothing_when_not_enabled(self):
        rc, _, _ = self.compact()
        self.assertEqual(rc, 0)
        self.assertIsNone(self.pending())

    def test_saves_the_summary_and_arms_the_flag(self):
        self.enable()
        rc, _, err = self.compact("Summary: canary xylophone-7731")
        self.assertEqual(rc, 0, err)
        kept = list(storage.Paths(self.project).auto.glob("summary-*.md"))
        self.assertEqual(len(kept), 1)
        self.assertIn("xylophone-7731", kept[0].read_text(encoding="utf-8"))
        self.assertIsNotNone(self.pending())

    def test_never_touches_the_handoff(self):
        # A summary nobody wrote must not overwrite one written with judgement.
        # This is the rule that avoids the worst possible failure.
        p = self.enable("---\nbaton: 1\nmode: continue\n---\n## State\nmine\n")
        before = p.document.read_bytes()
        self.compact()
        self.assertEqual(p.document.read_bytes(), before)

    def test_keeps_only_the_last_three_summaries(self):
        self.enable()
        for i in range(5):
            self.compact(f"summary number {i}")
        self.assertLessEqual(
            len(list(storage.Paths(self.project).auto.glob("summary-*.md"))), 3)

    def test_a_payload_without_a_summary_does_not_break(self):
        self.enable()
        rc, _, err = self.run_hook("post-compact", self.payload("PostCompact", trigger="auto"))
        self.assertEqual(rc, 0, err)


class TestStop(Base):
    def test_silent_without_a_flag(self):
        self.enable()
        rc, out, _ = self.stop()
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_silent_when_the_project_is_not_enabled(self):
        rc, out, _ = self.stop()
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_with_a_flag_it_asks_for_the_handoff(self):
        self.enable()
        self.compact()
        rc, out, err = self.stop()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("baton", out.get("reason", "").lower())

    def test_stop_hook_active_disables_it(self):
        # The harness's own loop guard: inside an already blocked Stop we cannot
        # block again.
        self.enable()
        self.compact()
        self.assertIsNone(self.stop(active=True)[1])

    def test_asks_only_once_per_compaction(self):
        self.enable()
        self.compact()
        self.assertEqual(self.stop()[1].get("decision"), "block")
        self.assertIsNone(self.stop()[1], "it cannot ask twice for one compaction")

    def test_consumes_the_flag_even_if_the_model_never_writes(self):
        self.enable()
        self.compact()
        self.stop()
        p = self.pending()
        self.assertTrue(p is None or p.get("requested"), "the flag must be consumed")

    def test_another_compaction_within_the_cooldown_does_not_interrupt_again(self):
        # Two compactions in a row are not two reasons to interrupt: the
        # cooldown protects the user, not the compaction.
        self.enable()
        self.compact(); self.stop()
        self.compact()
        self.assertIsNone(self.stop()[1])

    def test_another_compaction_past_the_cooldown_does_ask(self):
        self.enable()
        claude = self.project / ".claude"; claude.mkdir(exist_ok=True)
        (claude / "baton.json").write_text(json.dumps({"cooldown_minutes": 0}), encoding="utf-8")
        self.compact(); self.stop()
        self.compact()
        self.assertEqual(self.stop()[1].get("decision"), "block")

    def test_corrupt_stdin_exits_zero(self):
        self.enable()
        rc, _, err = self.run_hook("stop", None, raw_input="{broken")
        self.assertEqual(rc, 0, err)


class TestPreCompact(Base):
    """Before compacting, baton asks the summarizer for the handoff block.

    Its stdout is NOT JSON: Claude Code appends it verbatim to the summarizer's
    instructions and also shows it raw to the person on /compact."""

    def precompact(self, trigger="manual", **extra):
        return self.run_hook_text("pre-compact", self.payload(
            "PreCompact", trigger=trigger, **extra))

    def requests(self):
        return list(Path(self._tmp).rglob("compact-request.json"))

    def log_results(self, where):
        log = storage.Paths(where).log
        return [json.loads(l)["result"] for l in log.read_text(encoding="utf-8").splitlines()
                if l.strip()]

    def sub(self, rel):
        d = self.project / rel
        d.mkdir(parents=True)
        return self.enable_at(d)

    def enable_at(self, where):
        p = storage.Paths(where)
        p.document.parent.mkdir(parents=True, exist_ok=True)
        p.document.write_text("---\nbaton: 1\nmode: memory\n---\n## State\nx\n", encoding="utf-8")
        return where

    def test_a_project_with_a_handoff_gets_the_instruction_and_the_note(self):
        self.enable()
        rc, out, err = self.precompact(session_id="sesión 42")
        self.assertEqual(rc, 0, err)
        self.assertIn('<baton-handoff mode=', out)
        self.assertIn("</baton-handoff>", out)
        self.assertFalse(out.lstrip().startswith("{"), "plain text, never JSON")
        note = json.loads(storage.Paths(self.project).compact_request.read_text(encoding="utf-8"))
        self.assertEqual(note["session"], "sesión 42")
        self.assertIs(note["written"], False)
        self.assertTrue(note["requested_at"])

    def test_the_instruction_fits_in_twelve_lines(self):
        # Ruling 7: shown to the person on every /compact and kept in the
        # compacted context.
        self.enable()
        _, out, _ = self.precompact()
        self.assertLessEqual(len(out.strip().splitlines()), 12, out)

    def test_auto_and_manual_both_ask(self):
        self.enable()
        for trigger in ("auto", "manual"):
            with self.subTest(trigger=trigger):
                self.assertIn("</baton-handoff>", self.precompact(trigger=trigger)[1])

    def test_a_root_with_two_projects_and_none_active_stays_silent(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        rc, out, err = self.precompact()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(self.requests(), [])
        self.assertIn("silent: ambiguous target", self.log_results(self.project))

    def test_the_active_project_gets_the_note(self):
        radar = self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        found = projects.discover(self.project)
        target = next(p for p in found.projects if p.name.endswith("radar"))
        projects.set_active(self.project, target, session="test-session")
        rc, out, err = self.precompact()
        self.assertEqual(rc, 0, err)
        self.assertIn("</baton-handoff>", out)
        self.assertEqual(self.requests(), [storage.Paths(radar).compact_request])

    def test_a_session_standing_below_a_root_without_handoff_stays_silent(self):
        # The one case writable_target asks where; a hook cannot ask.
        (self.project / ".claude").mkdir()   # makes it the root seen from below
        self.sub("proyectos/radar")
        here = self.project / "otra carpeta"
        here.mkdir()
        rc, out, _ = self.precompact(cwd=str(here))
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")
        self.assertEqual(self.requests(), [])

    def test_a_project_not_enabled_stays_silent(self):
        rc, out, err = self.precompact()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "")
        self.assertEqual(self.requests(), [])

    def test_in_spanish_it_names_estado_as_required(self):
        self.enable()
        claude = self.project / ".claude"; claude.mkdir()
        (claude / "baton.json").write_text(json.dumps({"language": "es"}), encoding="utf-8")
        _, out, _ = self.precompact()
        self.assertIn('"## Estado" (required)', out)
        self.assertIn("Spanish", out)

    def test_it_is_idempotent(self):
        self.enable()
        first = self.precompact(session_id="a")[1]
        second = self.precompact(session_id="b")[1]
        self.assertEqual(first, second)
        note = json.loads(storage.Paths(self.project).compact_request.read_text(encoding="utf-8"))
        self.assertEqual(note["session"], "b")


class TestCompactionInstruction(unittest.TestCase):
    def cfg(self, language="en", **limits):
        return {"language": language,
                "limits": dict({"lines": 120, "characters": 6000, "tokens": 1700}, **limits)}

    def test_names_every_section_and_the_required_one(self):
        for language in ("en", "es"):
            strings = output.load_strings(language)
            text = output.compaction_instruction(self.cfg(language), strings)
            with self.subTest(language=language):
                for name in strings["sections"].values():
                    self.assertIn(f'"## {name}"', text)
                required = strings["sections"][strings["required_section"]]
                self.assertIn(f'"## {required}" (required)', text)

    def test_the_budget_comes_from_the_config(self):
        text = output.compaction_instruction(self.cfg(lines=77, characters=4321),
                                             output.load_strings("en"))
        self.assertIn("77 lines", text)
        self.assertIn("4321 characters", text)

    def test_it_warns_that_the_last_messages_are_out_of_view(self):
        # Ruling 5: the summarizer never sees the preserved tail.
        text = output.compaction_instruction(self.cfg(), output.load_strings("en"))
        self.assertIn("outside your view", text)
        self.assertIn("Distill, do not copy the summary", text)

    def test_it_asks_for_both_modes_and_ends_the_output_with_the_block(self):
        text = output.compaction_instruction(self.cfg(), output.load_strings("en"))
        self.assertIn('"continue"', text)
        self.assertIn('"memory"', text)
        self.assertIn("nothing after </baton-handoff>", text)


class TestPostCompactWritesTheBlock(Base):
    """With a note from this session's PreCompact and a valid block at the end of
    the summary, the PostCompact writes the handoff and arms nothing. Anything
    else falls back to today's path and leaves the previous handoff untouched."""

    PREVIOUS = "---\nbaton: 1\nmode: continue\n---\n## State\nthe previous one\n"

    def setUp(self):
        super().setUp()
        self.paths = self.enable(self.PREVIOUS)
        self.before = self.paths.document.read_bytes()

    @staticmethod
    def summary(body="## State\nStripe migrated in src/pay.py; refunds left.\n",
                mode="memory", tail="\n"):
        tag = output.COMPACTION_TAG
        return ("<analysis>thinking</analysis>\n<summary>Stripe was migrated.</summary>\n"
                f'<{tag} mode="{mode}">\n{body}</{tag}>{tail}')

    def note(self, where=None, session="test-session"):
        storage.note_compact_request(storage.Paths(where or self.project), session)

    def post(self, summary=None, **extra):
        return self.run_hook_text("post-compact", self.payload(
            "PostCompact", trigger="auto",
            compact_summary=self.summary() if summary is None else summary, **extra))

    def config(self, data):
        claude = self.project / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "baton.json").write_text(json.dumps(data), encoding="utf-8")

    def last_result(self, where=None):
        log = storage.Paths(where or self.project).log
        lines = [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
        return json.loads(lines[-1])["result"]

    def request(self, where=None):
        return json.loads(storage.Paths(where or self.project).compact_request
                          .read_text(encoding="utf-8"))

    def armed(self, where=None):
        p = storage.Paths(where or self.project).pending
        return p.exists() and bool(json.loads(p.read_text(encoding="utf-8")).get("armed"))

    def summaries(self, where=None):
        return list(storage.Paths(where or self.project).auto.glob("summary-*.md"))

    def assert_fell_back(self, out):
        self.assertEqual(out, "")
        self.assertEqual(self.paths.document.read_bytes(), self.before)
        self.assertTrue(self.armed(), "the fallback arms the flag as today")
        self.assertEqual(len(self.summaries()), 1)

    # -- written -------------------------------------------------------------
    def test_a_valid_block_is_written_and_nothing_is_armed(self):
        self.note()
        rc, out, err = self.post()
        self.assertEqual(rc, 0, err)
        text = self.paths.document.read_text(encoding="utf-8")
        self.assertIn("Stripe migrated in src/pay.py", text)
        self.assertIn("mode: memory", text)
        self.assertFalse(self.armed())
        note = self.request()
        self.assertIs(note["written"], True)
        self.assertTrue(note["written_at"])
        self.assertEqual(note["fingerprint"], document.fingerprint(text))
        self.assertEqual(out.strip(), output.load_strings("en")["auto_handoff"]["ready"])
        self.assertFalse(out.lstrip().startswith("{"), "PostCompact stdout is shown raw")
        self.assertIn("handoff written from compaction", self.last_result())

    def test_the_summary_is_saved_even_when_written(self):
        self.note()
        self.post()
        self.assertEqual(len(self.summaries()), 1)

    def test_the_previous_handoff_goes_to_the_history(self):
        self.note()
        self.post()
        kept = list(self.paths.history.glob("HANDOFF-*-continue.md"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_bytes(), self.before)

    def test_a_continue_block_is_written_in_memory_mode(self):
        # Ruling 5: the summarizer cannot see the latest messages.
        self.note()
        self.post(self.summary(mode="continue",
                               body="## State\nhalf done\n## Next step\nedit src/a.py:3\n"))
        text = self.paths.document.read_text(encoding="utf-8")
        self.assertEqual(document.read_mode(text), "memory")
        self.assertIn("edit src/a.py:3", text)
        result = self.last_result()
        self.assertIn("handoff written from compaction", result)
        self.assertIn("continue", result)

    def test_in_spanish_the_notice_is_spanish(self):
        self.config({"language": "es"})
        self.note()
        _, out, _ = self.post(self.summary(body="## Estado\nStripe migrado.\n"))
        self.assertEqual(out.strip(),
                         "baton: traspaso listo. Escribe /clear para seguir en una sesión nueva.")

    def test_the_active_project_gets_it_and_the_root_does_not(self):
        radar = self.project / "proyectos" / "radar"
        other = self.project / "proyectos" / "instrumentos"
        for where in (radar, other):
            where.mkdir(parents=True)
            self.enable_at(where)
        found = projects.discover(self.project)
        active = next(p for p in found.projects if p.name.endswith("radar"))
        projects.set_active(self.project, active, session="test-session")
        radar_before = storage.Paths(radar).document.read_bytes()
        self.note(radar)
        rc, _, err = self.post()
        self.assertEqual(rc, 0, err)
        self.assertNotEqual(storage.Paths(radar).document.read_bytes(), radar_before)
        self.assertEqual(self.paths.document.read_bytes(), self.before)
        self.assertFalse(self.armed(radar))
        self.assertIs(self.request(radar)["written"], True)

    def enable_at(self, where):
        p = storage.Paths(where)
        p.document.parent.mkdir(parents=True, exist_ok=True)
        p.document.write_text("---\nbaton: 1\nmode: memory\n---\n## State\nx\n", encoding="utf-8")

    # -- the mod speaks instead ------------------------------------------------
    def test_with_the_mod_it_writes_and_prints_nothing(self):
        self.note()
        rc, out, err = self.post(baton_mod=True)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "")
        self.assertIn("Stripe migrated", self.paths.document.read_text(encoding="utf-8"))
        self.assertFalse(self.armed())

    def test_display_panel_prints_nothing_either(self):
        self.config({"display": "panel"})
        self.note()
        _, out, _ = self.post()
        self.assertEqual(out, "")
        self.assertIn("Stripe migrated", self.paths.document.read_text(encoding="utf-8"))

    # -- fallback --------------------------------------------------------------
    def test_without_a_note_it_behaves_as_today(self):
        rc, out, err = self.post()
        self.assertEqual(rc, 0, err)
        self.assert_fell_back(out)
        self.assertEqual(self.last_result(), "summary saved, handoff pending")

    def test_a_note_from_another_session_is_no_note(self):
        self.note(session="another session")
        _, out, _ = self.post()
        self.assert_fell_back(out)
        self.assertIs(self.request()["written"], False)

    def test_an_empty_session_id_is_no_session(self):
        self.note(session="")
        _, out, _ = self.post(session_id="")
        self.assert_fell_back(out)

    def test_over_budget_falls_back(self):
        self.note()
        long = "".join(f"- line {i} of a summary nobody distilled\n" for i in range(200))
        _, out, _ = self.post(self.summary(body=f"## State\n{long}"))
        self.assert_fell_back(out)
        self.assertIs(self.request()["written"], False)
        self.assertIn("compaction block rejected: over_budget", self.last_result())

    def test_an_invalid_block_falls_back(self):
        self.note()
        _, out, _ = self.post(self.summary(body="## Traps\nno state here\n"))
        self.assert_fell_back(out)
        self.assertIn("compaction block rejected: invalid", self.last_result())

    def test_a_summary_without_a_block_falls_back(self):
        self.note()
        _, out, _ = self.post("Summary: Stripe was migrated.")
        self.assert_fell_back(out)
        self.assertIn("compaction block not found", self.last_result())

    def test_a_cut_off_block_falls_back(self):
        self.note()
        _, out, _ = self.post(self.summary(tail="\nand then the summarizer kept talking"))
        self.assert_fell_back(out)
        self.assertIn("compaction block not found", self.last_result())

    def test_a_draft_in_progress_is_not_overwritten(self):
        # Ruling 10: a model may be in the middle of /baton.
        self.note()
        self.paths.ensure_local()
        self.paths.draft.write_text("## State\nmine, half written\n", encoding="utf-8")
        _, out, _ = self.post()
        self.assert_fell_back(out)
        self.assertEqual(self.paths.draft.read_text(encoding="utf-8"),
                         "## State\nmine, half written\n")
        self.assertIn("compaction block not written: draft in progress", self.last_result())

    def test_a_busy_handoff_falls_back_without_retrying(self):
        self.note()
        self.paths.ensure_local()
        self.paths.lock.write_text("99999", encoding="utf-8")   # fresh: another writer
        _, out, _ = self.post()
        self.assert_fell_back(out)
        self.assertIn("compaction block rejected: busy", self.last_result())

    def test_an_unexpected_failure_still_arms_the_flag(self):
        # Failing half-way must not leave a compaction with neither a handoff
        # nor a request for one.
        import importlib.util
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        spec = importlib.util.spec_from_file_location(
            "baton_hook_build_fails", REPO_ROOT / "hooks" / "baton_hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)

        def boom(*_):
            raise RuntimeError("git on fire")

        self.note()
        stdin = io.StringIO(json.dumps(self.payload(
            "PostCompact", trigger="auto", compact_summary=self.summary())))
        captured = io.StringIO()
        with mock.patch.object(hook.handoff, "build", boom), \
                mock.patch.object(sys, "argv", ["baton_hook.py", "post-compact"]), \
                mock.patch.object(sys, "stdin", stdin), redirect_stdout(captured):
            self.assertEqual(hook.main(), 0)
        self.assert_fell_back(captured.getvalue())
        self.assertIn("compaction block failed: RuntimeError: git on fire", self.last_result())

    def test_running_twice_ends_in_the_same_state(self):
        self.note()
        self.post()
        first = document.extract_body(self.paths.document.read_text(encoding="utf-8"))
        rc, _, err = self.post()
        self.assertEqual(rc, 0, err)
        self.assertEqual(document.extract_body(self.paths.document.read_text(encoding="utf-8")),
                         first)
        self.assertFalse(self.armed())


class TestModActive(unittest.TestCase):
    def mod_active(self, entry, display="receipt"):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "baton_hook_mod_active", REPO_ROOT / "hooks" / "baton_hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        return hook._mod_active(entry, {"display": display})

    def test_the_payload_signal_or_the_panel_display(self):
        self.assertTrue(self.mod_active({"baton_mod": True}))
        self.assertTrue(self.mod_active({}, display="panel"))
        self.assertFalse(self.mod_active({}))
        for fake in ("true", 1, "yes", None):
            with self.subTest(fake=fake):
                self.assertFalse(self.mod_active({"baton_mod": fake}))


class TestCompactRequest(BaseCase):
    def paths(self):
        return storage.Paths(self.project)

    def test_mark_written_records_the_fingerprint(self):
        storage.note_compact_request(self.paths(), "s1")
        storage.mark_compact_written(self.paths(), "s1", "abc123")
        note = storage.read_compact_request(self.paths(), "s1")
        self.assertIs(note["written"], True)
        self.assertEqual(note["fingerprint"], "abc123")
        self.assertTrue(note["written_at"])

    def test_mark_written_leaves_another_sessions_note_alone(self):
        # Another session's PreCompact may have replaced the note meanwhile.
        storage.note_compact_request(self.paths(), "s2")
        storage.mark_compact_written(self.paths(), "s1", "abc123")
        note = storage.read_compact_request(self.paths(), "s2")
        self.assertIs(note["written"], False)
        self.assertNotIn("fingerprint", note)

    def test_mark_written_without_a_note_writes_nothing(self):
        storage.mark_compact_written(self.paths(), "s1", "abc123")
        self.assertFalse(self.paths().compact_request.exists())

    def test_read_returns_the_note_of_this_session(self):
        storage.note_compact_request(self.paths(), "s1")
        note = storage.read_compact_request(self.paths(), "s1")
        self.assertEqual(note["session"], "s1")
        self.assertIs(note["written"], False)

    def test_another_session_reads_nothing(self):
        storage.note_compact_request(self.paths(), "s1")
        self.assertIsNone(storage.read_compact_request(self.paths(), "s2"))

    def test_an_empty_session_id_is_no_session(self):
        storage.note_compact_request(self.paths(), "")
        self.assertIsNone(storage.read_compact_request(self.paths(), ""))

    def test_an_old_note_reads_nothing(self):
        p = self.paths()
        p.ensure_local()
        old = (datetime.now(timezone.utc) - timedelta(hours=13)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p.compact_request.write_text(json.dumps(
            {"session": "s1", "requested_at": old, "written": False}), encoding="utf-8")
        self.assertIsNone(storage.read_compact_request(p, "s1"))
        self.assertIsNotNone(storage.read_compact_request(p, "s1", max_age_hours=14))

    def test_garbage_reads_nothing(self):
        p = self.paths()
        p.ensure_local()
        for garbage in ("{broken", "[1]", json.dumps({"session": "s1"}),
                        json.dumps({"session": "s1", "requested_at": 5})):
            with self.subTest(garbage=garbage):
                p.compact_request.write_text(garbage, encoding="utf-8")
                self.assertIsNone(storage.read_compact_request(p, "s1"))

    def test_missing_file_reads_nothing(self):
        self.assertIsNone(storage.read_compact_request(self.paths(), "s1"))


if __name__ == "__main__":
    unittest.main()
