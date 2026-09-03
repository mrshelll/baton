"""baton's state files can be corrupt, and that cannot bring anything down.

baton writes them, yes -- but so can an editor, a merge, a full disk or a session
killed mid-write. Each of these cases once propagated an exception to the hook.
"""
import json
import sys
import unittest

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import storage  # noqa: E402


class TestCorruptState(BaseCase):
    def setUp(self):
        super().setUp()
        self.p = storage.Paths(self.project)
        self.p.ensure_local()
        self.p.document.parent.mkdir(parents=True, exist_ok=True)
        self.p.document.write_text("---\nbaton: 1\nmode: memory\n---\n## State\nx\n",
                                   encoding="utf-8")

    def junk(self):
        # Valid JSON that is NOT an object, loose text, and an empty file.
        return ('[1, 2, 3]', '"a string"', 'null', '{broken', '', '   ')

    def test_corrupt_deliveries_do_not_raise(self):
        for content in self.junk():
            with self.subTest(content=content):
                self.p.deliveries.write_text(content, encoding="utf-8")
                storage.record_delivery(self.p, "fingerprint123")

    def test_corrupt_pending_does_not_raise(self):
        for content in self.junk():
            with self.subTest(content=content):
                self.p.pending.write_text(content, encoding="utf-8")
                self.assertIsInstance(storage.has_pending(self.p, 30), bool)
                storage.consume_pending(self.p)
                storage.arm_pending(self.p, "s1")

    def test_an_odd_type_in_the_cooldown_stamp(self):
        # A numeric `last_request` raised TypeError, not ValueError.
        for value in (12345, None, [], {"a": 1}, "yesterday"):
            with self.subTest(value=value):
                self.p.pending.write_text(json.dumps(
                    {"requested": False, "last_request": value}), encoding="utf-8")
                self.assertIsInstance(storage.has_pending(self.p, 30), bool)

    def test_the_hook_survives_all_of_the_above(self):
        for content in self.junk():
            with self.subTest(content=content):
                self.p.deliveries.write_text(content, encoding="utf-8")
                self.p.pending.write_text(content, encoding="utf-8")
                for event in ("session-start", "post-compact", "stop"):
                    rc, _, err = self.run_hook(event, self.payload(event))
                    self.assertEqual(rc, 0, f"{event} with {content!r}: {err}")

    def test_a_corrupt_log_does_not_stop_logging(self):
        self.p.log.write_text("{not jsonl\nnor this\n", encoding="utf-8")
        storage.log_event(self.p, event="stop", result="ok")
        self.assertIn("stop", self.p.log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
