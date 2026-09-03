"""PostCompact captures, Stop asks. The automation covering what you don't control."""
import json
import sys
import unittest

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import storage  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
