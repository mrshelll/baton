"""Rutas, activacion y bitacora. La base sobre la que se apoya todo lo demas."""
import json
import sys
import unittest
from pathlib import Path

from tests.ayudas import RAIZ_REPO, CasoBase

sys.path.insert(0, str(RAIZ_REPO))
from lib import almacen  # noqa: E402


class TestRaizProyecto(CasoBase):
    def test_encuentra_la_raiz_por_git(self):
        self.init_git()
        hondo = self.proyecto / "src" / "muy" / "adentro"
        hondo.mkdir(parents=True)
        self.assertEqual(almacen.raiz_proyecto(hondo), self.proyecto)

    def test_git_como_fichero_es_worktree_valido(self):
        # En un worktree, .git es un FICHERO que apunta al repo real.
        (self.proyecto / ".git").write_text("gitdir: /otro/lado\n", encoding="utf-8")
        hondo = self.proyecto / "a" / "b"
        hondo.mkdir(parents=True)
        self.assertEqual(almacen.raiz_proyecto(hondo), self.proyecto)

    def test_encuentra_la_raiz_por_carpeta_claude(self):
        (self.proyecto / ".claude").mkdir()
        hondo = self.proyecto / "x"
        hondo.mkdir()
        self.assertEqual(almacen.raiz_proyecto(hondo), self.proyecto)

    def test_la_carpeta_baton_tambien_marca_la_raiz(self):
        (self.proyecto / ".baton").mkdir()
        hondo = self.proyecto / "x"
        hondo.mkdir()
        self.assertEqual(almacen.raiz_proyecto(hondo), self.proyecto)

    def test_sin_ninguna_marca_devuelve_el_propio_cwd(self):
        self.assertEqual(almacen.raiz_proyecto(self.proyecto), self.proyecto)

    def test_cwd_inexistente_no_revienta(self):
        fantasma = self.proyecto / "no" / "existe"
        self.assertEqual(almacen.raiz_proyecto(fantasma), fantasma)


class TestActivacion(CasoBase):
    def test_proyecto_nuevo_no_esta_activado(self):
        self.assertFalse(almacen.esta_activado(self.proyecto))

    def test_el_documento_es_la_senal_de_activacion(self):
        rutas = almacen.Rutas(self.proyecto)
        rutas.asegurar_local()
        rutas.documento.parent.mkdir(parents=True, exist_ok=True)
        rutas.documento.write_text("---\nbaton: 1\n---\n", encoding="utf-8")
        self.assertTrue(almacen.esta_activado(self.proyecto))


class TestBitacora(CasoBase):
    def test_escribe_una_linea_jsonl_por_ejecucion(self):
        rutas = almacen.Rutas(self.proyecto)
        almacen.anotar(rutas, evento="session-start", resultado="silencio")
        almacen.anotar(rutas, evento="stop", resultado="calla")
        lineas = rutas.bitacora.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lineas), 2)
        primera = json.loads(lineas[0])
        self.assertEqual(primera["evento"], "session-start")
        self.assertEqual(primera["resultado"], "silencio")
        self.assertIn("ts", primera)

    def test_se_capa_a_doscientas_lineas(self):
        rutas = almacen.Rutas(self.proyecto)
        for i in range(260):
            almacen.anotar(rutas, evento="session-start", resultado=str(i))
        lineas = rutas.bitacora.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lineas), almacen.BITACORA_MAX_LINEAS)
        # Se conservan las MAS RECIENTES: la ultima debe ser la 259.
        self.assertEqual(json.loads(lineas[-1])["resultado"], "259")

    def test_anotar_nunca_lanza_aunque_el_destino_sea_imposible(self):
        rutas = almacen.Rutas(Path("/proc/no-escribible-jamas"))
        almacen.anotar(rutas, evento="stop", resultado="x")  # no debe lanzar


if __name__ == "__main__":
    unittest.main()
