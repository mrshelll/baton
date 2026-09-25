"""Measuring the context window from the transcript, and deciding what 100% is.

The transcript is Claude Code's internal format and it WILL change. Every test
about garbage here is the same promise seen from another angle: when baton does
not understand what it reads, it says "I do not know" and never raises.
"""
import json
import os
import sys
import unittest
from unittest import mock

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import window  # noqa: E402


class TestReadUsage(BaseCase):
    def test_sums_the_three_input_fields_and_leaves_output_out(self):
        # The real answer this whole feature was measured against: it is the
        # figure the statusline paints as total_input_tokens.
        path = self.transcript([{"type": "assistant", "message": {
            "model": "claude-opus-5", "usage": {
                "input_tokens": 2, "cache_read_input_tokens": 62642,
                "cache_creation_input_tokens": 18172, "output_tokens": 1940}}}])
        self.assertEqual(window.read_usage(path).tokens, 80816)

    def test_takes_the_last_main_thread_answer_not_the_first(self):
        path = self.transcript([self.answer(50_000), self.answer(90_000)])
        self.assertEqual(window.read_usage(path).tokens, 90_000)

    def test_a_subagent_answer_at_the_end_does_not_count(self):
        path = self.transcript([self.answer(90_000),
                                self.answer(700_000, sidechain=True)])
        self.assertEqual(window.read_usage(path).tokens, 90_000)

    def test_a_synthetic_answer_measures_nothing_and_is_skipped(self):
        # Real: Claude Code writes "No response requested." as an assistant entry
        # with model <synthetic> and every counter at zero -- 30 of them in this
        # machine's transcripts. Read as the latest answer, it would say 0%.
        synthetic = self.answer(0, model="<synthetic>", output=0)
        path = self.transcript([self.answer(90_000), synthetic])
        self.assertEqual(window.read_usage(path).tokens, 90_000)

    def test_later_entries_without_usage_do_not_hide_the_answer(self):
        path = self.transcript([
            self.answer(90_000),
            {"type": "user", "message": {"content": "hi"}},
            {"type": "attachment", "attachment": {"type": "skill_listing"}},
            {"type": "a-type-nobody-has-invented-yet", "usage": {"input_tokens": 7}},
        ])
        self.assertEqual(window.read_usage(path).tokens, 90_000)

    def test_nothing_readable_is_unknown(self):
        empty = self.project / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        blank = self.project / "blank.jsonl"
        blank.write_text("\n\n\n", encoding="utf-8")
        for path in (self.project / "missing.jsonl", self.project, "/dev/null",
                     "", None, empty, blank):
            with self.subTest(path=path):
                self.assertIsNone(window.read_usage(path))

    def test_a_number_is_not_taken_for_a_file_descriptor(self):
        # open() takes an int as a descriptor and closes it on the way out: a
        # transcript_path of 1 would close the hook's own stdout.
        r, w = os.pipe()
        self.addCleanup(os.close, w)
        self.addCleanup(os.close, r)
        self.assertIsNone(window.read_usage(r))
        os.fstat(r)  # raises if read_usage closed it

    def test_garbage_around_the_answer_never_raises(self):
        path = self.project / "dirty.jsonl"
        good = json.dumps(self.answer(90_000)).encode()
        path.write_bytes(b"not json at all\n" + good + b"\n[1, 2, 3]\n"
                         b"\xff\xfe broken utf-8\n\x00\x00\n"
                         b'{"type": "assistant", "message": {"usa')
        self.assertEqual(window.read_usage(path).tokens, 90_000)

    def test_a_usage_it_does_not_understand_is_unknown_not_a_guess(self):
        # The newest answer is the only one worth trusting: if its shape is
        # foreign, the format changed, and an older figure would be stale.
        for bad in ("200", [1], -5, True, {"n": 1}):
            with self.subTest(bad=bad):
                entry = self.answer(90_000)
                entry["message"]["usage"]["cache_read_input_tokens"] = bad
                path = self.transcript([self.answer(50_000), entry])
                self.assertIsNone(window.read_usage(path))

    def test_a_missing_field_counts_as_zero(self):
        entry = self.answer(90_000)
        del entry["message"]["usage"]["input_tokens"]
        entry["message"]["usage"]["cache_creation_input_tokens"] = None
        path = self.transcript([entry])
        self.assertEqual(window.read_usage(path).tokens,
                         entry["message"]["usage"]["cache_read_input_tokens"])

    def test_an_answer_behind_a_huge_last_line_is_still_found(self):
        # Real case: a tool result of 123 KB as the final line. The tail starts
        # mid-line somewhere before it and that fragment must be dropped whole.
        huge = {"type": "user", "toolUseResult": "x" * 150_000}
        filler = [{"type": "user", "pad": "y" * 1000}] * 300
        path = self.transcript(filler + [self.answer(90_000), huge])
        self.assertEqual(window.read_usage(path).tokens, 90_000)

    def test_an_answer_behind_results_bigger_than_the_tail_is_found(self):
        # Real case: a turn that read images. Each result is one line of up to
        # 1.4 MB, more than the whole first read, and a batch of them sits
        # between the answer and the end -- 44 Stops of one session read blind.
        image = {"type": "user", "toolUseResult": "x" * 1_400_000}
        path = self.transcript([self.answer(90_000)] + [image] * 3)
        self.assertEqual(window.read_usage(path).tokens, 90_000)

    def test_the_tail_stops_growing_at_its_cap(self):
        # A limitation on purpose: an answer that far from the end means nothing
        # happened lately, and reading 40 MB on every turn is the cost avoided.
        filler = [{"type": "user", "pad": "y" * 1000}] * 20
        path = self.transcript([self.answer(90_000)] + filler)
        with mock.patch.object(window, "TAIL_BYTES", 4096), \
                mock.patch.object(window, "MAX_TAIL_BYTES", 16_384):
            self.assertIsNone(window.read_usage(path))

    def test_the_identity_names_the_window_the_answer_does_not(self):
        # message.model says claude-opus-5-5 in a 1M session; only the identity
        # attachment carries the suffix.
        path = self.transcript([self.identity("claude-opus-5-5[1m]"),
                                self.answer(90_000, model="claude-opus-5-5")])
        self.assertEqual(window.read_usage(path).model, "claude-opus-5-5[1m]")

    def test_without_an_identity_the_answering_model_is_used(self):
        path = self.transcript([self.answer(90_000, model="claude-sonnet-4-6")])
        self.assertEqual(window.read_usage(path).model, "claude-sonnet-4-6")

    def test_an_identity_for_another_model_loses_to_the_one_answering(self):
        # A /model switch mid-session: the identity is the old model's, and
        # trusting its [1m] would size a 200k session as 1M -- the silent case.
        path = self.transcript([
            self.identity("claude-sonnet-4-6[1m]"),
            self.answer(90_000, model="claude-haiku-4-5-20251001")])
        self.assertEqual(window.read_usage(path).model, "claude-haiku-4-5-20251001")

    def test_the_identity_is_found_at_the_head_of_a_long_transcript(self):
        filler = [{"type": "user", "pad": "y" * 1000}] * 20
        path = self.transcript([self.identity("claude-sonnet-4-6[1m]")] + filler
                               + [self.answer(90_000, model="claude-sonnet-4-6")])
        with mock.patch.object(window, "TAIL_BYTES", 4096):
            self.assertEqual(window.read_usage(path).model, "claude-sonnet-4-6[1m]")


