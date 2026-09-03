"""The README is the project's face: its diagrams have to be well formed.

A light, dependency-free check. The real validation, against the Mermaid parser
itself, lives in tools/validate-mermaid.mjs.
"""
import re
import unittest

from tests.helpers import REPO_ROOT

# Types GitHub renders. If you add a new one, validate it first with
# tools/validate-mermaid.mjs.
TYPES = ("flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram",
         "erDiagram", "journey", "gantt", "pie", "gitGraph", "mindmap", "timeline",
         "xychart-beta", "block-beta", "quadrantChart", "sankey-beta")

FILES = ("README.md", "README.es.md")


class TestReadme(unittest.TestCase):
    def each(self):
        for name in FILES:
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
            yield name, text, re.findall(r"```mermaid\n(.*?)```", text, re.DOTALL)

    def test_both_readmes_have_diagrams(self):
        for name, _, blocks in self.each():
            with self.subTest(file=name):
                self.assertGreaterEqual(len(blocks), 4)

    def test_every_block_closes(self):
        for name, text, blocks in self.each():
            with self.subTest(file=name):
                self.assertEqual(text.count("```mermaid"), len(blocks),
                                 "an unclosed mermaid block")

    def test_every_diagram_declares_a_known_type(self):
        for name, _, blocks in self.each():
            for i, block in enumerate(blocks, 1):
                with self.subTest(file=name, diagram=i):
                    first = block.strip().split("\n")[0].strip()
                    self.assertTrue(first.startswith(TYPES), f"unknown type: {first!r}")

    def test_code_fences_are_balanced(self):
        for name, text, _ in self.each():
            with self.subTest(file=name):
                self.assertEqual(text.count("```") % 2, 0, "an unpaired ``` fence")

    def test_both_mention_the_restart_after_installing(self):
        # It is the number one failure; if it leaves the README, it happens again.
        for name, text, _ in self.each():
            with self.subTest(file=name):
                self.assertTrue("Restart Claude Code" in text or "Reinicia Claude Code" in text)

    def test_the_two_readmes_link_to_each_other(self):
        self.assertIn("README.es.md", (REPO_ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("README.md", (REPO_ROOT / "README.es.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
