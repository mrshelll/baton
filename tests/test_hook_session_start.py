"""SessionStart: from the file to the model's context."""
import json
import sys
import unittest

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import budget, document, output, storage  # noqa: E402

S = output.load_strings("en")


class Base(BaseCase):
    def write_handoff(self, mode="memory", body="## State\nthis is where we are\n", **kw):
        fields = dict(date="2026-09-03T10:00:00-05:00", branch="main", commit="abc1234")
        fields.update(kw)
        text = document.compose(body=body, mode=mode,
                                context="- branch `main`, working tree clean",
                                strings=S, **fields)
        paths = storage.Paths(self.project)
        paths.document.parent.mkdir(parents=True, exist_ok=True)
        paths.document.write_text(text, encoding="utf-8")
        return text

    def start(self, source="startup", **extra):
        return self.run_hook("session-start",
                             self.payload("SessionStart", source=source, **extra))

    def context(self, out):
        return out["hookSpecificOutput"]["additionalContext"]


class TestInjection(Base):
    def test_no_handoff_means_silence(self):
        rc, out, _ = self.start()
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_uses_the_structured_channel(self):
        self.write_handoff()
        rc, out, err = self.start()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("additionalContext", out["hookSpecificOutput"])

    def test_memory_mode_says_not_to_start_work(self):
        self.write_handoff(mode="memory")
        _, out, _ = self.start()
        text = self.context(out)
        self.assertIn("do NOT start work", text)
        self.assertIn("MEMORY MODE", text)

    def test_continue_mode_asks_to_resume(self):
        self.write_handoff(mode="continue", body="## State\nx\n## Next step\ndo Y\n")
        _, out, _ = self.start()
        text = self.context(out)
        self.assertIn("CONTINUE MODE", text)
        self.assertNotIn("do NOT start work", text)

    def test_carries_the_handoff_content(self):
        self.write_handoff(body="## State\ncanary xylophone-7731\n")
        _, out, _ = self.start()
        self.assertIn("xylophone-7731", self.context(out))

    def test_emits_the_receipt(self):
        self.write_handoff()
        _, out, _ = self.start()
        self.assertIn("baton", out["systemMessage"])

    def test_the_receipt_shows_what_the_session_left_behind(self):
        # The handoff reaches the model and never the screen. This line is the
        # only thing the person who wrote it actually sees.
        self.write_handoff(body="## State\nx\n\n## Blockers\nthe coupon question\n")
        _, out, _ = self.start()
        self.assertIn("the coupon question", out["systemMessage"])

    def test_the_receipt_can_be_reduced_to_one_line(self):
        (self.project / ".claude").mkdir(exist_ok=True)
        (self.project / ".claude" / "baton.json").write_text(
            '{"receipt_lines": 0}', encoding="utf-8")
        self.write_handoff(body="## State\nx\n\n## Blockers\nthe coupon question\n")
        _, out, _ = self.start()
        self.assertNotIn("the coupon question", out["systemMessage"])
        self.assertIn("baton", out["systemMessage"])

    def test_never_exceeds_the_harness_ceiling(self):
        self.write_handoff(body="## State\n" + "a long filler line\n" * 500)
        text = self.context(self.start()[1])
        self.assertLessEqual(len(text), budget.CEILING_CHARACTERS)
        self.assertLessEqual(len(text.split("\n")), budget.CEILING_LINES)

    def test_reading_does_not_modify_the_document(self):
        # A one-shot session must not consume the note meant for the next human
        # session.
        original = self.write_handoff()
        self.start()
        self.start()
        self.assertEqual(storage.Paths(self.project).document.read_text(encoding="utf-8"),
                         original)

    def test_a_corrupt_document_does_not_break_startup(self):
        paths = storage.Paths(self.project)
        paths.document.parent.mkdir(parents=True, exist_ok=True)
        paths.document.write_bytes(b"\x00\x01\x02 binary junk \xff\xfe")
        rc, _, err = self.start()
        self.assertEqual(rc, 0, err)

    def test_a_document_without_frontmatter_is_injected_as_memory(self):
        paths = storage.Paths(self.project)
        paths.document.parent.mkdir(parents=True, exist_ok=True)
        paths.document.write_text("## State\nno header\n", encoding="utf-8")
        self.assertIn("MEMORY MODE", self.context(self.start()[1]))


