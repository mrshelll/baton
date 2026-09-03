"""PostCompact captura, Stop pide. El automatismo que cubre lo que no controlas."""
import json
import sys
import unittest

from tests.ayudas import RAIZ_REPO, CasoBase

sys.path.insert(0, str(RAIZ_REPO))
from lib import almacen  # noqa: E402


class Base(CasoBase):
    def activar(self, contenido="---\nbaton: 1\nmodo: memoria\n---\n## Estado\nx\n"):
        r = almacen.Rutas(self.proyecto)
        r.documento.parent.mkdir(parents=True, exist_ok=True)
        r.documento.write_text(contenido, encoding="utf-8")
        return r

    def compactar(self, resumen="Resumen de la conversacion: se migro Stripe.", trigger="auto"):
        return self.correr_hook("post-compact", self.payload(
            "PostCompact", trigger=trigger, compact_summary=resumen))

    def parar(self, activo=False, **extra):
        return self.correr_hook("stop", self.payload(
            "Stop", stop_hook_active=activo, **extra))

    def pendiente(self):
        r = almacen.Rutas(self.proyecto)
        return json.loads(r.pendiente.read_text(encoding="utf-8")) if r.pendiente.exists() else None


class TestPostCompact(Base):
    def test_sin_activar_no_hace_nada(self):
        rc, out, _ = self.compactar()
        self.assertEqual(rc, 0)
        self.assertIsNone(self.pendiente())

    def test_guarda_el_resumen_y_arma_la_bandera(self):
        self.activar()
        rc, out, err = self.compactar("Resumen: canario xilofono-7731")
        self.assertEqual(rc, 0, err)
        r = almacen.Rutas(self.proyecto)
        guardados = list(r.auto.glob("resumen-*.md"))
        self.assertEqual(len(guardados), 1)
        self.assertIn("xilofono-7731", guardados[0].read_text(encoding="utf-8"))
        self.assertIsNotNone(self.pendiente())

    def test_no_toca_el_traspaso_jamas(self):
        # Un resumen que nadie redactó no puede pisar un traspaso escrito con
        # criterio. Es la regla que evita el peor fallo posible.
        r = self.activar("---\nbaton: 1\nmodo: continuacion\n---\n## Estado\nmio\n")
        antes = r.documento.read_bytes()
        self.compactar()
        self.assertEqual(r.documento.read_bytes(), antes)

    def test_solo_conserva_los_ultimos_tres_resumenes(self):
        self.activar()
        for i in range(5):
            self.compactar(f"resumen numero {i}")
        r = almacen.Rutas(self.proyecto)
        self.assertLessEqual(len(list(r.auto.glob("resumen-*.md"))), 3)

    def test_sin_resumen_en_el_payload_no_revienta(self):
        self.activar()
        rc, _, err = self.correr_hook("post-compact", self.payload("PostCompact", trigger="auto"))
        self.assertEqual(rc, 0, err)


class TestStop(Base):
    def test_sin_bandera_calla(self):
        self.activar()
        rc, out, _ = self.parar()
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_sin_activar_calla_aunque_hubiera_bandera(self):
        rc, out, _ = self.parar()
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_con_bandera_pide_el_traspaso(self):
        self.activar()
        self.compactar()
        rc, out, err = self.parar()
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("baton", out.get("reason", "").lower())

    def test_stop_hook_active_lo_desactiva(self):
        # Anti-bucle nativo del harness: si ya estamos dentro de un Stop
        # bloqueado, no se puede volver a bloquear.
        self.activar()
        self.compactar()
        rc, out, _ = self.parar(activo=True)
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_solo_pide_una_vez_por_compactacion(self):
        self.activar()
        self.compactar()
        _, primera, _ = self.parar()
        self.assertEqual(primera.get("decision"), "block")
        _, segunda, _ = self.parar()
        self.assertIsNone(segunda, "no puede pedirlo dos veces por una compactacion")

    def test_consume_la_bandera_aunque_el_modelo_no_escriba(self):
        self.activar()
        self.compactar()
        self.parar()
        p = self.pendiente()
        self.assertTrue(p is None or p.get("pedido"), "la bandera debe quedar consumida")

    def test_otra_compactacion_dentro_del_cooldown_no_vuelve_a_interrumpir(self):
        # Dos compactaciones seguidas no son dos motivos para interrumpir: lo
        # que el cooldown protege es al usuario, no a la compactacion.
        self.activar()
        self.compactar(); self.parar()
        self.compactar()
        _, out, _ = self.parar()
        self.assertIsNone(out)

    def test_otra_compactacion_pasado_el_cooldown_si_lo_pide(self):
        self.activar()
        claude = self.proyecto / ".claude"; claude.mkdir(exist_ok=True)
        (claude / "baton.json").write_text(json.dumps({"cooldown_minutos": 0}),
                                           encoding="utf-8")
        self.compactar(); self.parar()
        self.compactar()
        _, out, _ = self.parar()
        self.assertEqual(out.get("decision"), "block")

    def test_el_cooldown_impide_pedirlo_seguido(self):
        self.activar()
        claude = self.proyecto / ".claude"; claude.mkdir(exist_ok=True)
        (claude / "baton.json").write_text(json.dumps({"cooldown_minutos": 999}),
                                           encoding="utf-8")
        self.compactar(); self.parar()
        self.compactar()
        _, out, _ = self.parar()
        self.assertIsNone(out, "el cooldown deberia haberlo frenado")

    def test_stdin_corrupto_sale_cero(self):
        self.activar()
        rc, _, err = self.correr_hook("stop", None, entrada_cruda="{roto")
        self.assertEqual(rc, 0, err)


if __name__ == "__main__":
    unittest.main()
