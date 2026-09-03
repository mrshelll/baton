"""Los ficheros de estado de baton pueden estar corruptos, y no pueden tumbar nada.

Los escribe baton, sí -- pero también los puede tocar un editor, un merge, un
disco lleno o una sesión matada a mitad de escritura. Cada uno de estos casos
llegó a propagar una excepción hacia el hook.
"""
import json
import sys
import unittest

from tests.ayudas import RAIZ_REPO, CasoBase

sys.path.insert(0, str(RAIZ_REPO))
from lib import almacen  # noqa: E402


class TestEstadoCorrupto(CasoBase):
    def setUp(self):
        super().setUp()
        self.r = almacen.Rutas(self.proyecto)
        self.r.asegurar_local()
        self.r.documento.parent.mkdir(parents=True, exist_ok=True)
        self.r.documento.write_text("---\nbaton: 1\nmodo: memoria\n---\n## Estado\nx\n",
                                    encoding="utf-8")

    def basura(self):
        # JSON válido que NO es un objeto, texto suelto, y un fichero vacío.
        return ('[1, 2, 3]', '"una cadena"', 'null', '{roto', '', '   ')

    def test_entregas_corrupto_no_lanza(self):
        for contenido in self.basura():
            with self.subTest(contenido=contenido):
                self.r.entregas.write_text(contenido, encoding="utf-8")
                almacen.registrar_entrega(self.r, "huella123")

    def test_pendiente_corrupto_no_lanza(self):
        for contenido in self.basura():
            with self.subTest(contenido=contenido):
                self.r.pendiente.write_text(contenido, encoding="utf-8")
                self.assertIsInstance(almacen.hay_pendiente(self.r, 30), bool)
                almacen.consumir_pendiente(self.r)
                almacen.armar_pendiente(self.r, "s1")

    def test_fecha_de_tipo_raro_en_el_cooldown(self):
        # Un `ultima_peticion` numérico lanzaba TypeError, no ValueError.
        for valor in (12345, None, [], {"a": 1}, "ayer"):
            with self.subTest(valor=valor):
                self.r.pendiente.write_text(json.dumps(
                    {"pedido": False, "ultima_peticion": valor}), encoding="utf-8")
                self.assertIsInstance(almacen.hay_pendiente(self.r, 30), bool)

    def test_el_hook_sobrevive_a_todo_lo_anterior(self):
        for contenido in self.basura():
            with self.subTest(contenido=contenido):
                self.r.entregas.write_text(contenido, encoding="utf-8")
                self.r.pendiente.write_text(contenido, encoding="utf-8")
                for evento in ("session-start", "post-compact", "stop"):
                    rc, _, err = self.correr_hook(evento, self.payload(evento))
                    self.assertEqual(rc, 0, f"{evento} con {contenido!r}: {err}")

    def test_bitacora_corrupta_no_impide_anotar(self):
        self.r.bitacora.write_text("{esto no es jsonl\nni esto\n", encoding="utf-8")
        almacen.anotar(self.r, evento="stop", resultado="ok")
        self.assertIn("stop", self.r.bitacora.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
