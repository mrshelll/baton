"""El README es la cara del proyecto: sus diagramas tienen que estar bien formados.

Comprobacion ligera y sin dependencias. La validacion de verdad, contra el parser
de Mermaid, esta en tools/validar-mermaid.mjs.
"""
import re
import unittest

from tests.ayudas import RAIZ_REPO

# Tipos que GitHub renderiza. Si anades uno nuevo, validalo antes con
# tools/validar-mermaid.mjs.
TIPOS = ("flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram",
         "erDiagram", "journey", "gantt", "pie", "gitGraph", "mindmap", "timeline",
         "xychart-beta", "block-beta", "quadrantChart", "sankey-beta")


class TestReadme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texto = (RAIZ_REPO / "README.md").read_text(encoding="utf-8")
        cls.bloques = re.findall(r"```mermaid\n(.*?)```", cls.texto, re.DOTALL)

    def test_hay_diagramas(self):
        self.assertGreaterEqual(len(self.bloques), 4)

    def test_todos_los_bloques_cierran(self):
        self.assertEqual(self.texto.count("```mermaid"), len(self.bloques),
                         "hay un bloque mermaid sin cerrar")

    def test_cada_diagrama_declara_un_tipo_conocido(self):
        for i, bloque in enumerate(self.bloques, 1):
            with self.subTest(diagrama=i):
                primera = bloque.strip().split("\n")[0].strip()
                self.assertTrue(primera.startswith(TIPOS),
                                f"tipo desconocido: {primera!r}")

    def test_los_bloques_de_codigo_estan_balanceados(self):
        self.assertEqual(self.texto.count("```") % 2, 0, "hay una valla ``` sin pareja")

    def test_menciona_el_reinicio_tras_instalar(self):
        # Es el error numero uno; si desaparece del README, vuelve a pasar.
        self.assertIn("Reinicia Claude Code", self.texto)


if __name__ == "__main__":
    unittest.main()
