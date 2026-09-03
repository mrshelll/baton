"""doctor: convertir el silencio de un hook que no dispara en un diagnostico."""
import subprocess
import sys
import unittest

from tests.ayudas import RAIZ_REPO, CasoBase, _sin_locale


class TestDoctor(CasoBase):
    def doctor(self):
        return subprocess.run(
            [sys.executable, str(RAIZ_REPO / "scripts" / "baton.py"),
             "doctor", "--cwd", str(self.proyecto)],
            capture_output=True, text=True, env=_sin_locale(), timeout=30,
        )

    def activar(self):
        rutas_baton = self.proyecto / ".baton"
        rutas_baton.mkdir(parents=True, exist_ok=True)
        (rutas_baton / "TRASPASO.md").write_text("---\nbaton: 1\n---\n", encoding="utf-8")

    def test_proyecto_sin_activar_lo_explica_y_sale_cero(self):
        p = self.doctor()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("aun no usa baton", p.stdout)
        self.assertIn("NO es un fallo", p.stdout)

    def test_comprueba_hooks_json_python_y_git(self):
        p = self.doctor()
        for esperado in ("hooks.json valido", "python3", "git"):
            self.assertIn(esperado, p.stdout)

    def test_proyecto_activado_sin_rastro_acusa_al_reinicio(self):
        self.activar()
        p = self.doctor()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("NO ha dejado ni un rastro", p.stdout)
        self.assertIn("sin reiniciar Claude Code", p.stdout)

    def test_proyecto_activado_con_rastro_reciente_no_acusa_a_nadie(self):
        self.activar()
        sys.path.insert(0, str(RAIZ_REPO))
        from lib import almacen
        almacen.anotar(almacen.Rutas(self.proyecto), evento="session-start", resultado="ok")
        p = self.doctor()
        self.assertIn("Ultimo disparo del hook:", p.stdout)
        self.assertNotIn("NO ha dejado ni un rastro", p.stdout)


if __name__ == "__main__":
    unittest.main()


class TestVer(CasoBase):
    def ver(self, *extra):
        import subprocess, sys
        from tests.ayudas import RAIZ_REPO, _sin_locale
        return subprocess.run(
            [sys.executable, str(RAIZ_REPO / "scripts" / "baton.py"), "ver",
             "--cwd", str(self.proyecto), *extra],
            capture_output=True, text=True, env=_sin_locale(), timeout=30)

    def test_sin_traspaso_lo_dice_sin_fallar(self):
        p = self.ver()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("no tiene traspaso", p.stdout)

    def test_resume_modo_tamano_y_frescura(self):
        d = self.proyecto / ".baton"
        d.mkdir(parents=True)
        (d / "TRASPASO.md").write_text(
            "---\nbaton: 1\nmodo: continuacion\nfecha: 2020-01-01T00:00:00Z\n"
            "rama: main\ncommit: abc1234\n---\n\n## Estado\nx\n", encoding="utf-8")
        p = self.ver()
        self.assertIn("modo continuacion", p.stdout)
        self.assertIn("lineas", p.stdout)
        self.assertIn("frescura", p.stdout.lower())