class TestModelWindow(unittest.TestCase):
    def test_the_table(self):
        # The frontier does not follow the family: within Opus it moves at 4.7,
        # within Sonnet at 5. These are the rows people guess wrong.
        cases = {
            "claude-opus-5-5": 1_000_000,
            "claude-opus-4-7": 1_000_000,
            "claude-opus-4-6": 200_000,
            "claude-sonnet-5": 1_000_000,
            "claude-sonnet-4-6": 200_000,
            "claude-fable-5-1": 1_000_000,
        }
        for model, expected in cases.items():
            with self.subTest(model=model):
                self.assertEqual(window.model_window(model), expected)

    def test_the_suffix_opens_a_200k_model_to_1m(self):
        self.assertEqual(window.model_window("claude-sonnet-4-6[1m]"), 1_000_000)

    def test_the_suffix_changes_nothing_on_a_native_1m_model(self):
        self.assertEqual(window.model_window("claude-opus-5-5[1m]"), 1_000_000)

    def test_a_dated_id_is_its_model(self):
        self.assertEqual(window.model_window("claude-haiku-4-5-20251001"), 200_000)

    def test_an_unknown_model_is_zero_not_a_neighbour(self):
        # Prefix matching would read a future opus-4-10 as opus-4-1.
        for model in ("claude-opus-4-10", "claude-future-9", "", None, "gpt-5"):
            with self.subTest(model=model):
                self.assertEqual(window.model_window(model), 0)


