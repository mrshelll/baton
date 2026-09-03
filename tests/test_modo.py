"""El regex de modo: la pieza de la que cuelga el diferenciador de baton.

Regla unica: ante CUALQUIER duda, `memoria`. Un documento ambiguo jamas puede
provocar que la sesion nueva arranque sola y toque trabajo que nadie pidio.
"""
import sys
import time
import unittest

from tests.ayudas import RAIZ_REPO

sys.path.insert(0, str(RAIZ_REPO))
from lib import documento  # noqa: E402

CAB = "---\nbaton: 1\n{}\nfecha: 2026-09-03T00:00:00Z\nrama: main\ncommit: abc1234\n---\n"


def doc(linea_modo, cuerpo="\n## Estado\nalgo\n"):
    return CAB.format(linea_modo) + cuerpo


class TestLeerModo(unittest.TestCase):
    def test_valores_validos(self):
        for valor in ("continuacion", "memoria"):
            with self.subTest(valor=valor):
                self.assertEqual(documento.leer_modo(doc(f"modo: {valor}")), valor)

    def test_tolera_espacios_y_tabulaciones(self):
        casos = ["modo:continuacion", "modo:   continuacion   ", "modo:\tcontinuacion"]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertEqual(documento.leer_modo(doc(texto)), "continuacion")

    def test_ascii_estricto_la_tilde_no_vale(self):
        # `continuacion` es un ENUM, no prosa. Con tilde no es el enum.
        self.assertEqual(documento.leer_modo(doc("modo: continuación")), "memoria")

    def test_mayusculas_no_valen(self):
        for texto in ("modo: CONTINUACION", "modo: Continuacion"):
            with self.subTest(texto=texto):
                self.assertEqual(documento.leer_modo(doc(texto)), "memoria")

    def test_valor_parecido_pero_distinto(self):
        for texto in ("modo: continuacion_larga", "modo: continuacion extra", "modo: cont"):
            with self.subTest(texto=texto):
                self.assertEqual(documento.leer_modo(doc(texto)), "memoria")

    def test_sin_frontmatter(self):
        self.assertEqual(documento.leer_modo("## Estado\nhola\n"), "memoria")

    def test_frontmatter_sin_cerrar(self):
        self.assertEqual(documento.leer_modo("---\nbaton: 1\nmodo: continuacion\n"), "memoria")

    def test_fichero_vacio(self):
        self.assertEqual(documento.leer_modo(""), "memoria")

    def test_modo_en_el_cuerpo_no_cuenta(self):
        # Solo manda el frontmatter. Un cuerpo que hable de "modo: continuacion"
        # no puede cambiar el comportamiento de la sesion siguiente.
        texto = doc("modo: memoria", cuerpo="\n## Estado\nhablamos de modo: continuacion aqui\n")
        self.assertEqual(documento.leer_modo(texto), "memoria")

    def test_soporta_crlf(self):
        self.assertEqual(documento.leer_modo(doc("modo: continuacion").replace("\n", "\r\n")),
                         "continuacion")

    def test_documento_gigante_es_rapido(self):
        # Solo se mira la cabeza del fichero: un doc de 1 MB no puede costar
        # nada en el arranque de cada sesion.
        gigante = doc("modo: continuacion") + ("x" * 1_000_000)
        t0 = time.perf_counter()
        self.assertEqual(documento.leer_modo(gigante), "continuacion")
        self.assertLess(time.perf_counter() - t0, 0.05)

    def test_bytes_no_utf8_no_lanzan(self):
        self.assertEqual(documento.leer_modo("\udcff\udcfe basura"), "memoria")

    def test_none_o_tipo_raro(self):
        for valor in (None, 123, [], {}):
            with self.subTest(valor=valor):
                self.assertEqual(documento.leer_modo(valor), "memoria")

    def test_version_futura_conserva_el_modo_pero_se_marca(self):
        texto = doc("modo: continuacion").replace("baton: 1", "baton: 2")
        self.assertEqual(documento.leer_modo(texto), "continuacion")
        self.assertEqual(documento.leer_version(texto), 2)

    def test_version_ausente_es_none(self):
        self.assertIsNone(documento.leer_version("## Estado\nx\n"))


if __name__ == "__main__":
    unittest.main()
