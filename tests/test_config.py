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


class TestContextWindow(BaseCase):
    """The automatic handoff by context usage: one block, validated key by key."""

    def load(self, data):
        (self.project / ".claude").mkdir(exist_ok=True)
        (self.project / ".claude" / "baton.json").write_text(json.dumps(data), encoding="utf-8")
        return config.load(self.project, global_path=self.project / "no-global.json")

    def test_overriding_one_key_keeps_the_others(self):
        c = self.load({"context_window": {"confirm": False}})
        self.assertFalse(c["context_window"]["confirm"])
        self.assertEqual(c["context_window"]["thresholds"],
                         config.DEFAULTS["context_window"]["thresholds"])
        self.assertEqual(c.warnings, [])

    def test_thresholds_come_back_sorted_and_without_repeats(self):
        # The hook takes "the highest crossed" and marks everything below it as
        # consumed: an unsorted list would break neither loudly nor at once.
        c = self.load({"context_window": {"thresholds": [85, 65, 85]}})
        self.assertEqual(c["context_window"]["thresholds"], [65, 85])

    def test_bad_thresholds_warn_and_keep_the_default(self):
        default = config.DEFAULTS["context_window"]["thresholds"]
        for bad in ("70", [], [1, 2, 3, 4, 5], [True], [0], [65, "85"], None):
            with self.subTest(bad=bad):
                c = self.load({"context_window": {"thresholds": bad}})
                self.assertEqual(c["context_window"]["thresholds"], default)
                self.assertTrue(any("thresholds" in w for w in c.warnings))

    def test_a_threshold_above_95_says_why(self):
        # Past 95 the drafting itself can trigger the compaction it pre-empts.
        c = self.load({"context_window": {"thresholds": [65, 99]}})
        self.assertEqual(c["context_window"]["thresholds"],
                         config.DEFAULTS["context_window"]["thresholds"])
        self.assertTrue(any("compact" in w for w in c.warnings))

    def test_switches_must_be_booleans(self):
        for key in ("enabled", "confirm"):
            with self.subTest(key=key):
                c = self.load({"context_window": {key: "yes"}})
                self.assertIs(c["context_window"][key], config.DEFAULTS["context_window"][key])
                self.assertTrue(any(key in w for w in c.warnings))

    def test_watch_at_zero_turns_the_early_warning_off(self):
        self.assertEqual(self.load({"context_window": {"watch_at": 0}})
                         ["context_window"]["watch_at"], 0)

    def test_numbers_out_of_range_warn(self):
        for key, bad in (("watch_at", 96), ("watch_at", -1), ("budget_tokens", 5000),
                         ("budget_tokens", True), ("min_tokens", -1)):
            with self.subTest(key=key, bad=bad):
                c = self.load({"context_window": {key: bad}})
                self.assertEqual(c["context_window"][key], config.DEFAULTS["context_window"][key])
                self.assertTrue(any(key in w for w in c.warnings))

    def test_a_budget_of_zero_means_automatic(self):
        c = self.load({"context_window": {"budget_tokens": 0}})
        self.assertEqual(c["context_window"]["budget_tokens"], 0)
        self.assertEqual(c.warnings, [])

    def test_an_unknown_subkey_warns(self):
        c = self.load({"context_window": {"thresold": [70]}})
        self.assertTrue(any("context_window.thresold" in w for w in c.warnings))

    def test_a_block_that_is_not_an_object_warns_instead_of_replacing(self):
        c = self.load({"context_window": 65})
        self.assertEqual(c["context_window"], config.DEFAULTS["context_window"])
        self.assertTrue(any("context_window" in w for w in c.warnings))

    def test_the_likely_typo_gets_a_hint(self):
        c = self.load({"threshold": 65})
        self.assertTrue(any("context_window.thresholds" in w for w in c.warnings))

    def test_the_loaded_list_is_not_the_defaults_list(self):
        # dict() copies the block but SHARES the list inside it: an append on a
        # loaded config would poison DEFAULTS for the rest of the process.
        before = list(config.DEFAULTS["context_window"]["thresholds"])
        c = config.load(self.project, global_path=self.project / "no-global.json")
        c["context_window"]["thresholds"].append(90)
        self.assertEqual(config.DEFAULTS["context_window"]["thresholds"], before)


if __name__ == "__main__":
    unittest.main()
