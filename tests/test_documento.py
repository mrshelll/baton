"""Validar el borrador del modelo y componer el fichero final."""
import sys
import unittest

from tests.ayudas import RAIZ_REPO

sys.path.insert(0, str(RAIZ_REPO))
from lib import documento, salida  # noqa: E402

T = salida.cargar_textos()


class TestValidar(unittest.TestCase):
    def validar(self, cuerpo, modo="memoria"):
        return documento.validar_borrador(cuerpo, modo=modo, textos=T)

    def test_solo_estado_es_valido(self):
        p = self.validar("## Estado\nalgo concreto\n")
        self.assertTrue(p.valido, p.errores)

    def test_falta_estado(self):
        p = self.validar("## Trampas\ncuidado con X\n")
        self.assertFalse(p.valido)
        self.assertTrue(any("Estado" in e for e in p.errores), p.errores)

    def test_seccion_desconocida_lista_las_validas(self):
        p = self.validar("## Estado\nx\n## Notas sueltas\ny\n")
        self.assertFalse(p.valido)
        texto = " ".join(p.errores)
        self.assertIn("Notas sueltas", texto)
        self.assertIn("Trampas", texto, "debe listar las secciones validas")

    def test_relleno_se_rechaza_en_todas_sus_formas(self):
        for basura in ("ninguno", "N/A", "-", "—", "nada", "TBD", "no aplica"):
            with self.subTest(basura=basura):
                p = self.validar(f"## Estado\nx\n## Bloqueos\n{basura}\n")
                self.assertFalse(p.valido, basura)
                self.assertTrue(any("borra" in e.lower() for e in p.errores), p.errores)

    def test_seccion_vacia_tambien_es_relleno(self):
        p = self.validar("## Estado\nx\n## Bloqueos\n\n")
        self.assertFalse(p.valido)

    def test_continuacion_exige_siguiente_paso(self):
        p = self.validar("## Estado\nx\n", modo="continuacion")
        self.assertFalse(p.valido)
        self.assertTrue(any("Siguiente paso" in e for e in p.errores), p.errores)

    def test_continuacion_con_siguiente_paso_es_valida(self):
        p = self.validar("## Estado\nx\n## Siguiente paso\nhaz Y en z.py:10\n",
                         modo="continuacion")
        self.assertTrue(p.valido, p.errores)

    def test_memoria_puede_llevar_siguiente_paso(self):
        # Se permite a proposito: el peligro se neutraliza en el texto que se
        # inyecta, no rechazando informacion util.
        p = self.validar("## Estado\nx\n## Siguiente paso\nalgun dia Y\n")
        self.assertTrue(p.valido, p.errores)

    def test_etiquetas_con_tilde_o_caja_distinta_se_aceptan(self):
        p = self.validar("## estado\nx\n## Decisiones y su porqué\nA porque B\n")
        self.assertTrue(p.valido, p.errores)

    def test_texto_suelto_antes_de_la_primera_seccion_se_rechaza(self):
        p = self.validar("esto va suelto\n## Estado\nx\n")
        self.assertFalse(p.valido)

    def test_borrador_vacio_se_rechaza(self):
        self.assertFalse(self.validar("").valido)

    def test_el_frontmatter_del_modelo_se_ignora(self):
        # El modelo no escribe el frontmatter: si lo cuela, se descarta.
        p = self.validar("---\nmodo: continuacion\n---\n## Estado\nx\n")
        self.assertTrue(p.valido, p.errores)
        self.assertNotIn("modo:", p.cuerpo)


class TestComponer(unittest.TestCase):
    def componer(self, cuerpo="## Estado\nx\n", modo="memoria", **kw):
        base = dict(cuerpo=cuerpo, modo=modo, fecha="2026-09-03T10:00:00-05:00",
                    rama="main", commit="abc1234",
                    contexto="- rama `main`, arbol limpio", textos=T)
        base.update(kw)
        return documento.componer(**base)

    def test_frontmatter_con_las_cinco_claves_en_orden(self):
        texto = self.componer()
        cabecera = texto.split("---")[1].strip().split("\n")
        self.assertEqual([l.split(":")[0] for l in cabecera],
                         ["baton", "modo", "fecha", "rama", "commit"])

    def test_lo_compuesto_se_relee_solo(self):
        texto = self.componer(modo="continuacion",
                              cuerpo="## Estado\nx\n## Siguiente paso\ny\n")
        self.assertEqual(documento.leer_modo(texto), "continuacion")
        self.assertEqual(documento.leer_version(texto), documento.VERSION)
        self.assertEqual(documento.leer_campos(texto)["commit"], "abc1234")

    def test_lleva_la_advertencia_de_reescritura(self):
        self.assertIn("REESCRIBE ENTERO", self.componer())

    def test_incluye_el_contexto_de_git(self):
        self.assertIn("## Contexto", self.componer())
        self.assertIn("arbol limpio", self.componer())

    def test_sin_git_los_campos_lo_dicen(self):
        texto = self.componer(rama="sin-git", commit="sin-git")
        self.assertEqual(documento.leer_campos(texto)["rama"], "sin-git")

    def test_extraer_cuerpo_devuelve_lo_que_escribio_el_modelo(self):
        texto = self.componer(cuerpo="## Estado\nmi estado\n")
        self.assertIn("mi estado", documento.extraer_cuerpo(texto))
        self.assertNotIn("## Contexto", documento.extraer_cuerpo(texto))

    def test_la_huella_ignora_el_contexto_de_git(self):
        # Dos traspasos con el mismo cuerpo y distinto git son el MISMO
        # traspaso: si no, cada commit haria que pareciera novedad.
        a = self.componer(contexto="- rama `main`, arbol limpio")
        b = self.componer(contexto="- rama `otra`, 9 sin commitear: x")
        self.assertEqual(documento.huella(a), documento.huella(b))

    def test_la_huella_cambia_si_cambia_el_cuerpo(self):
        a = self.componer(cuerpo="## Estado\nuno\n")
        b = self.componer(cuerpo="## Estado\ndos\n")
        self.assertNotEqual(documento.huella(a), documento.huella(b))


if __name__ == "__main__":
    unittest.main()