class TestSnapUp(unittest.TestCase):
    def test_rounds_up_to_a_real_window_size(self):
        cases = {150_000: 200_000, 200_000: 200_000, 210_000: 1_000_000,
                 673_678: 1_000_000, 1_200_000: 2_000_000, 2_500_000: 3_000_000}
        for seen, expected in cases.items():
            with self.subTest(seen=seen):
                self.assertEqual(window.snap_up(seen), expected)


class TestCalibrate(unittest.TestCase):
    def test_a_bigger_observation_raises_the_mark(self):
        seen, changed = window.calibrate({"m": 100_000}, "m", 300_000)
        self.assertEqual(seen, {"m": 300_000})
        self.assertTrue(changed)

    def test_a_smaller_observation_never_lowers_it(self):
        seen, changed = window.calibrate({"m": 300_000}, "m", 100_000)
        self.assertEqual(seen, {"m": 300_000})
        self.assertFalse(changed)

    def test_incredible_figures_are_ignored(self):
        for tokens in (5, window.MAX_CREDIBLE + 1):
            with self.subTest(tokens=tokens):
                self.assertEqual(window.calibrate({}, "m", tokens), ({}, False))

    def test_each_model_keeps_its_own_mark(self):
        seen, _ = window.calibrate({"a[1m]": 800_000}, "a", 150_000)
        self.assertEqual(seen, {"a[1m]": 800_000, "a": 150_000})

    def test_the_input_is_not_mutated(self):
        before = {"m": 100_000}
        window.calibrate(before, "m", 300_000)
        self.assertEqual(before, {"m": 100_000})

    def test_a_corrupt_record_is_replaced_not_trusted(self):
        seen, changed = window.calibrate({"m": "lots"}, "m", 300_000)
        self.assertEqual(seen, {"m": 300_000})
        self.assertTrue(changed)


