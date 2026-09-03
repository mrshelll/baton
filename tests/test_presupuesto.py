"""El presupuesto: que el traspaso no crezca, verificado por codigo.

El techo no es una preferencia. `additionalContext` se trunca a 8.000
caracteres o 200 lineas, lo que ocurra primero, y en silencio. Los topes por
defecto se derivan hacia atras desde ahi.
"""
import sys
import unittest

from tests.ayudas import RAIZ_REPO

sys.path.insert(0, str(RAIZ_REPO))
from lib import presupuesto  # noqa: E402


class TestEstimarTokens(unittest.TestCase):
    def test_vacio_es_cero(self):
        self.assertEqual(presupuesto.estimar_tokens(""), 0)
        self.assertEqual(presupuesto.estimar_tokens(None), 0)

    def test_golden_no_se_mueve_sin_querer(self):
        # Fijar un rango evita que un refactor cambie en silencio la cifra que
        # se le reporta al usuario.
        texto = ("Migrando el cobro de Stripe Charges a PaymentIntents. "
                 "src/pagos.ts ya usa PaymentIntents en el camino feliz.\n") * 10
        self.assertTrue(180 <= presupuesto.estimar_tokens(texto) <= 400,
                        presupuesto.estimar_tokens(texto))

    def test_es_pesimista_nunca_subestima_de_largo(self):
        texto = "palabra " * 500
        # ~4000 chars / 3.6 = 1111 ; 500 palabras * 1.3 = 650 -> gana el mayor
        self.assertGreaterEqual(presupuesto.estimar_tokens(texto), 1000)


class TestMedir(unittest.TestCase):
    def test_documento_corto_pasa(self):
        m = presupuesto.medir("---\nbaton: 1\n---\n\n## Estado\ncorto\n")
        self.assertLess(m.lineas, 20)
        self.assertGreater(m.caracteres, 0)

    def test_vacio_no_divide_por_cero(self):
        m = presupuesto.medir("")
        self.assertEqual((m.lineas, m.caracteres, m.tokens), (0, 0, 0))

    def test_cuenta_lineas_reales_no_parrafos(self):
        self.assertEqual(presupuesto.medir("a\nb\nc\n").lineas, 3)
        self.assertEqual(presupuesto.medir("a\nb\nc").lineas, 3)


class TestVeredicto(unittest.TestCase):
    def topes(self, **kw):
        base = dict(presupuesto.TOPES_POR_DEFECTO)
        base.update(kw)
        return base

    def test_dentro_de_presupuesto(self):
        v = presupuesto.evaluar("## Estado\nbreve\n", self.topes())
        self.assertTrue(v.cabe)
        self.assertEqual(v.excesos, {})

    def test_demasiadas_lineas(self):
        v = presupuesto.evaluar("x\n" * 147, self.topes(lineas=120))
        self.assertFalse(v.cabe)
        self.assertIn("lineas", v.excesos)
        self.assertEqual(v.excesos["lineas"], 27)

    def test_pocas_lineas_pero_demasiados_caracteres(self):
        # Un parrafo largo cabe en pocas lineas y aun asi no entra: por eso
        # `caracteres` es la medida vinculante, no `lineas`.
        v = presupuesto.evaluar("palabra " * 2000, self.topes())
        self.assertFalse(v.cabe)
        self.assertIn("caracteres", v.excesos)
        self.assertNotIn("lineas", v.excesos)

    def test_los_topes_por_defecto_caben_bajo_el_techo_del_harness(self):
        t = presupuesto.TOPES_POR_DEFECTO
        self.assertLessEqual(t["caracteres"] + presupuesto.RESERVA_ENVOLTORIO_CARACTERES,
                             presupuesto.TECHO_CARACTERES)
        self.assertLessEqual(t["lineas"] + presupuesto.RESERVA_ENVOLTORIO_LINEAS,
                             presupuesto.TECHO_LINEAS)

    def test_respeta_topes_personalizados(self):
        v = presupuesto.evaluar("x\n" * 80, self.topes(lineas=60))
        self.assertFalse(v.cabe)
        self.assertEqual(v.excesos["lineas"], 20)


class TestInforme(unittest.TestCase):
    CUERPO = ("## Estado\n" + "e\n" * 40 +
              "## Decisiones y su porque\n" + "d\n" * 61 +
              "## Trampas\n" + "t\n" * 27)

    def test_senala_la_seccion_mas_gorda(self):
        v = presupuesto.evaluar(self.CUERPO, presupuesto.TOPES_POR_DEFECTO)
        texto = presupuesto.informe(v, self.CUERPO, intento=1, maximo=3)
        self.assertIn("Decisiones y su porque", texto)
        self.assertIn("<--", texto, "debe marcar cual es la mas gorda")

    def test_dice_que_no_se_ha_escrito_nada(self):
        v = presupuesto.evaluar(self.CUERPO, presupuesto.TOPES_POR_DEFECTO)
        texto = presupuesto.informe(v, self.CUERPO, intento=1, maximo=3)
        self.assertIn("No se ha escrito nada", texto)

    def test_muestra_el_contador_de_intentos(self):
        v = presupuesto.evaluar(self.CUERPO, presupuesto.TOPES_POR_DEFECTO)
        self.assertIn("Intento 2 de 3", presupuesto.informe(v, self.CUERPO, intento=2, maximo=3))


class TestRecorteHonesto(unittest.TestCase):
    def test_corta_por_lineas_completas_nunca_a_media_frase(self):
        texto = "linea primera y larga\nlinea segunda tambien larga\nlinea tercera\n"
        salida, recortado = presupuesto.recortar_por_lineas(texto, max_caracteres=30, max_lineas=99)
        self.assertTrue(recortado)
        self.assertLessEqual(len(salida), 30)
        for linea in salida.split("\n"):
            if linea:
                self.assertIn(linea, texto, "ninguna linea puede quedar partida")

    def test_no_recorta_lo_que_ya_cabe(self):
        texto = "corto\n"
        salida, recortado = presupuesto.recortar_por_lineas(texto, 1000, 100)
        self.assertFalse(recortado)
        self.assertEqual(salida, texto)

    def test_tambien_recorta_por_numero_de_lineas(self):
        texto = "".join(f"l{i}\n" for i in range(50))
        salida, recortado = presupuesto.recortar_por_lineas(texto, 100000, 10)
        self.assertTrue(recortado)
        self.assertLessEqual(len([l for l in salida.split("\n") if l]), 10)


if __name__ == "__main__":
    unittest.main()
