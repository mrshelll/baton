"""A root that holds several projects: what the session receives, and where the
handoff ends up."""
import json
import sys

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import document, output, projects, storage  # noqa: E402

S = output.load_strings("en")


class Base(BaseCase):
    def handoff(self, where, mode="memory", body="## State\nx\n"):
        text = document.compose(body=body, mode=mode, date="2026-09-03T10:00:00-05:00",
                                branch="main", commit="abc1234",
                                context="- branch `main`, working tree clean", strings=S)
        paths = storage.Paths(where)
        paths.document.parent.mkdir(parents=True, exist_ok=True)
        paths.document.write_text(text, encoding="utf-8")
        return where

    def sub(self, rel, **kw):
        d = self.project / rel
        d.mkdir(parents=True, exist_ok=True)
        return self.handoff(d, **kw)

    def start(self, source="startup", **extra):
        return self.run_hook("session-start",
                             self.payload("SessionStart", source=source, **extra))

    def context(self, out):
        return out["hookSpecificOutput"]["additionalContext"]


class TestSessionStart(Base):
    def test_a_root_with_no_document_and_no_projects_stays_silent(self):
        rc, out, _ = self.start()
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_a_normal_project_is_unchanged(self):
        self.handoff(self.project, body="## State\ncanary xylophone-7731\n")
        _, out, _ = self.start()
        text = self.context(out)
        self.assertIn("xylophone-7731", text)
        self.assertNotIn("baton-index", text)

    def test_two_projects_and_no_root_document_inject_the_index(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        _, out, _ = self.start()
        text = self.context(out)
        self.assertIn("<baton-index", text)
        self.assertIn("radar", text)
        self.assertIn("instrumentos", text)
        self.assertIn("baton.py load", text)

    def test_the_index_does_not_carry_any_project_body(self):
        self.sub("proyectos/radar", body="## State\ncanary xylophone-7731\n")
        text = self.context(self.start()[1])
        self.assertNotIn("xylophone-7731", text)

    def test_the_mixed_case_carries_the_root_document_and_the_index(self):
        self.handoff(self.project, body="## State\ncanary xylophone-7731\n")
        self.sub("proyectos/radar")
        text = self.context(self.start()[1])
        self.assertIn("xylophone-7731", text)
        self.assertIn("<baton-index", text)
        self.assertLess(text.index("MEMORY MODE"), text.index("<baton-index"),
                        "the mode instruction has to come first: it survives any trim")

    def test_the_receipt_names_how_many_projects_are_available(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        _, out, _ = self.start()
        self.assertIn("2 project", out["systemMessage"])
        self.assertIn("none loaded", out["systemMessage"])

    def test_a_fresh_session_clears_the_active_project(self):
        self.sub("proyectos/radar")
        found = projects.discover(self.project)
        projects.set_active(self.project, found.projects[0], session="old")
        self.start(source="startup")
        self.assertIsNone(projects.read_active(self.project, found))

    def test_a_compaction_preserves_the_active_project(self):
        # Clearing here would drop the target exactly when the automatic cycle
        # is about to ask for the handoff.
        self.sub("proyectos/radar")
        found = projects.discover(self.project)
        projects.set_active(self.project, found.projects[0], session="s")
        self.start(source="compact")
        self.assertIsNotNone(projects.read_active(self.project, found))

    def test_the_activation_is_cleared_even_when_injection_is_disabled(self):
        self.sub("proyectos/radar")
        (self.project / ".claude").mkdir(exist_ok=True)
        (self.project / ".claude" / "baton.json").write_text(
            json.dumps({"inject_on": ["resume"]}), encoding="utf-8")
        found = projects.discover(self.project)
        projects.set_active(self.project, found.projects[0], session="old")
        self.start(source="startup")
        self.assertIsNone(projects.read_active(self.project, found))


if __name__ == "__main__":
    import unittest
    unittest.main()
