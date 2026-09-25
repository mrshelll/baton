"""The handoff asked for when the session fills up, before the harness compacts.

Every test runs the real hook as a subprocess, the way the harness does, against
a transcript written the way Claude Code writes it. HOME points at an empty
folder and the window variables are removed, so nothing here depends on the
settings of whoever runs the suite.
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import storage  # noqa: E402

MODEL = "claude-sonnet-4-6"   # 200k in the table: 1% is 2,000 tokens


class Base(BaseCase):
    def setUp(self):
        super().setUp()
        self.home = Path(self._tmp) / "home"
        self.home.mkdir()
        self.p = storage.Paths(self.project)
        self.p.document.parent.mkdir(parents=True, exist_ok=True)
        self.p.document.write_text("---\nbaton: 1\nmode: memory\n---\n## State\nx\n",
                                   encoding="utf-8")

    def env(self):
        return {"HOME": str(self.home), "CLAUDE_CODE_MAX_CONTEXT_TOKENS": None,
                "CLAUDE_CODE_AUTO_COMPACT_WINDOW": None}

    def configure(self, cooldown=None, **context_window):
        data = {"context_window": context_window}
        if cooldown is not None:
            data["cooldown_minutes"] = cooldown
        (self.project / ".claude").mkdir(exist_ok=True)
        (self.project / ".claude" / "baton.json").write_text(json.dumps(data), encoding="utf-8")

    def at(self, percent, model=MODEL, extra=()):
        return str(self.transcript([self.identity(model), self.answer(percent * 2_000, model=model),
                                    *extra]))

    def stop(self, percent=None, session="s1", active=False, transcript=None, **extra):
        payload = self.payload("Stop", stop_hook_active=active, session_id=session, **extra)
        payload["transcript_path"] = transcript or (self.at(percent) if percent else "/dev/null")
        return self.run_hook("stop", payload, env=self.env())

    def batch(self, percent, session="s1", **extra):
        payload = self.payload("PostToolBatch", session_id=session, tool_calls=[], **extra)
        payload["transcript_path"] = self.at(percent)
        return self.run_hook("tool-batch", payload, env=self.env())

    def compact(self, session="s1"):
        # Same session as the Stops around it, as in the harness.
        return self.run_hook("post-compact", self.payload(
            "PostCompact", session_id=session, trigger="auto", compact_summary="summary"),
            env=self.env())

    def state(self):
        return json.loads(self.p.window.read_text(encoding="utf-8"))

    def log(self):
        if not self.p.log.exists():
            return []
        return [json.loads(l) for l in self.p.log.read_text(encoding="utf-8").splitlines() if l]


class TestTheRequest(Base):
    def test_below_the_first_threshold_it_stays_quiet(self):
        rc, out, err = self.stop(60)
        self.assertEqual(rc, 0, err)
        self.assertIsNone(out)

    def test_at_the_threshold_it_asks_and_tells_the_person(self):
        rc, out, err = self.stop(66)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["decision"], "block")
        self.assertIn("66%", out["reason"])
        self.assertIn("132k", out["reason"])
        self.assertIn("66%", out["systemMessage"])
        # Copy the compaction request by mistake and the model goes looking for
        # a summary that does not exist.
        self.assertNotIn("just been compacted", out["reason"])

    def test_by_default_it_asks_before_writing(self):
        _, out, _ = self.stop(66)
        self.assertIn("Do NOT write anything yet", out["reason"])

    def test_without_confirm_it_goes_straight_to_writing(self):
        self.configure(confirm=False)
        _, out, _ = self.stop(66)
        self.assertNotIn("Do NOT write anything yet", out["reason"])
        self.assertIn("baton.py write", out["reason"])

    def test_the_same_threshold_is_not_asked_twice(self):
        self.configure(cooldown=0)
        self.stop(66)
        rc, out, _ = self.stop(70)
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_the_next_threshold_asks_again_and_says_the_old_one_aged(self):
        self.configure(cooldown=0)
        _, first, _ = self.stop(66)
        self.assertNotIn("rewrite it WHOLE", first["reason"])
        _, out, _ = self.stop(86)
        self.assertEqual(out["decision"], "block")
        self.assertIn("rewrite it WHOLE", out["reason"])

    def test_inside_the_cooldown_the_next_threshold_waits_and_is_not_lost(self):
        self.stop(66)
        _, out, _ = self.stop(86)
        self.assertIsNone(out)
        self.assertEqual(self.state()["fired"], [65])   # 85 postponed, not consumed
        data = json.loads(self.p.pending.read_text(encoding="utf-8"))
        data["last_request"] = (datetime.now(timezone.utc) - timedelta(hours=1)
                                ).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.p.pending.write_text(json.dumps(data), encoding="utf-8")
        _, out, _ = self.stop(86)
        self.assertEqual(out["decision"], "block")

    def test_a_session_resumed_past_both_thresholds_is_asked_once(self):
        self.configure(cooldown=0)
        _, out, _ = self.stop(90)
        self.assertEqual(out["decision"], "block")
        self.assertEqual(self.state()["fired"], [65, 85])
        _, out, _ = self.stop(91)
        self.assertIsNone(out)

    def test_a_new_session_is_asked_again(self):
        self.configure(cooldown=0)
        self.stop(66, session="s1")
        _, out, _ = self.stop(66, session="s2")
        self.assertEqual(out["decision"], "block")

    def test_inside_a_blocked_stop_it_stays_quiet(self):
        rc, out, _ = self.stop(99, active=True)
        self.assertEqual(rc, 0)
        self.assertIsNone(out)


class TestWhatDoesNotCount(Base):
    def test_a_subagent_never_triggers_it(self):
        rc, out, _ = self.stop(99, agent_id="agent-1")
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_a_subagent_answer_in_the_transcript_does_not_count(self):
        path = self.at(10, extra=[self.answer(198_000, model=MODEL, sidechain=True)])
        _, out, _ = self.stop(transcript=path)
        self.assertIsNone(out)

    def test_switched_off_it_stays_quiet(self):
        self.configure(enabled=False)
        _, out, _ = self.stop(99)
        self.assertIsNone(out)

    def test_where_baton_is_not_enabled_nothing_is_measured_or_written(self):
        self.p.document.unlink()
        _, out, _ = self.stop(99)
        self.assertIsNone(out)
        self.assertFalse(self.p.window.exists())

    def test_an_unreadable_transcript_is_silence(self):
        rc, out, err = self.stop(transcript=str(self.project))
        self.assertEqual(rc, 0, err)
        self.assertIsNone(out)
        self.assertIn("context unknown", self.log()[-1]["result"])

    def test_every_turn_leaves_the_percentage_in_the_log(self):
        # Without it, "why did it not warn me at 80%?" cannot be answered.
        self.stop(30)
        self.assertIn("30%", self.log()[-1]["result"])


class TestWithTheCompaction(Base):
    def test_a_pending_compaction_wins_and_the_threshold_waits(self):
        self.configure(cooldown=0)
        self.compact()
        _, out, _ = self.stop(70)
        self.assertIn("just been compacted", out["reason"])
        self.assertEqual(self.state()["fired"], [])
        _, out, _ = self.stop(70)
        self.assertIn("70%", out["reason"])

    def test_a_window_request_leaves_the_compaction_cycle_working(self):
        self.configure(cooldown=0)
        self.stop(66)
        self.compact()
        _, out, _ = self.stop(20)
        self.assertIn("just been compacted", out["reason"])

    def test_a_compaction_clears_the_thresholds(self):
        # It moves the baseline: 90% becomes 20%, and the thresholds already met
        # describe an occupation that no longer exists.
        self.configure(cooldown=0)
        self.stop(66)
        self.compact()
        self.assertEqual(self.state()["fired"], [])


class TestCalibration(Base):
    def test_a_model_the_table_does_not_know_is_learnt(self):
        # 450k tokens on an assumed 200k window would read 225%: the observation
        # proves the window is bigger, and that is remembered.
        path = str(self.transcript([self.answer(450_000, model="claude-future-9")]))
        _, out, _ = self.stop(transcript=path)
        self.assertIsNone(out)
        self.assertEqual(self.state()["marks"], {"claude-future-9": 450_000})
        self.assertIn("45%", self.log()[-1]["result"])


class TestTheEarlyWarning(Base):
    def test_past_the_watch_mark_the_model_is_told_once(self):
        rc, out, err = self.batch(61)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolBatch")
        self.assertIn("61%", out["hookSpecificOutput"]["additionalContext"])
        _, out, _ = self.batch(62)
        self.assertIsNone(out)

    def test_below_the_watch_mark_nothing(self):
        _, out, _ = self.batch(50)
        self.assertIsNone(out)

    def test_zero_switches_it_off(self):
        self.configure(watch_at=0)
        _, out, _ = self.batch(90)
        self.assertIsNone(out)

    def test_a_subagent_batch_is_ignored(self):
        _, out, _ = self.batch(90, agent_id="agent-1")
        self.assertIsNone(out)

    def test_once_a_threshold_was_asked_it_has_nothing_to_add(self):
        self.stop(66)
        _, out, _ = self.batch(67)
        self.assertIsNone(out)

    def test_a_new_session_is_warned_again(self):
        self.batch(61, session="s1")
        _, out, _ = self.batch(61, session="s2")
        self.assertIsNotNone(out)

    def test_where_baton_is_not_enabled_nothing(self):
        self.p.document.unlink()
        _, out, _ = self.batch(90)
        self.assertIsNone(out)

    def test_a_quiet_batch_leaves_no_trace_in_the_log(self):
        # It runs after every batch of tools: logging each one would push out of
        # a 200-line log everything worth reading.
        self.batch(30)
        self.assertEqual([e for e in self.log() if e["event"] == "tool-batch"], [])


if __name__ == "__main__":
    unittest.main()
