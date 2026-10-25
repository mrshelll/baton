"""baton's test suite.

Its HOME is an empty folder of its own, for the tests and every process they
start: whoever runs the suite may keep a `~/.claude/baton.json` (a `language`,
say) that is not the defaults'. A test that needs a HOME of its own passes it.
"""
import atexit
import os
import shutil
import tempfile

_HOME = tempfile.mkdtemp(prefix="baton-test-home-")
os.environ["HOME"] = _HOME
atexit.register(shutil.rmtree, _HOME, ignore_errors=True)
