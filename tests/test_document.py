"""Validating the model's draft and composing the final file."""
import sys
import unittest

from tests.helpers import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))
from lib import document, output  # noqa: E402

S = output.load_strings("en")


class TestValidate(unittest.TestCase):
    def validate(self, body, mode="memory"):
        return document.validate_draft(body, mode=mode, strings=S)

    def test_state_alone_is_valid(self):
        self.assertTrue(self.validate("## State\nsomething concrete\n").valid)

    def test_missing_state(self):
        p = self.validate("## Traps\nwatch out for X\n")
        self.assertFalse(p.valid)
        self.assertTrue(any("State" in e for e in p.errors), p.errors)

    def test_unknown_section_lists_the_valid_ones(self):
        p = self.validate("## State\nx\n## Loose notes\ny\n")
        self.assertFalse(p.valid)
        joined = " ".join(p.errors)
        self.assertIn("Loose notes", joined)
        self.assertIn("Traps", joined)

    def test_filler_is_rejected_in_every_shape(self):
        for junk in ("none", "N/A", "-", "—", "nothing", "TBD", "not applicable"):
            with self.subTest(junk=junk):
                p = self.validate(f"## State\nx\n## Blockers\n{junk}\n")
                self.assertFalse(p.valid, junk)
                self.assertTrue(any("DELETE" in e for e in p.errors), p.errors)

    def test_empty_section_is_filler_too(self):
        self.assertFalse(self.validate("## State\nx\n## Blockers\n\n").valid)

    def test_continue_requires_next_step(self):
        p = self.validate("## State\nx\n", mode="continue")
        self.assertFalse(p.valid)
        self.assertTrue(any("Next step" in e for e in p.errors), p.errors)

    def test_continue_with_next_step_is_valid(self):
        self.assertTrue(self.validate(
            "## State\nx\n## Next step\ndo Y in z.py:10\n", mode="continue").valid)

    def test_memory_may_carry_next_step(self):
        # Allowed on purpose: the danger is neutralised in the injected text,
        # not by rejecting useful information.
        self.assertTrue(self.validate("## State\nx\n## Next step\nsomeday Y\n").valid)

    def test_labels_with_different_case_or_accents_are_accepted(self):
        self.assertTrue(self.validate("## state\nx\n## Decisions and why\nA because B\n").valid)

    def test_loose_text_before_the_first_section_is_rejected(self):
        self.assertFalse(self.validate("this is loose\n## State\nx\n").valid)

    def test_empty_draft_is_rejected(self):
        self.assertFalse(self.validate("").valid)

    def test_the_models_frontmatter_is_ignored(self):
        p = self.validate("---\nmode: continue\n---\n## State\nx\n")
        self.assertTrue(p.valid, p.errors)
        self.assertNotIn("mode:", p.body)


class TestCompose(unittest.TestCase):
    def compose(self, body="## State\nx\n", mode="memory", **kw):
        base = dict(body=body, mode=mode, date="2026-09-03T10:00:00-05:00",
                    branch="main", commit="abc1234",
                    context="- branch `main`, working tree clean", strings=S)
        base.update(kw)
        return document.compose(**base)

    def test_frontmatter_has_the_five_keys_in_order(self):
        header = self.compose().split("---")[1].strip().split("\n")
        self.assertEqual([l.split(":")[0] for l in header],
                         ["baton", "mode", "date", "branch", "commit"])

    def test_what_is_composed_reads_back(self):
        text = self.compose(mode="continue", body="## State\nx\n## Next step\ny\n")
        self.assertEqual(document.read_mode(text), "continue")
        self.assertEqual(document.read_version(text), document.VERSION)
        self.assertEqual(document.read_fields(text)["commit"], "abc1234")

    def test_carries_the_rewrite_warning(self):
        self.assertIn("REWRITTEN IN FULL", self.compose())

    def test_includes_the_git_context(self):
        self.assertIn("## Context", self.compose())
        self.assertIn("working tree clean", self.compose())

    def test_without_git_the_fields_say_so(self):
        self.assertEqual(document.read_fields(
            self.compose(branch="no-git", commit="no-git"))["branch"], "no-git")

    def test_extract_body_returns_what_the_model_wrote(self):
        text = self.compose(body="## State\nmy state\n")
        self.assertIn("my state", document.extract_body(text))
        self.assertNotIn("## Context", document.extract_body(text))

    def test_the_fingerprint_ignores_the_git_context(self):
        # Two handoffs with the same body and different git are the SAME
        # handoff: otherwise every commit would make it look like news.
        a = self.compose(context="- branch `main`, working tree clean")
        b = self.compose(context="- branch `other`, 9 uncommitted: x")
        self.assertEqual(document.fingerprint(a), document.fingerprint(b))

    def test_the_fingerprint_changes_with_the_body(self):
        self.assertNotEqual(document.fingerprint(self.compose(body="## State\none\n")),
                            document.fingerprint(self.compose(body="## State\ntwo\n")))


