"""Config: global + proyecto, con precedencia clave a clave y fallo legible."""
import json
import sys
import unittest

from tests.ayudas import RAIZ_REPO, CasoBase

sys.path.insert(0, str(RAIZ_REPO))
from lib import config as cfg  # noqa: E402


class TestCarga(CasoBase):
    def escribir(self, cual, datos):
        if cual == "global":
            ruta = self.proyecto / "global-baton.json"
        else:
            (self.proyecto / ".claude").mkdir(exist_ok=True)
            ruta = self.proyecto / ".claude" / "baton.json"
        ruta.write_text(json.dumps(datos) if not isinstance(datos, str) else datos,
                        encoding="utf-8")
        return ruta

    def cargar(self, con_global=None):
        return cfg.cargar(self.proyecto, ruta_global=con_global)

    def test_sin_ficheros_devuelve_los_defaults(self):
        c = self.cargar()
        self.assertEqual(c["topes"], cfg.POR_DEFECTO["topes"])
        self.assertEqual(c.avisos, [])

    def test_el_proyecto_pisa_al_global(self):
        g = self.escribir("global", {"topes": {"lineas": 90}})
        self.escribir("proyecto", {"topes": {"lineas": 200}})
        self.assertEqual(self.cargar(g)["topes"]["lineas"], 200)

    def test_sobreescribir_un_tope_no_borra_los_otros(self):
        # Merge de un nivel: tocar `lineas` no puede dejarte sin `caracteres`.
        self.escribir("proyecto", {"topes": {"lineas": 60}})
        c = self.cargar()
        self.assertEqual(c["topes"]["lineas"], 60)
        self.assertEqual(c["topes"]["caracteres"], cfg.POR_DEFECTO["topes"]["caracteres"])

    def test_json_roto_avisa_nombrando_el_fichero_y_sigue(self):
        self.escribir("proyecto", "{esto no es json")
        c = self.cargar()
        self.assertEqual(c["topes"], cfg.POR_DEFECTO["topes"])
        self.assertTrue(any("baton.json" in a for a in c.avisos), c.avisos)

    def test_json_que_es_una_lista_no_rompe(self):
        self.escribir("proyecto", [1, 2, 3])
        c = self.cargar()
        self.assertEqual(c["topes"], cfg.POR_DEFECTO["topes"])
        self.assertTrue(c.avisos)

    def test_clave_desconocida_sugiere_la_correcta(self):
        self.escribir("proyecto", {"lineas_max": 60})
        c = self.cargar()
        self.assertTrue(any("lineas_max" in a for a in c.avisos), c.avisos)
        self.assertTrue(any("topes.lineas" in a for a in c.avisos), c.avisos)

    def test_ruta_de_documento_absoluta_se_rechaza(self):
        self.escribir("proyecto", {"documento": "/etc/passwd"})
        c = self.cargar()
        self.assertEqual(c["documento"], cfg.POR_DEFECTO["documento"])
        self.assertTrue(any("fuera del proyecto" in a for a in c.avisos), c.avisos)

    def test_ruta_de_documento_con_dos_puntos_se_rechaza(self):
        self.escribir("proyecto", {"documento": "../../fuera.md"})
        c = self.cargar()
        self.assertEqual(c["documento"], cfg.POR_DEFECTO["documento"])
        self.assertTrue(c.avisos)

    def test_historial_cero_desactiva_sin_romper(self):
        self.escribir("proyecto", {"historial_max": 0})
        self.assertEqual(self.cargar()["historial_max"], 0)

    def test_tope_no_numerico_se_ignora_con_aviso(self):
        self.escribir("proyecto", {"topes": {"lineas": "muchas"}})
        c = self.cargar()
        self.assertEqual(c["topes"]["lineas"], cfg.POR_DEFECTO["topes"]["lineas"])
        self.assertTrue(c.avisos)


if __name__ == "__main__":
    unittest.main()
