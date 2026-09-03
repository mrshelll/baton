"""Ayudas comunes a los tests.

Regla de la casa: los proyectos temporales se crean SIEMPRE bajo una ruta con
espacio y tilde. La ruta rara es el caso base, no un test aparte -- es donde se
rompen los plugins que citan mal en el shell.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
SUBDIR_RARO = "Agentes IA/próyecto de prueba"


def _sin_locale(env=None):
    e = dict(os.environ if env is None else env)
    e["LC_ALL"] = "C"
    return e


class CasoBase(unittest.TestCase):
    """Crea un proyecto temporal en una ruta con espacio y tilde."""

    def setUp(self):
        # resolve(): en macOS /var es un symlink a /private/var, y el codigo
        # canonicaliza rutas. Sin esto los tests comparan rutas equivalentes
        # pero distintas y fallan por un detalle que no es del producto.
        self._tmp = str(Path(tempfile.mkdtemp(prefix="baton-test-")).resolve())
        self.proyecto = Path(self._tmp) / SUBDIR_RARO
        self.proyecto.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    # -- git ---------------------------------------------------------------
    def init_git(self, commit=True):
        """Repo git aislado: la config va inline para no depender de la global."""
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@baton.local")
        self.git("config", "user.name", "baton test")
        if commit:
            (self.proyecto / "README.md").write_text("hola\n", encoding="utf-8")
            self.git("add", "-A")
            self.git("commit", "-q", "-m", "commit inicial")
        return self.proyecto

    def git(self, *args):
        return subprocess.run(
            ("git",) + args, cwd=self.proyecto, capture_output=True,
            text=True, env=_sin_locale(), check=False,
        )

    # -- hooks -------------------------------------------------------------
    def correr_hook(self, evento, payload, entrada_cruda=None):
        """Invoca el hook como lo hace el harness: subproceso + stdin JSON.

        Devuelve (returncode, dict_o_None, stderr). El dict es None cuando la
        salida esta vacia (silencio legitimo) o no es JSON.
        """
        datos = entrada_cruda
        if datos is None:
            datos = json.dumps(payload)
        p = subprocess.run(
            [sys.executable, str(RAIZ_REPO / "hooks" / "baton_hook.py"), evento],
            input=datos, capture_output=True, text=True, env=_sin_locale(),
            check=False, timeout=30,
        )
        salida = None
        if p.stdout.strip():
            try:
                salida = json.loads(p.stdout)
            except json.JSONDecodeError:
                salida = None
        return p.returncode, salida, p.stderr

    def payload(self, evento, **extra):
        base = {
            "session_id": "sesion-de-prueba",
            "transcript_path": os.devnull,
            "cwd": str(self.proyecto),
            "hook_event_name": evento,
        }
        base.update(extra)
        return base
