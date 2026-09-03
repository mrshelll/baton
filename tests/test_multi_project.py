"""A root that holds several projects: what the session receives, and where the
handoff ends up."""
import json
import os
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


class TestWriteTarget(Base):
    def draft(self, where, text="## State\nwhere we are, concretely\n"):
        d = where / ".baton" / "local"
        d.mkdir(parents=True, exist_ok=True)
        (d / "draft.md").write_text(text, encoding="utf-8")

    def test_it_writes_into_the_active_project(self):
        radar = self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        self.cli("load", "radar")
        self.draft(radar)
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(str(radar), p.stdout)
        self.assertIn("where we are, concretely",
                      (radar / ".baton" / "HANDOFF.md").read_text(encoding="utf-8"))

    def test_with_projects_and_none_active_it_refuses_and_lists_them(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        self.draft(self.project)
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, 3)
        self.assertIn("radar", p.stderr)
        self.assertIn("instrumentos", p.stderr)

    def test_an_explicit_project_bootstraps_a_folder_with_no_handoff(self):
        self.sub("proyectos/radar")
        nuevo = self.project / "proyectos" / "nuevo"
        nuevo.mkdir(parents=True)
        self.draft(nuevo)
        p = self.cli("write", "--mode", "memory", "--project", "proyectos/nuevo")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((nuevo / ".baton" / "HANDOFF.md").is_file())

    def test_a_typo_does_not_found_a_project_in_a_folder_nobody_made(self):
        self.sub("proyectos/radar")
        self.draft(self.project)
        p = self.cli("write", "--mode", "memory", "--project", "proyectos/nuevoo")
        self.assertEqual(p.returncode, 3)
        self.assertFalse((self.project / "proyectos" / "nuevoo").exists())

    def test_a_single_project_root_is_unaffected(self):
        self.draft(self.project)
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.project / ".baton" / "HANDOFF.md").is_file())

    def test_context_reports_the_target_project(self):
        radar = self.sub("proyectos/radar")
        self.cli("load", "radar")
        p = self.cli("context")
        self.assertIn(str(radar), p.stdout)


class TestColdStart(Base):
    """The two failures the manual acceptance run in SECOP found.

    A session opened INSIDE a project folder, under a root that is a root only
    because it has `.claude`, with no handoff anywhere yet.
    """

    def deep_cli(self, where, *args):
        """Like self.cli, but standing in `where` -- the whole point here is
        that the session's directory is not the root."""
        import subprocess
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "baton.py"), *args],
            capture_output=True, text=True, cwd=str(where), timeout=60,
            env={**os.environ, "LC_ALL": "C"})

    def setUp(self):
        super().setUp()
        (self.project / ".claude").mkdir(exist_ok=True)
        self.radar = self.project / "proyectos" / "radar-licitaciones-secop"
        self.radar.mkdir(parents=True)
        (self.project / "proyectos" / "instrumentos-control").mkdir(parents=True)

    def draft(self, where):
        d = where / ".baton" / "local"
        d.mkdir(parents=True, exist_ok=True)
        (d / "draft.md").write_text("## State\ntrabajo del radar\n", encoding="utf-8")

    def test_project_can_be_named_by_its_folder_name(self):
        # `--project proyectos/radar-licitaciones-secop` worked, the bare name
        # did not -- while the index and `load` both take the name. That
        # contradiction is what blocked the first real session.
        self.draft(self.radar)
        p = self.cli("write", "--mode", "memory", "--project", "radar-licitaciones-secop")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.radar / ".baton" / "HANDOFF.md").is_file())

    def test_an_ambiguous_folder_name_creates_nothing(self):
        (self.project / "otros" / "radar-licitaciones-secop").mkdir(parents=True)
        self.draft(self.project)
        p = self.cli("write", "--mode", "memory", "--project", "radar-licitaciones-secop")
        self.assertEqual(p.returncode, 3)
        self.assertIn("otros/radar-licitaciones-secop", p.stderr)
        self.assertFalse((self.radar / ".baton" / "HANDOFF.md").exists())

    def test_a_cold_start_from_inside_a_subfolder_asks(self):
        # It used to claim the root in silence, which is how SECOP ended up with
        # a .baton/ that had to be deleted by hand.
        self.draft(self.project)
        p = self.deep_cli(self.radar, "write", "--mode", "memory")
        self.assertEqual(p.returncode, 3)
        self.assertIn("proyectos/radar-licitaciones-secop", p.stderr)
        self.assertIn("--project .", p.stderr)
        self.assertFalse((self.project / ".baton" / "HANDOFF.md").exists())

    def test_context_asks_too_so_the_question_comes_before_the_drafting(self):
        p = self.deep_cli(self.radar, "context")
        self.assertEqual(p.returncode, 3)
        self.assertIn("--project", p.stderr)

    def test_at_the_root_itself_it_still_writes_without_asking(self):
        self.draft(self.project)
        p = self.deep_cli(self.project, "write", "--mode", "memory")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.project / ".baton" / "HANDOFF.md").is_file())

    def test_with_the_root_already_enabled_a_subfolder_writes_to_the_root(self):
        # Nothing to ask here: the root's handoff exists, so that is where a
        # session below it belongs. This is the ordinary repo case and it must
        # not have grown a question.
        self.handoff(self.project)
        self.draft(self.project)
        p = self.deep_cli(self.radar, "write", "--mode", "memory")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("trabajo del radar",
                      (self.project / ".baton" / "HANDOFF.md").read_text(encoding="utf-8"))


class TestDoctor(Base):
    def test_it_lists_the_projects_and_the_active_one(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        self.cli("load", "radar")
        p = self.cli("doctor")
        self.assertIn("proyectos/radar", p.stdout)
        self.assertIn("proyectos/instrumentos", p.stdout)
        self.assertIn("active", p.stdout.lower())

    def test_it_says_how_deep_it_looked(self):
        p = self.cli("doctor")
        self.assertIn("depth 2", p.stdout)

    def test_it_warns_when_the_scan_hit_its_cap(self):
        (self.project / ".claude").mkdir(exist_ok=True)
        (self.project / ".claude" / "baton.json").write_text(
            '{"discovery": {"max_dirs": 50}}', encoding="utf-8")
        for i in range(60):
            (self.project / f"vacia{i}").mkdir()
        p = self.cli("doctor")
        self.assertIn("limit", p.stdout.lower())


if __name__ == "__main__":
    import unittest
    unittest.main()
