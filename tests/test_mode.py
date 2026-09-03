"""The mode regex: the piece baton's differentiator hangs from.

One rule: on ANY doubt, `memory`. An ambiguous document must never cause the new
session to start on its own and touch work nobody asked for.
"""
import sys
import time
import unittest

from tests.helpers import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))
from lib import document  # noqa: E402

HEAD = "---\nbaton: 1\n{}\ndate: 2026-09-03T00:00:00Z\nbranch: main\ncommit: abc1234\n---\n"


def doc(mode_line, body="\n## State\nsomething\n"):
    return HEAD.format(mode_line) + body


class TestReadMode(unittest.TestCase):
    def test_valid_values(self):
        for value in ("continue", "memory"):
            with self.subTest(value=value):
                self.assertEqual(document.read_mode(doc(f"mode: {value}")), value)

    def test_tolerates_spaces_and_tabs(self):
        for text in ("mode:continue", "mode:   continue   ", "mode:\tcontinue"):
            with self.subTest(text=text):
                self.assertEqual(document.read_mode(doc(text)), "continue")

    def test_casing_does_not_count(self):
        for text in ("mode: CONTINUE", "mode: Continue"):
            with self.subTest(text=text):
                self.assertEqual(document.read_mode(doc(text)), "memory")

    def test_near_miss_values(self):
        for text in ("mode: continues", "mode: continue extra", "mode: cont"):
            with self.subTest(text=text):
                self.assertEqual(document.read_mode(doc(text)), "memory")

    def test_no_frontmatter(self):
        self.assertEqual(document.read_mode("## State\nhi\n"), "memory")

    def test_unclosed_frontmatter(self):
        self.assertEqual(document.read_mode("---\nbaton: 1\nmode: continue\n"), "memory")

    def test_empty_file(self):
        self.assertEqual(document.read_mode(""), "memory")

    def test_mode_in_the_body_does_not_count(self):
        # Only the frontmatter rules. A body discussing "mode: continue" cannot
        # change how the next session behaves.
        text = doc("mode: memory", body="\n## State\nwe discussed mode: continue here\n")
        self.assertEqual(document.read_mode(text), "memory")

    def test_supports_crlf(self):
        self.assertEqual(document.read_mode(doc("mode: continue").replace("\n", "\r\n")),
                         "continue")

    def test_huge_document_is_fast(self):
        # Only the head of the file is read: a 1 MB doc cannot cost anything on
        # every session start.
        huge = doc("mode: continue") + ("x" * 1_000_000)
        t0 = time.perf_counter()
        self.assertEqual(document.read_mode(huge), "continue")
        self.assertLess(time.perf_counter() - t0, 0.05)

    def test_non_utf8_bytes_do_not_raise(self):
        self.assertEqual(document.read_mode("\udcff\udcfe garbage"), "memory")

    def test_odd_types(self):
        for value in (None, 123, [], {}):
            with self.subTest(value=value):
                self.assertEqual(document.read_mode(value), "memory")

    def test_future_version_keeps_the_mode_but_is_flagged(self):
        text = doc("mode: continue").replace("baton: 1", "baton: 2")
        self.assertEqual(document.read_mode(text), "continue")
        self.assertEqual(document.read_version(text), 2)

    def test_missing_version_is_none(self):
        self.assertIsNone(document.read_version("## State\nx\n"))


if __name__ == "__main__":
    unittest.main()
