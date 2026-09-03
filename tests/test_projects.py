"""Which project: discovery, name resolution and activation."""
import sys

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import projects  # noqa: E402


class Base(BaseCase):
    def make_project(self, rel):
        """A directory that qualifies: it has its own handoff."""
        d = self.project / rel
        (d / ".baton").mkdir(parents=True, exist_ok=True)
        (d / ".baton" / "HANDOFF.md").write_text(
            "---\nbaton: 1\nmode: memory\ndate: 2026-09-03T10:00:00-05:00\n"
            "branch: main\ncommit: abc1234\n---\n\n## State\nx\n", encoding="utf-8")
        return d


class TestDiscovery(Base):
    def test_no_projects_is_an_empty_discovery(self):
        found = projects.discover(self.project)
        self.assertEqual(found.projects, ())
        self.assertFalse(found)
        self.assertFalse(found.truncated)

    def test_finds_a_loose_folder_at_depth_one(self):
        self.make_project("radar")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects], ["radar"])
        self.assertEqual(found.projects[0].name, "radar")

    def test_finds_a_grouped_folder_at_depth_two(self):
        self.make_project("proyectos/radar")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects], ["proyectos/radar"])
        self.assertEqual(found.projects[0].name, "radar")

    def test_finds_both_shapes_mixed_in_one_root(self):
        self.make_project("suelto")
        self.make_project("proyectos/uno")
        self.make_project("proyectos/dos")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects],
                         ["proyectos/dos", "proyectos/uno", "suelto"])

    def test_depth_three_is_not_reached_by_default(self):
        self.make_project("a/b/c")
        self.assertEqual(projects.discover(self.project).projects, ())
        deeper = projects.discover(self.project, depth=3)
        self.assertEqual([p.rel for p in deeper.projects], ["a/b/c"])

    def test_a_found_project_is_not_descended_into(self):
        self.make_project("radar")
        self.make_project("radar/interno")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects], ["radar"])

    def test_hidden_and_heavy_folders_are_skipped(self):
        self.make_project(".oculto")
        self.make_project("node_modules/paquete")
        self.assertEqual(projects.discover(self.project).projects, ())

    def test_symlinked_directories_are_not_followed(self):
        target = self.make_project("real")
        link = self.project / "enlace"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("this filesystem does not allow symlinks")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects], ["real"])

    def test_the_cap_stops_the_scan_and_says_so(self):
        for i in range(10):
            (self.project / f"vacia{i}").mkdir()
        self.make_project("zzz-ultima")
        found = projects.discover(self.project, max_dirs=3)
        self.assertTrue(found.truncated)

    def test_a_custom_document_path_is_honoured(self):
        d = self.project / "otro"
        (d / "docs").mkdir(parents=True)
        (d / "docs" / "H.md").write_text("x", encoding="utf-8")
        found = projects.discover(self.project, document_rel="docs/H.md")
        self.assertEqual([p.rel for p in found.projects], ["otro"])

    def test_an_unreadable_root_returns_empty_instead_of_raising(self):
        found = projects.discover(self.project / "no-existe")
        self.assertEqual(found.projects, ())
