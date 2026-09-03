"""Shared test helpers.

House rule: temporary projects are ALWAYS created under a path with a space and
an accent. The awkward path is the base case, not a separate test -- it is where
plugins that quote badly in the shell fall over.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ODD_SUBDIR = "Agentes IA/próyecto de prueba"


def clean_env(env=None):
    e = dict(os.environ if env is None else env)
    e["LC_ALL"] = "C"
    return e


class BaseCase(unittest.TestCase):
    """Creates a temporary project on a path with a space and an accent."""

    def setUp(self):
        # resolve(): on macOS /var is a symlink to /private/var and the code
        # canonicalises paths. Without this, tests compare equivalent but
        # different paths and fail over something that is not the product.
        self._tmp = str(Path(tempfile.mkdtemp(prefix="baton-test-")).resolve())
        self.project = Path(self._tmp) / ODD_SUBDIR
        self.project.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    # -- git ---------------------------------------------------------------
    def init_git(self, commit=True):
        """An isolated git repo: config goes inline so it never depends on the
        global one."""
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@baton.local")
        self.git("config", "user.name", "baton test")
        if commit:
            (self.project / "README.md").write_text("hello\n", encoding="utf-8")
            self.git("add", "-A")
            self.git("commit", "-q", "-m", "initial commit")
        return self.project

    def git(self, *args):
        return subprocess.run(
            ("git",) + args, cwd=self.project, capture_output=True,
            text=True, env=clean_env(), check=False,
        )

    # -- hooks -------------------------------------------------------------
    def run_hook(self, event, payload, raw_input=None):
        """Invoke the hook the way the harness does: subprocess plus JSON stdin.

        Returns (returncode, dict_or_None, stderr). The dict is None when the
        output is empty (legitimate silence) or is not JSON.
        """
        data = raw_input if raw_input is not None else json.dumps(payload)
        # cwd=project on purpose: when the payload carries no "cwd" the hook
        # falls back to os.getcwd(), and without this a test would write into
        # the real repo.
        p = subprocess.run(
            [sys.executable, str(REPO_ROOT / "hooks" / "baton_hook.py"), event],
            input=data, capture_output=True, text=True, env=clean_env(),
            cwd=str(self.project), check=False, timeout=30,
        )
        out = None
        if p.stdout.strip():
            try:
                out = json.loads(p.stdout)
            except json.JSONDecodeError:
                out = None
        return p.returncode, out, p.stderr

    def payload(self, event, **extra):
        base = {
            "session_id": "test-session",
            "transcript_path": os.devnull,
            "cwd": str(self.project),
            "hook_event_name": event,
        }
        base.update(extra)
        return base

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "baton.py"), *args,
             "--cwd", str(self.project)],
            capture_output=True, text=True, env=clean_env(), timeout=60,
        )
