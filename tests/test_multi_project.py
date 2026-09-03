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


class TestAutomaticCycle(Base):
    def compact(self, **extra):
        return self.run_hook("post-compact", self.payload(
            "PostCompact", compact_summary="a summary", trigger="auto", **extra))

    def stop(self, **extra):
        return self.run_hook("stop", self.payload("Stop", stop_hook_active=False, **extra))

    def activate(self, rel):
        found = projects.discover(self.project)
        target = [p for p in found.projects if p.rel == rel][0]
        projects.set_active(self.project, target, session="test-session")
        return self.project / rel

    def test_the_summary_lands_in_the_active_project(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        radar = self.activate("proyectos/radar")
        self.compact()
        self.assertTrue(any((radar / ".baton" / "local" / "auto").glob("summary-*.md")))
        self.assertFalse((self.project / ".baton" / "local" / "auto").exists())

    def test_stop_asks_and_names_the_active_project(self):
        self.sub("proyectos/radar")
        self.activate("proyectos/radar")
        self.compact()
        _, out, _ = self.stop()
        self.assertEqual(out["decision"], "block")
        self.assertIn("radar", out["reason"])

    def test_with_no_active_project_and_no_root_document_it_stays_quiet(self):
        # Interrupting with a question the hook cannot answer on its own is
        # worse than saying nothing.
        self.sub("proyectos/radar")
        self.compact()
        _, out, _ = self.stop()
        self.assertIsNone(out)

    def test_a_single_project_root_still_gets_asked(self):
        self.handoff(self.project)
        self.compact()
        _, out, _ = self.stop()
        self.assertEqual(out["decision"], "block")


class TestLoad(Base):
    def setUp(self):
        super().setUp()
        self.sub("proyectos/radar", body="## State\ncanary xylophone-7731\n")
        self.sub("proyectos/instrumentos")

    def test_it_prints_the_handoff_with_its_wrapper(self):
        p = self.cli("load", "radar")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("xylophone-7731", p.stdout)
        self.assertIn("MEMORY MODE", p.stdout)
        self.assertIn("baton-handoff", p.stdout)

    def test_it_marks_the_project_as_active(self):
        self.cli("load", "radar")
        found = projects.discover(self.project)
        self.assertEqual(projects.read_active(self.project, found).rel, "proyectos/radar")

    def test_an_exact_name_beats_a_substring(self):
        # With `radar` and `radar-dos`, typing "radar" is not ambiguous: it names
        # one of them exactly. Treating it as ambiguous would make a project
        # unreachable by its own name.
        self.sub("proyectos/radar-dos")
        p = self.cli("load", "radar")
        self.assertEqual(p.returncode, 0, p.stderr)
        found = projects.discover(self.project)
        self.assertEqual(projects.read_active(self.project, found).rel, "proyectos/radar")

    def test_an_ambiguous_name_loads_nothing(self):
        self.sub("proyectos/radar-dos")
        p = self.cli("load", "rada")
        self.assertEqual(p.returncode, 3)
        self.assertIn("radar-dos", p.stderr)
        found = projects.discover(self.project)
        self.assertIsNone(projects.read_active(self.project, found))

    def test_an_unknown_name_lists_what_exists(self):
        p = self.cli("load", "nada")
        self.assertEqual(p.returncode, 3)
        self.assertIn("instrumentos", p.stderr)

    def test_loading_the_root_clears_the_activation(self):
        self.handoff(self.project)
        self.cli("load", "radar")
        p = self.cli("load", ".")
        self.assertEqual(p.returncode, 0, p.stderr)
        found = projects.discover(self.project)
        self.assertIsNone(projects.read_active(self.project, found))

    def test_freshness_only_counts_commits_that_touched_this_project(self):
        # Spec 8: `git -C <project>` with the pathspec `.` scopes the count to
        # that folder. Without it, in a monorepo every project's handoff would
        # look stale the moment any other project got a commit -- and a notice
        # that always fires is one the model learns to ignore.
        self.init_git()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "todo")
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        radar_doc = self.project / "proyectos" / "radar" / ".baton" / "HANDOFF.md"
        radar_doc.write_text(radar_doc.read_text(encoding="utf-8").replace(
            "commit: abc1234", f"commit: {head}"), encoding="utf-8")
        (self.project / "proyectos" / "instrumentos" / "otro.txt").write_text(
            "cambio ajeno\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "cambio en el otro proyecto")

        p = self.cli("load", "radar")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("new commits", p.stdout)

    def test_the_second_load_says_it_is_a_repeat(self):
        self.cli("load", "radar")
        p = self.cli("load", "radar")
        self.assertIn("already been delivered", p.stdout)


if __name__ == "__main__":
    import unittest
    unittest.main()
