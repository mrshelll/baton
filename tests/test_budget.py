"""The budget: keeping the handoff from growing, enforced by code.

The ceiling is not a preference. `additionalContext` truncates at 8,000
characters or 200 lines, whichever comes first, and silently. The defaults are
derived backwards from there.
"""
import sys
import unittest

from tests.helpers import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))
from lib import budget, output  # noqa: E402

S = output.load_strings("en")


class TestEstimateTokens(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(budget.estimate_tokens(""), 0)
        self.assertEqual(budget.estimate_tokens(None), 0)

    def test_golden_does_not_drift(self):
        # Pinning a range stops a refactor from silently changing the figure
        # reported back to the user.
        text = ("Migrating the charge from Stripe Charges to PaymentIntents. "
                "src/pagos.ts already uses PaymentIntents on the happy path.\n") * 10
        self.assertTrue(180 <= budget.estimate_tokens(text) <= 400,
                        budget.estimate_tokens(text))

    def test_takes_the_larger_of_the_two_formulas(self):
        # Short-word text (lists, paths, code) is where dividing by characters
        # underestimates, so the word count has to be able to win.
        short_words = "a b c " * 400          # 2400 chars, 1200 words
        long_words = "internationalisation " * 120  # few words, many chars
        self.assertGreaterEqual(budget.estimate_tokens(short_words), 1200 * 1.3 - 1)
        self.assertGreaterEqual(budget.estimate_tokens(long_words), len(long_words) / 3.6 - 1)


class TestMeasure(unittest.TestCase):
    def test_short_document_passes(self):
        m = budget.measure("---\nbaton: 1\n---\n\n## State\nshort\n")
        self.assertLess(m.lines, 20)
        self.assertGreater(m.characters, 0)

    def test_empty_does_not_divide_by_zero(self):
        m = budget.measure("")
        self.assertEqual((m.lines, m.characters, m.tokens), (0, 0, 0))

    def test_counts_real_lines(self):
        self.assertEqual(budget.measure("a\nb\nc\n").lines, 3)
        self.assertEqual(budget.measure("a\nb\nc").lines, 3)


class TestVerdict(unittest.TestCase):
    def limits(self, **kw):
        base = dict(budget.DEFAULT_LIMITS)
        base.update(kw)
        return base

    def test_within_budget(self):
        v = budget.evaluate("## State\nbrief\n", self.limits())
        self.assertTrue(v.fits)
        self.assertEqual(v.excess, {})

    def test_too_many_lines(self):
        v = budget.evaluate("x\n" * 147, self.limits(lines=120))
        self.assertFalse(v.fits)
        self.assertEqual(v.excess["lines"], 27)

    def test_few_lines_but_too_many_characters(self):
        # A long paragraph fits in few lines and still does not get in: that is
        # why `characters` is the binding measure, not `lines`.
        v = budget.evaluate("word " * 2000, self.limits())
        self.assertFalse(v.fits)
        self.assertIn("characters", v.excess)
        self.assertNotIn("lines", v.excess)

    def test_defaults_fit_under_the_harness_ceiling(self):
        t = budget.DEFAULT_LIMITS
        self.assertLessEqual(t["characters"] + budget.WRAPPER_RESERVE_CHARACTERS,
                             budget.CEILING_CHARACTERS)
        self.assertLessEqual(t["lines"] + budget.WRAPPER_RESERVE_LINES, budget.CEILING_LINES)

    def test_custom_limits_are_honoured(self):
        v = budget.evaluate("x\n" * 80, self.limits(lines=60))
        self.assertEqual(v.excess["lines"], 20)


class TestReport(unittest.TestCase):
    BODY = ("## State\n" + "s\n" * 40 +
            "## Decisions and why\n" + "d\n" * 61 +
            "## Traps\n" + "t\n" * 27)

    def report(self, attempt=1):
        v = budget.evaluate(self.BODY, budget.DEFAULT_LIMITS)
        return budget.report(v, self.BODY, attempt, 3, S)

    def test_points_at_the_biggest_section(self):
        text = self.report()
        self.assertIn("Decisions and why", text)
        self.assertIn("<--", text)

    def test_says_nothing_was_written(self):
        self.assertIn("Nothing has been written", self.report())

    def test_shows_the_attempt_counter(self):
        self.assertIn("Attempt 2 of 3", self.report(attempt=2))


class TestHonestTrim(unittest.TestCase):
    def test_cuts_on_whole_lines_never_mid_sentence(self):
        text = "first line and long\nsecond line also long\nthird line\n"
        out, trimmed = budget.trim_to_lines(text, max_characters=30, max_lines=99)
        self.assertTrue(trimmed)
        self.assertLessEqual(len(out), 30)
        for line in out.split("\n"):
            if line:
                self.assertIn(line, text, "no line may be left split")

    def test_does_not_trim_what_already_fits(self):
        out, trimmed = budget.trim_to_lines("short\n", 1000, 100)
        self.assertFalse(trimmed)
        self.assertEqual(out, "short\n")

    def test_also_trims_by_line_count(self):
        out, trimmed = budget.trim_to_lines("".join(f"l{i}\n" for i in range(50)), 100000, 10)
        self.assertTrue(trimmed)
        self.assertLessEqual(len([l for l in out.split("\n") if l]), 10)


if __name__ == "__main__":
    unittest.main()