class TestSpanishStrings(unittest.TestCase):
    """The section labels are translatable; the mode enum is not."""

    def test_spanish_labels_validate(self):
        es = output.load_strings("es")
        p = document.validate_draft("## Estado\nalgo\n## Trampas\nojo\n",
                                    mode="memory", strings=es)
        self.assertTrue(p.valid, p.errors)

    def test_the_mode_enum_stays_english_in_every_language(self):
        es = output.load_strings("es")
        text = document.compose(body="## Estado\nx\n", mode="memory",
                                date="2026-09-03T10:00:00Z", branch="main",
                                commit="abc1234", context="- rama `main`", strings=es)
        self.assertIn("mode: memory", text)
        self.assertEqual(document.read_mode(text), "memory")


class TestExtractCompactionBlock(unittest.TestCase):
    """The block the summarizer appends after its summary, and nothing else."""

    SUMMARY = "<analysis>thinking</analysis>\n<summary>Stripe was migrated.</summary>\n"

    def block(self, body="## State\nStripe migrated; refunds left.\n", mode="memory"):
        return f'<{output.COMPACTION_TAG} mode="{mode}">\n{body}</{output.COMPACTION_TAG}>'

    def extract(self, text):
        return document.extract_compaction_block(text)

    def test_a_block_at_the_end(self):
        self.assertEqual(self.extract(self.SUMMARY + self.block() + "\n\n"),
                         ("memory", "## State\nStripe migrated; refunds left."))

    def test_the_mode_of_the_attribute_comes_back(self):
        found = self.extract(self.SUMMARY + self.block(mode="continue"))
        self.assertEqual(found[0], "continue")

    def test_two_blocks_give_the_last(self):
        # The first one quoted mid-summary -- the instruction itself, say.
        quoted = self.block(body="## State\n...\n")
        text = (self.SUMMARY + f"The user was told:\n{quoted}\nand carried on.\n"
                + self.block(body="## State\nthe real one\n"))
        self.assertEqual(self.extract(text), ("memory", "## State\nthe real one"))

    def test_an_unclosed_block_is_none(self):
        text = self.SUMMARY + f'<{output.COMPACTION_TAG} mode="memory">\n## State\ncut off'
        self.assertIsNone(self.extract(text))

    def test_text_after_the_close_is_none(self):
        self.assertIsNone(self.extract(self.SUMMARY + self.block() + "\nOne more thing."))

    def test_an_unknown_mode_is_none(self):
        for mode in ("otro", "Memory", ""):
            with self.subTest(mode=mode):
                self.assertIsNone(self.extract(self.SUMMARY + self.block(mode=mode)))

    def test_a_block_without_a_mode_is_none(self):
        text = (self.SUMMARY + f"<{output.COMPACTION_TAG}>\n## State\nx\n"
                f"</{output.COMPACTION_TAG}>")
        self.assertIsNone(self.extract(text))

    def test_a_stray_close_inside_the_last_block_is_none(self):
        # The last opening tag, then a close, then loose text, then another
        # close: what sits between them is not one block.
        text = self.SUMMARY + self.block().replace(
            "refunds left.\n", f"refunds left.\n</{output.COMPACTION_TAG}>\nloose\n")
        self.assertIsNone(self.extract(text))

    def test_crlf_and_trailing_blank_lines_are_tolerated(self):
        text = (self.SUMMARY + self.block() + "\r\n  \r\n").replace("\n", "\r\n")
        self.assertEqual(self.extract(text)[0], "memory")

    def test_garbage_is_none(self):
        for garbage in (None, "", "   ", 42, f"</{output.COMPACTION_TAG}>"):
            with self.subTest(garbage=garbage):
                self.assertIsNone(self.extract(garbage))


if __name__ == "__main__":
    unittest.main()
