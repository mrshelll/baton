"""SessionStart: del fichero al contexto del modelo."""
import json
import sys
import unittest

from tests.ayudas import RAIZ_REPO, CasoBase

sys.path.insert(0, str(RAIZ_REPO))
from lib import almacen, documento, presupuesto, salida  # noqa: E402

T = salida.cargar_textos()


class Base(CasoBase):
    def escribir_traspaso(self, modo="memoria", cuerpo="## Estado\nvamos por aqui\n", **kw):
        campos = dict(fecha="2026-09-03T10:00:00-05:00", rama="main", commit="abc1234")
        campos.update(kw)
        texto = documento.componer(cuerpo=cuerpo, modo=modo,
                                   contexto="- rama `main`, arbol limpio", textos=T, **campos)
        r = almacen.Rutas(self.proyecto)
        r.documento.parent.mkdir(parents=True, exist_ok=True)
        r.documento.write_text(texto, encoding="utf-8")
        return texto

    def arrancar(self, source="startup", **extra):
        return self.correr_hook("session-start",
                                self.payload("SessionStart", source=source, **extra))

    def contexto(self, salida_json):
        return salida_json["hookSpecificOutput"]["additionalContext"]


class TestInyeccion(Base):
    def test_sin_traspaso_calla(self):
        rc, out, _ = self.arrancar()
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_con_traspaso_emite_el_canal_estructurado(self):
        self.escribir_traspaso()
        rc, out, err = self.arrancar()
        self.assertEqual(rc, 0, err)
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("additionalContext", out["hookSpecificOutput"])

    def test_modo_memoria_dice_que_no_inicie_trabajo(self):
        self.escribir_traspaso(modo="memoria")
        _, out, _ = self.arrancar()
        texto = self.contexto(out)
        self.assertIn("NO inicies trabajo", texto)
        self.assertIn("MODO MEMORIA", texto)

    def test_modo_continuacion_pide_retomar(self):
        self.escribir_traspaso(modo="continuacion",
                               cuerpo="## Estado\nx\n## Siguiente paso\nhaz Y\n")
        _, out, _ = self.arrancar()
        texto = self.contexto(out)
        self.assertIn("MODO CONTINUACION", texto)
        self.assertNotIn("NO inicies trabajo", texto)

    def test_lleva_el_contenido_del_traspaso(self):
        self.escribir_traspaso(cuerpo="## Estado\ncanario xilofono-7731\n")
        _, out, _ = self.arrancar()
        self.assertIn("xilofono-7731", self.contexto(out))

    def test_emite_el_recibo(self):
        self.escribir_traspaso()
        _, out, _ = self.arrancar()
        self.assertIn("systemMessage", out)
        self.assertIn("baton", out["systemMessage"])

    def test_nunca_pasa_del_techo_del_harness(self):
        self.escribir_traspaso(cuerpo="## Estado\n" + "linea larga de relleno\n" * 500)
        _, out, _ = self.arrancar()
        texto = self.contexto(out)
        self.assertLessEqual(len(texto), presupuesto.TECHO_CARACTERES)
        self.assertLessEqual(len(texto.split("\n")), presupuesto.TECHO_LINEAS)

    def test_no_modifica_el_documento_al_leerlo(self):
        # Una sesion de un solo tiro no puede consumir la nota destinada a la
        # siguiente sesion humana.
        original = self.escribir_traspaso()
        self.arrancar()
        self.arrancar()
        r = almacen.Rutas(self.proyecto)
        self.assertEqual(r.documento.read_text(encoding="utf-8"), original)

    def test_documento_corrupto_no_rompe_el_arranque(self):
        r = almacen.Rutas(self.proyecto)
        r.documento.parent.mkdir(parents=True, exist_ok=True)
        r.documento.write_bytes(b"\x00\x01\x02 basura binaria \xff\xfe")
        rc, out, err = self.arrancar()
        self.assertEqual(rc, 0, err)

    def test_documento_sin_frontmatter_se_inyecta_como_memoria(self):
        r = almacen.Rutas(self.proyecto)
        r.documento.parent.mkdir(parents=True, exist_ok=True)
        r.documento.write_text("## Estado\nsin cabecera\n", encoding="utf-8")
        _, out, _ = self.arrancar()
        self.assertIn("MODO MEMORIA", self.contexto(out))


class TestFrescuraEnLaInyeccion(Base):
    def test_traspaso_viejo_avisa(self):
        self.escribir_traspaso(fecha="2020-01-01T00:00:00Z")
        _, out, _ = self.arrancar()
        self.assertIn("Aviso de frescura", self.contexto(out))

    def test_traspaso_de_hoy_sin_git_no_gasta_lineas(self):
        import datetime
        hoy = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()
        self.escribir_traspaso(fecha=hoy, rama="sin-git", commit="sin-git")
        _, out, _ = self.arrancar()
        self.assertNotIn("Aviso de frescura", self.contexto(out))


class TestRegistroDeEntregas(Base):
    def test_avisa_cuando_ya_lo_entrego_antes(self):
        self.escribir_traspaso()
        self.arrancar()
        _, out, _ = self.arrancar()
        self.assertIn("ya se te entrego", self.contexto(out))

    def test_la_primera_vez_no_avisa(self):
        self.escribir_traspaso()
        _, out, _ = self.arrancar()
        self.assertNotIn("ya se te entrego", self.contexto(out))

    def test_una_compactacion_no_cuenta_como_sesion_nueva(self):
        self.escribir_traspaso()
        for _ in range(3):
            self.arrancar(source="compact")
        _, out, _ = self.arrancar(source="compact")
        self.assertNotIn("ya se te entrego", self.contexto(out))

    def test_un_traspaso_nuevo_reinicia_la_cuenta(self):
        self.escribir_traspaso(cuerpo="## Estado\nuno\n")
        self.arrancar(); self.arrancar()
        self.escribir_traspaso(cuerpo="## Estado\ndos\n")
        _, out, _ = self.arrancar()
        self.assertNotIn("ya se te entrego", self.contexto(out))


class TestFiltroDeArranques(Base):
    def test_respeta_inyectar_en(self):
        self.escribir_traspaso()
        claude = self.proyecto / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "baton.json").write_text(json.dumps({"inyectar_en": ["startup"]}),
                                           encoding="utf-8")
        _, con, _ = self.arrancar(source="startup")
        self.assertIsNotNone(con)
        _, sin, _ = self.arrancar(source="resume")
        self.assertIsNone(sin, "resume estaba excluido por config")


if __name__ == "__main__":
    unittest.main()
