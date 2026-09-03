"""Escritura atomica, lock y rotacion del historial."""
import subprocess
import sys
import textwrap
import time
import unittest

from tests.ayudas import RAIZ_REPO, CasoBase, _sin_locale

sys.path.insert(0, str(RAIZ_REPO))
from lib import almacen  # noqa: E402


class TestEscrituraAtomica(CasoBase):
    def rutas(self):
        return almacen.Rutas(self.proyecto)

    def test_primera_escritura_crea_el_arbol(self):
        r = self.rutas()
        almacen.escribir_documento(r, "contenido\n", historial_max=10)
        self.assertTrue(r.documento.is_file())
        self.assertEqual(r.documento.read_text(encoding="utf-8"), "contenido\n")
        self.assertFalse(any(r.historial.glob("*.md")), "la primera no rota nada")

    def test_la_segunda_manda_la_anterior_al_historial(self):
        r = self.rutas()
        # Documentos reales: el modo del nombre sale del que se archiva.
        almacen.escribir_documento(r, "---\nbaton: 1\nmodo: memoria\n---\nprimera\n", historial_max=10)
        almacen.escribir_documento(r, "---\nbaton: 1\nmodo: continuacion\n---\nsegunda\n", historial_max=10)
        self.assertIn("segunda", r.documento.read_text(encoding="utf-8"))
        guardados = sorted(r.historial.glob("*.md"))
        self.assertEqual(len(guardados), 1)
        self.assertIn("primera", guardados[0].read_text(encoding="utf-8"))
        self.assertIn("memoria", guardados[0].name,
                      "el nombre lleva el modo del documento ARCHIVADO, no el del nuevo")

    def test_se_conservan_exactamente_los_ultimos_diez(self):
        r = self.rutas()
        for i in range(12):
            almacen.escribir_documento(r, f"v{i}\n", historial_max=10)
        self.assertEqual(len(list(r.historial.glob("*.md"))), 10)

    def test_historial_cero_no_guarda_nada(self):
        r = self.rutas()
        almacen.escribir_documento(r, "a\n", historial_max=0)
        almacen.escribir_documento(r, "b\n", historial_max=0)
        self.assertFalse(list(r.historial.glob("*.md")))

    def test_nunca_borra_ficheros_ajenos(self):
        # Un plugin que borra ficheros necesita no poder equivocarse.
        r = self.rutas()
        r.historial.mkdir(parents=True, exist_ok=True)
        intruso = r.historial / "notas.md"
        intruso.write_text("mis notas a mano\n", encoding="utf-8")
        for i in range(15):
            almacen.escribir_documento(r, f"v{i}\n", historial_max=3)
        self.assertTrue(intruso.is_file(), "baton ha borrado un fichero que no es suyo")
        self.assertEqual(intruso.read_text(encoding="utf-8"), "mis notas a mano\n")

    def test_colision_en_el_mismo_segundo_no_pisa(self):
        r = self.rutas()
        almacen.escribir_documento(r, "uno\n", historial_max=10)
        for i in range(3):
            almacen.escribir_documento(r, f"n{i}\n", historial_max=10)
        nombres = {p.name for p in r.historial.glob("*.md")}
        self.assertEqual(len(nombres), 3, "cada rotacion necesita su propio nombre")

    def test_el_borrador_se_borra_al_escribir_con_exito(self):
        r = self.rutas()
        r.asegurar_local()
        r.borrador.write_text("## Estado\nx\n", encoding="utf-8")
        almacen.escribir_documento(r, "final\n", historial_max=10)
        self.assertFalse(r.borrador.exists())


class TestLock(CasoBase):
    def test_dos_escritores_a_la_vez_no_mezclan(self):
        # El fichero final tiene que ser uno de los dos ENTERO, nunca a medias.
        guion = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(RAIZ_REPO)!r})
            from lib import almacen
            r = almacen.Rutas({str(self.proyecto)!r})
            contenido = sys.argv[1] * 20000 + "\\n"
            try:
                almacen.escribir_documento(r, contenido, historial_max=5)
                print("ok")
            except almacen.OcupadoError:
                print("ocupado")
        """)
        procs = [subprocess.Popen([sys.executable, "-c", guion, letra],
                                  stdout=subprocess.PIPE, text=True, env=_sin_locale())
                 for letra in ("A", "B")]
        salidas = [p.communicate()[0].strip() for p in procs]
        self.assertIn("ok", salidas)
        final = almacen.Rutas(self.proyecto).documento.read_text(encoding="utf-8")
        self.assertIn(final, ("A" * 20000 + "\n", "B" * 20000 + "\n"),
                      "el documento ha quedado mezclado")

    def test_lock_caducado_se_puede_robar(self):
        r = almacen.Rutas(self.proyecto)
        r.asegurar_local()
        r.lock.write_text("proceso zombi", encoding="utf-8")
        viejo = time.time() - (almacen.LOCK_CADUCA_SEGUNDOS + 30)
        import os
        os.utime(r.lock, (viejo, viejo))
        almacen.escribir_documento(r, "pude escribir\n", historial_max=5)
        self.assertEqual(r.documento.read_text(encoding="utf-8"), "pude escribir\n")

    def test_lock_vivo_bloquea(self):
        r = almacen.Rutas(self.proyecto)
        r.asegurar_local()
        r.lock.write_text("otro proceso", encoding="utf-8")
        with self.assertRaises(almacen.OcupadoError):
            almacen.escribir_documento(r, "no deberia\n", historial_max=5)


class TestErroresDeEntorno(CasoBase):
    def test_sin_permisos_lanza_error_de_entorno_no_traceback(self):
        import os
        r = almacen.Rutas(self.proyecto)
        r.baton.mkdir(parents=True)
        os.chmod(r.baton, 0o500)
        self.addCleanup(os.chmod, r.baton, 0o700)
        with self.assertRaises(almacen.EntornoError):
            almacen.escribir_documento(r, "x\n", historial_max=5)


if __name__ == "__main__":
    unittest.main()
