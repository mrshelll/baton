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
    def run_hook(self, event, payload, raw_input=None, env=None):
        """Invoke the hook the way the harness does: subprocess plus JSON stdin.

        Returns (returncode, dict_or_None, stderr). The dict is None when the
        output is empty (legitimate silence) or is not JSON.

        `env` overrides variables for this run; a None value removes one.
        """
        data = raw_input if raw_input is not None else json.dumps(payload)
        environment = clean_env()
        for key, value in (env or {}).items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        # cwd=project on purpose: when the payload carries no "cwd" the hook
        # falls back to os.getcwd(), and without this a test would write into
        # the real repo.
        p = subprocess.run(
            [sys.executable, str(REPO_ROOT / "hooks" / "baton_hook.py"), event],
            input=data, capture_output=True, text=True, env=environment,
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

    # -- transcripts -------------------------------------------------------
    def transcript(self, entries, name="transcript.jsonl"):
        """A JSONL transcript under the odd path, the way Claude Code writes it.

        A string entry goes in raw -- that is how a test plants garbage -- and
        anything else is serialised."""
        path = self.project / name
        lines = [e if isinstance(e, str) else json.dumps(e) for e in entries]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def answer(tokens, model="claude-opus-5-5", sidechain=False, output=1940):
        """An assistant entry whose context is exactly `tokens`, split across the
        three input fields the way real answers are. `output` is set on purpose:
        it must never count."""
        fresh = min(2, tokens)
        creation = (tokens - fresh) // 5
        return {
            "type": "assistant",
            "isSidechain": sidechain,
            "message": {"model": model, "usage": {
                "input_tokens": fresh,
                "cache_creation_input_tokens": creation,
                "cache_read_input_tokens": tokens - fresh - creation,
                "output_tokens": output,
            }},
        }

    @staticmethod
    def identity(model_id):
        """The attachment where Claude Code records the model WITH its window
        suffix -- `message.model` never carries the `[1m]`."""
        return {"type": "attachment", "isSidechain": False, "attachment": {
            "type": "model", "identity": {"modelId": model_id}}}
