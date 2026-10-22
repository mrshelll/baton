"""Composing and measuring a handoff outside the CLI.

The PostCompact hook writes a handoff through the same path as `baton.py write`;
these tests pin what that shared path promises: it writes only a draft that is
valid and fits, and on any other outcome the previous handoff is left alone.
"""
import sys

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))

from lib import config, document, handoff, output, storage  # noqa: E402

S = output.load_strings("en")


class TestHandoff(BaseCase):
    def setUp(self):
        super().setUp()
        self.init_git()
        self.cfg = config.load(self.project, global_path=self.project / "no-global.json")
        self.paths = storage.Paths(self.project, document_rel=self.cfg["document"])

    def build(self, body, mode="memory"):
        return handoff.build(body, mode, self.project, self.cfg, S)

    def test_a_valid_body_is_written_in_its_mode(self):
        built = self.build("## State\nMigration to PaymentIntents half done.\n")
        self.assertEqual(handoff.write_if_fits(self.paths, built, self.cfg), "written")
        doc = self.paths.document.read_text(encoding="utf-8")
        self.assertEqual(document.read_mode(doc), "memory")
        self.assertIn("mode: memory", doc)
        self.assertIn("PaymentIntents", doc)
        self.assertEqual(doc, built.final)

    def test_a_body_without_the_required_section_is_invalid_and_writes_nothing(self):
        built = self.build("## Traps\nwatch out for X\n")
        self.assertFalse(built.parsed.valid)
        self.assertEqual(handoff.write_if_fits(self.paths, built, self.cfg), "invalid")
        self.assertFalse(self.paths.document.exists())

    def test_an_oversized_body_is_over_budget_and_the_previous_survives(self):
        handoff.write_if_fits(self.paths, self.build("## State\ngood\n"), self.cfg)
        before = self.paths.document.read_text(encoding="utf-8")
        built = self.build("## State\n" + "filler line\n" * 200)
        self.assertFalse(built.verdict.fits)
        self.assertEqual(handoff.write_if_fits(self.paths, built, self.cfg), "over_budget")
        self.assertEqual(self.paths.document.read_text(encoding="utf-8"), before,
                         "the previous handoff must survive")

    def test_a_busy_lock_is_reported_not_raised(self):
        self.paths.ensure_local()
        self.paths.lock.write_text("123", encoding="utf-8")  # fresh lock: someone else
        built = self.build("## State\nx\n")
        self.assertEqual(handoff.write_if_fits(self.paths, built, self.cfg), "busy")
        self.assertFalse(self.paths.document.exists())

    def test_an_unknown_mode_is_invalid_and_writes_nothing(self):
        built = self.build("## State\nx\n", mode="nope")
        self.assertEqual(handoff.write_if_fits(self.paths, built, self.cfg), "invalid")
        self.assertFalse(self.paths.document.exists())

    def test_build_does_not_write(self):
        built = self.build("## State\nx\n")
        self.assertTrue(built.verdict.fits)
        self.assertFalse(self.paths.document.exists())
        self.assertFalse(self.paths.local.exists())
