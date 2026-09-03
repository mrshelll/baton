"""El CLI: los codigos de salida son el protocolo con el modelo."""
import subprocess
import sys
import unittest

from tests.ayudas import RAIZ_REPO, CasoBase, _sin_locale

OK, PRESUPUESTO, INVALIDO, ENTORNO = 0, 1, 2, 3


class BaseCLI(CasoBase):
    def baton(self, *args):
        return subprocess.run(
            [sys.executable, str(RAIZ_REPO / "scripts" / "baton.py"), *args,
             "--cwd", str(self.proyecto)],
            capture_output=True, text=True, env=_sin_locale(), timeout=60,
        )

    def borrador(self, texto):
        local = self.proyecto / ".baton" / "local"
        local.mkdir(parents=True, exist_ok=True)
        (local / "borrador.md").write_text(texto, encoding="utf-8")

    def documento(self):
        return (self.proyecto / ".baton" / "TRASPASO.md").read_text(encoding="utf-8")


class TestContexto(BaseCLI):
    def test_es_breve_y_util(self):
        self.init_git()
        p = self.baton("contexto")
        self.assertEqual(p.returncode, OK, p.stderr)
        self.assertLessEqual(len(p.stdout.strip().split("\n")), 25,
                             "el contexto no puede comerse el presupuesto")
        self.assertIn("rama", p.stdout)

    def test_dice_donde_escribir_el_borrador(self):
        p = self.baton("contexto")
        self.assertIn("borrador.md", p.stdout)

    def test_avisa_de_la_linea_de_gitignore_que_falta(self):
        self.init_git()
        p = self.baton("contexto")
        self.assertIn(".baton/local/", p.stdout)

    def test_sin_git_no_revienta(self):
        p = self.baton("contexto")
        self.assertEqual(p.returncode, OK, p.stderr)


class TestEscribir(BaseCLI):
    def test_camino_feliz(self):
        self.init_git()
        self.borrador("## Estado\nMigracion a PaymentIntents a medias.\n")
        p = self.baton("escribir", "--modo", "memoria")
        self.assertEqual(p.returncode, OK, p.stderr + p.stdout)
        doc = self.documento()
        self.assertIn("modo: memoria", doc)
        self.assertIn("PaymentIntents", doc)
        self.assertIn("## Contexto", doc)

    def test_el_documento_escrito_se_relee_solo(self):
        sys.path.insert(0, str(RAIZ_REPO))
        from lib import documento as doc
        self.init_git()
        self.borrador("## Estado\nx\n## Siguiente paso\nhaz Y en a.py:1\n")
        self.baton("escribir", "--modo", "continuacion")
        self.assertEqual(doc.leer_modo(self.documento()), "continuacion")

    def test_sin_borrador_es_error_de_estructura(self):
        p = self.baton("escribir", "--modo", "memoria")
        self.assertEqual(p.returncode, INVALIDO, p.stdout)

    def test_borrador_sin_estado_es_error_de_estructura(self):
        self.borrador("## Trampas\nojo con X\n")
        p = self.baton("escribir", "--modo", "memoria")
        self.assertEqual(p.returncode, INVALIDO)
        self.assertIn("Estado", p.stderr)

    def test_relleno_es_error_de_estructura(self):
        self.borrador("## Estado\nx\n## Bloqueos\nninguno\n")
        p = self.baton("escribir", "--modo", "memoria")
        self.assertEqual(p.returncode, INVALIDO)
        self.assertIn("BORRALA", p.stderr.upper())

    def test_continuacion_sin_siguiente_paso(self):
        self.borrador("## Estado\nx\n")
        p = self.baton("escribir", "--modo", "continuacion")
        self.assertEqual(p.returncode, INVALIDO)
        self.assertIn("continuacion", p.stderr)

    def test_pasarse_de_presupuesto_es_codigo_uno(self):
        self.borrador("## Estado\n" + "linea de relleno\n" * 200)
        p = self.baton("escribir", "--modo", "memoria")
        self.assertEqual(p.returncode, PRESUPUESTO, p.stderr)
        self.assertIn("Intento 1 de 3", p.stderr)

    def test_al_fallar_no_escribe_nada_y_respeta_lo_anterior(self):
        self.init_git()
        self.borrador("## Estado\nbueno\n")
        self.baton("escribir", "--modo", "memoria")
        antes = self.documento()
        self.borrador("## Estado\n" + "x\n" * 300)
        self.baton("escribir", "--modo", "memoria")
        self.assertEqual(self.documento(), antes, "el traspaso anterior debe seguir intacto")

    def test_al_tercer_intento_escribe_un_minimo_y_lo_declara(self):
        self.init_git()
        gordo = "## Estado\n" + "linea de relleno bastante larga\n" * 200
        for i in (1, 2):
            self.borrador(gordo)
            self.assertEqual(self.baton("escribir", "--modo", "memoria").returncode, PRESUPUESTO)
        self.borrador(gordo)
        p = self.baton("escribir", "--modo", "memoria")
        self.assertEqual(p.returncode, OK, p.stderr)
        doc = self.documento()
        self.assertIn("recortado por baton", doc)
        # Y lo escrito respeta el presupuesto de verdad.
        sys.path.insert(0, str(RAIZ_REPO))
        from lib import presupuesto
        self.assertTrue(presupuesto.evaluar(doc).cabe, presupuesto.medir(doc))

    def test_un_exito_reinicia_el_contador_de_intentos(self):
        self.init_git()
        self.borrador("## Estado\n" + "x\n" * 300)
        self.baton("escribir", "--modo", "memoria")
        self.borrador("## Estado\nbreve\n")
        self.assertEqual(self.baton("escribir", "--modo", "memoria").returncode, OK)
        self.borrador("## Estado\n" + "x\n" * 300)
        p = self.baton("escribir", "--modo", "memoria")
        self.assertIn("Intento 1 de 3", p.stderr, "el contador no se reinicio tras el exito")

    def test_modo_invalido_se_rechaza(self):
        self.borrador("## Estado\nx\n")
        p = self.baton("escribir", "--modo", "loquesea")
        self.assertNotEqual(p.returncode, OK)

    def test_escribir_activa_el_proyecto(self):
        sys.path.insert(0, str(RAIZ_REPO))
        from lib import almacen
        self.assertFalse(almacen.esta_activado(self.proyecto))
        self.borrador("## Estado\nx\n")
        self.baton("escribir", "--modo", "memoria")
        self.assertTrue(almacen.esta_activado(self.proyecto))


if __name__ == "__main__":
    unittest.main()
