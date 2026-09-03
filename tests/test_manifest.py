"""The two manifests have to agree on the version.

`plugin.json` is what the installed plugin reports; `marketplace.json` is what
`claude plugin update` reads to decide there is something new. Bumping only the
first ships a release nobody can install: the code changes, the marketplace still
says 0.3.2, and the update is a no-op with no error anywhere.

Same reasoning as the README test count: remove the possibility, not the symptom.
"""
import json
import unittest

from tests.helpers import REPO_ROOT

MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestManifests(unittest.TestCase):
    def test_both_are_valid_json_objects(self):
        for path in (MANIFEST, MARKETPLACE):
            with self.subTest(file=path.name):
                self.assertIsInstance(_load(path), dict)

    def test_the_marketplace_lists_the_plugin_once(self):
        entries = [p for p in _load(MARKETPLACE)["plugins"]
                   if p["name"] == _load(MANIFEST)["name"]]
        self.assertEqual(len(entries), 1)

    def test_the_version_is_the_same_in_both(self):
        plugin = _load(MANIFEST)
        entry = next(p for p in _load(MARKETPLACE)["plugins"]
                     if p["name"] == plugin["name"])
        self.assertEqual(entry["version"], plugin["version"],
                         "marketplace.json says {}, plugin.json says {}: "
                         "`claude plugin update` would not pick the release up"
                         .format(entry["version"], plugin["version"]))

    def test_the_version_looks_like_a_version(self):
        parts = _load(MANIFEST)["version"].split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            self.assertTrue(part.isdigit(), f"not a number: {part!r}")


if __name__ == "__main__":
    unittest.main()