class TestResolveBudget(unittest.TestCase):
    MODEL = "claude-opus-5-5"   # 1M in the table

    def resolve(self, **kw):
        kw.setdefault("seen", 0)
        kw.setdefault("env", {})
        return window.resolve_budget(kw.pop("model", self.MODEL), **kw)

    def test_the_real_window_variable_wins(self):
        env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "400000",
               "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000"}
        self.assertEqual(self.resolve(env=env, budget_tokens=250_000,
                                      settings_window=220_000), (400_000, "env"))

    def test_then_the_compaction_window(self):
        env = {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000"}
        self.assertEqual(self.resolve(env=env, budget_tokens=250_000),
                         (300_000, "env"))

    def test_then_baton_config(self):
        self.assertEqual(self.resolve(budget_tokens=250_000, settings_window=220_000),
                         (250_000, "config"))

    def test_then_claude_code_settings(self):
        self.assertEqual(self.resolve(settings_window=220_000), (220_000, "settings"))

    def test_then_the_model_table(self):
        self.assertEqual(self.resolve(), (1_000_000, "model"))

    def test_an_unknown_model_starts_at_the_default(self):
        self.assertEqual(self.resolve(model="claude-future-9"),
                         (window.DEFAULT_WINDOW, "default"))

    def test_nonsense_in_the_environment_is_skipped(self):
        # "²" passes str.isdigit() and then makes int() raise.
        for bad in ("abc", "0", "-5", "99999999999", "", "1e6", "²", "2²0000"):
            with self.subTest(bad=bad):
                env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": bad}
                self.assertEqual(self.resolve(env=env), (1_000_000, "model"))

    def test_an_observation_beyond_the_declared_size_wins(self):
        # 673,678 tokens were really seen in a session whose model id said
        # nothing about its window: that is proof the window is at least that.
        self.assertEqual(self.resolve(model="claude-future-9", seen=673_678),
                         (1_000_000, "calibrated"))

    def test_an_observation_never_lowers_the_budget(self):
        self.assertEqual(self.resolve(seen=150_000), (1_000_000, "model"))


class TestReading(unittest.TestCase):
    def test_percent_rounds_like_the_statusline(self):
        r = window.Reading(True, tokens=231_400, model="m", budget=1_000_000, source="model")
        self.assertEqual(r.percent, 23)

    def test_unknown_is_zero(self):
        self.assertEqual(window.UNKNOWN.percent, 0)
        self.assertFalse(window.UNKNOWN.at_least(1))

    def test_at_least_is_exact_at_the_edge(self):
        r = window.Reading(True, tokens=650_000, model="m", budget=1_000_000, source="model")
        self.assertTrue(r.at_least(65))
        self.assertFalse(r.at_least(66))


class TestTierReached(unittest.TestCase):
    def reading(self, percent):
        return window.Reading(True, tokens=percent * 10_000, model="m",
                              budget=1_000_000, source="model")

    def tier(self, percent, fired=(), min_tokens=0):
        return window.tier_reached(self.reading(percent), [65, 85], fired, min_tokens)

    def test_below_the_first_threshold_nothing(self):
        self.assertIsNone(self.tier(64))

    def test_on_the_threshold_it_fires(self):
        self.assertEqual(self.tier(65), 65)

    def test_past_both_it_is_the_highest(self):
        # A session resumed at 88% must be interrupted once, not twice.
        self.assertEqual(self.tier(88), 85)

    def test_a_consumed_tier_stays_quiet(self):
        self.assertIsNone(self.tier(70, fired=[65]))

    def test_the_next_tier_still_fires(self):
        self.assertEqual(self.tier(86, fired=[65]), 85)

    def test_everything_consumed(self):
        self.assertIsNone(self.tier(95, fired=[65, 85]))

    def test_below_the_token_floor_nothing(self):
        # A budget set absurdly low would read as 100% on a tiny session.
        self.assertIsNone(self.tier(90, min_tokens=1_000_000))

    def test_unknown_never_fires(self):
        self.assertIsNone(window.tier_reached(window.UNKNOWN, [65, 85], [], 0))


class TestSettingsWindow(BaseCase):
    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data),
                        encoding="utf-8")

    def setUp(self):
        super().setUp()
        self.home = self.project / "home"

    def test_nothing_configured_is_zero(self):
        self.assertEqual(window.settings_window(self.project, self.home), 0)

    def test_local_beats_project_beats_user(self):
        self.write(self.home / ".claude" / "settings.json", {"autoCompactWindow": 300_000})
        self.assertEqual(window.settings_window(self.project, self.home), 300_000)
        self.write(self.project / ".claude" / "settings.json", {"autoCompactWindow": 400_000})
        self.assertEqual(window.settings_window(self.project, self.home), 400_000)
        self.write(self.project / ".claude" / "settings.local.json",
                   {"autoCompactWindow": 500_000})
        self.assertEqual(window.settings_window(self.project, self.home), 500_000)

    def test_garbage_is_ignored(self):
        self.write(self.home / ".claude" / "settings.json", {"autoCompactWindow": 300_000})
        for bad in ("{broken", [1, 2], {"autoCompactWindow": "auto"},
                    {"autoCompactWindow": True}, {"autoCompactWindow": -1}):
            with self.subTest(bad=bad):
                self.write(self.project / ".claude" / "settings.json", bad)
                self.assertEqual(window.settings_window(self.project, self.home), 300_000)


class TestAssess(BaseCase):
    def test_a_real_shaped_session(self):
        path = self.transcript([self.identity("claude-opus-5-5[1m]"),
                                self.answer(231_000, model="claude-opus-5-5")])
        reading, seen, changed = window.assess(path, seen={}, env={})
        # The figure Miguel's statusline painted for this very model: 231k/1000k.
        self.assertEqual((reading.tokens, reading.budget, reading.percent),
                         (231_000, 1_000_000, 23))
        self.assertEqual(reading.source, "model")
        self.assertEqual(seen, {"claude-opus-5-5[1m]": 231_000})
        self.assertTrue(changed)

    def test_unknown_leaves_the_calibration_alone(self):
        reading, seen, changed = window.assess(self.project / "none.jsonl",
                                               seen={"m": 5}, env={})
        self.assertFalse(reading.known)
        self.assertEqual(seen, {"m": 5})
        self.assertFalse(changed)

    def test_the_first_answer_past_a_wrong_guess_corrects_it(self):
        path = self.transcript([self.answer(450_000, model="claude-future-9")])
        reading, _, _ = window.assess(path, seen={}, env={})
        self.assertEqual((reading.budget, reading.source), (1_000_000, "calibrated"))


if __name__ == "__main__":
    unittest.main()
