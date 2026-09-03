"""El contrato que ningun camino puede romper: el hook SIEMPRE sale con 0.

Un traspaso roto, un stdin corrupto o un disco lleno no pueden impedir que
arranque una sesion de Claude Code. Estos tests invocan el hook como subproceso
con stdin JSON, exactamente igual que el harness.
"""
import json
import unittest

from tests.ayudas import CasoBase

EVENTOS = ("session-start", "post-compact", "stop")


class TestSiempreSaleCero(CasoBase):
    def test_todos_los_eventos_callan_en_proyecto_sin_activar(self):
        for evento in EVENTOS:
            with self.subTest(evento=evento):
                rc, salida, err = self.correr_hook(evento, self.payload(evento))
                self.assertEqual(rc, 0, err)
                self.assertIsNone(salida, "un proyecto sin activar debe callar")

    def test_stdin_que_no_es_json(self):
        for evento in EVENTOS:
            with self.subTest(evento=evento):
                rc, _, err = self.correr_hook(evento, None, entrada_cruda="{esto no es json")
                self.assertEqual(rc, 0, err)

    def test_stdin_vacio(self):
        for evento in EVENTOS:
            with self.subTest(evento=evento):
                rc, _, err = self.correr_hook(evento, None, entrada_cruda="")
                self.assertEqual(rc, 0, err)

    def test_stdin_json_pero_no_es_un_objeto(self):
        rc, _, err = self.correr_hook("session-start", None, entrada_cruda="[1, 2, 3]")
        self.assertEqual(rc, 0, err)

    def test_cwd_inexistente(self):
        payload = self.payload("SessionStart", cwd=str(self.proyecto / "no" / "existe"))
        rc, _, err = self.correr_hook("session-start", payload)
        self.assertEqual(rc, 0, err)

    def test_cwd_ausente_del_payload(self):
        rc, _, err = self.correr_hook("session-start", {"session_id": "x"})
        self.assertEqual(rc, 0, err)

    def test_evento_desconocido_no_revienta(self):
        rc, _, err = self.correr_hook("evento-inventado", self.payload("X"))
        self.assertEqual(rc, 0, err)

    def test_sin_argumento_de_evento_no_revienta(self):
        import subprocess, sys
        from tests.ayudas import RAIZ_REPO, _sin_locale
        p = subprocess.run(
            [sys.executable, str(RAIZ_REPO / "hooks" / "baton_hook.py")],
            input="{}", capture_output=True, text=True, env=_sin_locale(), timeout=30,
        )
        self.assertEqual(p.returncode, 0, p.stderr)


class TestBitacoraDelHook(CasoBase):
    def test_toda_ejecucion_deja_rastro(self):
        # Sin documento el hook calla, pero DEBE anotar: es lo unico que
        # distingue "no disparo" de "disparo y callo".
        rc, salida, _ = self.correr_hook("session-start", self.payload("SessionStart"))
        self.assertEqual(rc, 0)
        self.assertIsNone(salida)
        bitacora = self.proyecto / ".baton" / "local" / "bitacora.jsonl"
        self.assertTrue(bitacora.exists(), "el hook debe anotar aunque calle")
        registro = json.loads(bitacora.read_text(encoding="utf-8").strip())
        self.assertEqual(registro["evento"], "session-start")


if __name__ == "__main__":
    unittest.main()