class TestFreshnessOnInjection(Base):
    def test_an_old_handoff_is_flagged(self):
        self.write_handoff(date="2020-01-01T00:00:00Z")
        self.assertIn("Freshness notice", self.context(self.start()[1]))

    def test_a_fresh_handoff_without_git_spends_no_lines(self):
        import datetime
        today = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()
        self.write_handoff(date=today, branch="no-git", commit="no-git")
        self.assertNotIn("Freshness notice", self.context(self.start()[1]))


class TestDeliveryRegister(Base):
    def test_flags_a_repeat_delivery(self):
        self.write_handoff()
        self.start()
        self.assertIn("already been delivered", self.context(self.start()[1]))

    def test_the_first_time_is_not_flagged(self):
        self.write_handoff()
        self.assertNotIn("already been delivered", self.context(self.start()[1]))

    def test_a_compaction_is_not_a_new_session(self):
        self.write_handoff()
        for _ in range(3):
            self.start(source="compact")
        self.assertNotIn("already been delivered", self.context(self.start(source="compact")[1]))

    def test_a_new_handoff_resets_the_count(self):
        self.write_handoff(body="## State\none\n")
        self.start(); self.start()
        self.write_handoff(body="## State\ntwo\n")
        self.assertNotIn("already been delivered", self.context(self.start()[1]))


