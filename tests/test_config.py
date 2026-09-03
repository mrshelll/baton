"""Config: global plus project, key-by-key precedence and readable failure."""
import json
import sys
import unittest

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import config  # noqa: E402


class TestLoad(BaseCase):
    def write(self, which, data):
        if which == "global":
            path = self.project / "global-baton.json"
        else:
            (self.project / ".claude").mkdir(exist_ok=True)
            path = self.project / ".claude" / "baton.json"
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return path

    def load(self, global_path=None):
        return config.load(self.project, global_path=global_path)

    def test_no_files_gives_the_defaults(self):
        c = self.load()
        self.assertEqual(c["limits"], config.DEFAULTS["limits"])
        self.assertEqual(c.warnings, [])

    def test_project_beats_global(self):
        g = self.write("global", {"limits": {"lines": 90}})
        self.write("project", {"limits": {"lines": 200}})
        self.assertEqual(self.load(g)["limits"]["lines"], 200)

    def test_overriding_one_limit_keeps_the_others(self):
        # One-level merge: touching `lines` cannot leave you without `characters`.
        self.write("project", {"limits": {"lines": 60}})
        c = self.load()
        self.assertEqual(c["limits"]["lines"], 60)
        self.assertEqual(c["limits"]["characters"], config.DEFAULTS["limits"]["characters"])

    def test_broken_json_warns_naming_the_file_and_carries_on(self):
        self.write("project", "{not json")
        c = self.load()
        self.assertEqual(c["limits"], config.DEFAULTS["limits"])
        self.assertTrue(any("baton.json" in w for w in c.warnings), c.warnings)

    def test_json_that_is_a_list_does_not_break(self):
        self.write("project", [1, 2, 3])
        self.assertTrue(self.load().warnings)

    def test_unknown_key_suggests_the_right_one(self):
        self.write("project", {"lines_max": 60})
        joined = " ".join(self.load().warnings)
        self.assertIn("lines_max", joined)
        self.assertIn("limits.lines", joined)

    def test_spanish_key_from_an_older_config_is_recognised(self):
        # baton spoke Spanish before 0.3.0; pointing at the new key beats an
        # unhelpful "unknown key".
        self.write("project", {"topes": {"lineas": 60}})
        joined = " ".join(self.load().warnings)
        self.assertIn("limits", joined)

    def test_absolute_document_path_is_rejected(self):
        self.write("project", {"document": "/etc/passwd"})
        c = self.load()
        self.assertEqual(c["document"], config.DEFAULTS["document"])
        self.assertTrue(any("outside the project" in w for w in c.warnings), c.warnings)

    def test_document_path_with_dotdot_is_rejected(self):
        self.write("project", {"document": "../../outside.md"})
        self.assertEqual(self.load()["document"], config.DEFAULTS["document"])

    def test_history_zero_disables_without_breaking(self):
        self.write("project", {"history_max": 0})
        self.assertEqual(self.load()["history_max"], 0)

    def test_non_numeric_limit_is_ignored_with_a_warning(self):
        self.write("project", {"limits": {"lines": "many"}})
        c = self.load()
        self.assertEqual(c["limits"]["lines"], config.DEFAULTS["limits"]["lines"])
        self.assertTrue(c.warnings)

    def test_true_is_not_a_valid_number(self):
        # bool subclasses int in Python; without the guard `True` would pass.
        self.write("project", {"limits": {"lines": True}})
        self.assertEqual(self.load()["limits"]["lines"], config.DEFAULTS["limits"]["lines"])

    def test_language_is_honoured(self):
        self.write("project", {"language": "es"})
        self.assertEqual(self.load()["language"], "es")

    def test_unknown_language_falls_back_and_lists_what_exists(self):
        self.write("project", {"language": "klingon"})
        c = self.load()
        self.assertEqual(c["language"], config.DEFAULTS["language"])
        self.assertTrue(any("available" in w for w in c.warnings), c.warnings)


class TestDiscoveryKey(BaseCase):
    def write_cfg(self, where, data):
        (where / ".claude").mkdir(parents=True, exist_ok=True)
        (where / ".claude" / "baton.json").write_text(json.dumps(data), encoding="utf-8")

    def load(self, where=None, parent=None):
        return config.load(where or self.project, global_path=self.project / "nope.json",
                           parent=parent)

    def test_the_default_is_depth_two(self):
        cfg = self.load()
        self.assertEqual(cfg["discovery"]["depth"], 2)
        self.assertEqual(cfg["discovery"]["max_dirs"], 400)

    def test_the_root_can_deepen_it(self):
        self.write_cfg(self.project, {"discovery": {"depth": 3}})
        cfg = self.load()
        self.assertEqual(cfg["discovery"]["depth"], 3)
        self.assertEqual(cfg["discovery"]["max_dirs"], 400)

    def test_an_absurd_depth_warns_and_falls_back(self):
        self.write_cfg(self.project, {"discovery": {"depth": 99}})
        cfg = self.load()
        self.assertEqual(cfg["discovery"]["depth"], 2)
        self.assertTrue(any("depth" in w for w in cfg.warnings))

    def test_a_subproject_inherits_the_root_and_overrides_what_is_its_own(self):
        sub = self.project / "proyectos" / "radar"
        sub.mkdir(parents=True)
        self.write_cfg(self.project, {"language": "es", "history_max": 3})
        self.write_cfg(sub, {"history_max": 5})
        cfg = self.load(sub, parent=self.project)
        self.assertEqual(cfg["language"], "es")
        self.assertEqual(cfg["history_max"], 5)

    def test_discovery_in_a_subproject_is_ignored_with_a_warning(self):
        sub = self.project / "proyectos" / "radar"
        sub.mkdir(parents=True)
        self.write_cfg(self.project, {"discovery": {"depth": 3}})
        self.write_cfg(sub, {"discovery": {"depth": 1}})
        cfg = self.load(sub, parent=self.project)
        self.assertEqual(cfg["discovery"]["depth"], 3)
        self.assertTrue(any("discovery" in w for w in cfg.warnings))


if __name__ == "__main__":
    unittest.main()
