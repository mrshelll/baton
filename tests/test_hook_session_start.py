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