class TestAfterACompaction(Base):
    """The SessionStart of `compact` runs before -- or alongside -- the PostCompact,
    so it decides by the note this session's PreCompact left: the summary carries
    a newer handoff than the one on disk, and reinjecting the old one would put
    yesterday on top of today."""

    def log(self):
        log = storage.Paths(self.project).log
        return [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l]

    def test_a_block_asked_by_this_session_is_not_reinjected(self):
        self.write_handoff()
        storage.note_compact_request(storage.Paths(self.project), "test-session")
        rc, out, err = self.start(source="compact")
        self.assertEqual(rc, 0, err)
        self.assertIsNone(out)
        self.assertEqual(self.log()[-1]["result"],
                         "silent: handoff travels in the compaction summary")

    def test_a_note_from_another_session_injects_as_today(self):
        self.write_handoff()
        storage.note_compact_request(storage.Paths(self.project), "another-session")
        _, out, _ = self.start(source="compact")
        self.assertIn("this is where we are", self.context(out))

    def test_without_a_note_it_injects_as_today(self):
        self.write_handoff()
        _, out, _ = self.start(source="compact")
        self.assertIn("this is where we are", self.context(out))

    def test_an_active_projects_note_does_not_silence_the_roots_handoff(self):
        # The block replaces radar's handoff, not the root's: the root's handoff
        # and the index are not in the summary, and silencing them loses them.
        from lib import projects
        self.write_handoff()
        radar = self.project / "radar"
        storage.Paths(radar).document.parent.mkdir(parents=True)
        storage.Paths(radar).document.write_text(
            "---\nbaton: 1\nmode: memory\n---\n## State\nradar state\n", encoding="utf-8")
        found = projects.discover(self.project)
        target = next(p for p in found.projects if p.name == "radar")
        projects.set_active(self.project, target, session="test-session")
        storage.note_compact_request(storage.Paths(radar), "test-session")
        _, out, _ = self.start(source="compact")
        injected = self.context(out)
        self.assertIn("this is where we are", injected)
        self.assertIn("radar", injected)

    def test_a_failure_resolving_the_note_injects_as_today(self):
        # Never leave the person with nothing: if the check itself breaks, the
        # handoff on disk is better than an error notice.
        import importlib.util
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        spec = importlib.util.spec_from_file_location(
            "baton_hook_destination_fails", REPO_ROOT / "hooks" / "baton_hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)

        def boom(*_):
            raise RuntimeError("config on fire")

        self.write_handoff()
        storage.note_compact_request(storage.Paths(self.project), "test-session")
        stdin = io.StringIO(json.dumps(self.payload("SessionStart", source="compact")))
        captured = io.StringIO()
        with mock.patch.object(hook, "_compaction_destination", boom), \
                mock.patch.object(sys, "argv", ["baton_hook.py", "session-start"]), \
                mock.patch.object(sys, "stdin", stdin), redirect_stdout(captured):
            self.assertEqual(hook.main(), 0)
        out = json.loads(captured.getvalue())
        self.assertIn("this is where we are", self.context(out))
        self.assertNotIn("could not complete", out.get("systemMessage", ""))

    def test_the_note_only_silences_a_compaction(self):
        # A /clear right after is a new session: it needs the handoff on disk,
        # which by then is the one the compaction wrote.
        self.write_handoff()
        storage.note_compact_request(storage.Paths(self.project), "test-session")
        _, out, _ = self.start(source="clear")
        self.assertIn("this is where we are", self.context(out))


class TestWithTheMod(Base):
    """With baton's mod active the panel shows what the receipt showed: the
    handoff still goes to the model, the receipt does not go to the screen."""

    def test_the_mod_signal_drops_the_receipt_and_keeps_the_handoff(self):
        self.write_handoff()
        rc, out, err = self.start(source="clear", baton_mod=True)
        self.assertEqual(rc, 0, err)
        self.assertIn("this is where we are", self.context(out))
        self.assertNotIn("systemMessage", out)

    def test_display_panel_drops_the_receipt_too(self):
        self.write_handoff()
        claude = self.project / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "baton.json").write_text(json.dumps({"display": "panel"}), encoding="utf-8")
        _, out, _ = self.start(source="clear")
        self.assertIn("this is where we are", self.context(out))
        self.assertNotIn("systemMessage", out)

    def test_an_index_alone_drops_the_receipt_too(self):
        sub = self.project / "radar"
        storage.Paths(sub).document.parent.mkdir(parents=True)
        storage.Paths(sub).document.write_text(
            "---\nbaton: 1\nmode: memory\n---\n## State\nx\n", encoding="utf-8")
        _, out, _ = self.start(source="clear", baton_mod=True)
        self.assertIn("radar", self.context(out))
        self.assertNotIn("systemMessage", out)

    def test_without_the_mod_the_receipt_stays(self):
        self.write_handoff()
        _, out, _ = self.start(source="clear", baton_mod="true")   # a near-miss is not the mod
        self.assertIn("systemMessage", out)


class TestStartFilter(Base):
    def test_honours_inject_on(self):
        self.write_handoff()
        claude = self.project / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "baton.json").write_text(json.dumps({"inject_on": ["startup"]}),
                                           encoding="utf-8")
        self.assertIsNotNone(self.start(source="startup")[1])
        self.assertIsNone(self.start(source="resume")[1], "resume was excluded by config")


class TestLanguage(Base):
    def test_spanish_config_injects_spanish_instructions(self):
        claude = self.project / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "baton.json").write_text(json.dumps({"language": "es"}), encoding="utf-8")
        es = output.load_strings("es")
        text = document.compose(body="## Estado\nvamos por aqui\n", mode="memory",
                                date="2026-09-03T10:00:00-05:00", branch="main",
                                commit="abc1234", context="- rama `main`", strings=es)
        paths = storage.Paths(self.project)
        paths.document.parent.mkdir(parents=True, exist_ok=True)
        paths.document.write_text(text, encoding="utf-8")
        injected = self.context(self.start()[1])
        self.assertIn("NO inicies trabajo", injected)
        self.assertIn("vamos por aqui", injected)


if __name__ == "__main__":
    unittest.main()
