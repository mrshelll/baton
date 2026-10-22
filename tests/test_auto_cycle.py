"""PostCompact captures, Stop asks. The automation covering what you don't control."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import output, projects, storage  # noqa: E402


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


class TestCompactRequest(BaseCase):
    def paths(self):
        return storage.Paths(self.project)

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
