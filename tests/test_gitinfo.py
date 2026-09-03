"""git: snapshot determinista y aviso de frescura. Degradar siempre, nunca lanzar."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.ayudas import RAIZ_REPO, CasoBase

sys.path.insert(0, str(RAIZ_REPO))
from lib import gitinfo  # noqa: E402


class SinGit:
    """Deja el PATH sin `git`, para probar el camino degradado de verdad."""

    def __enter__(self):
        self._path = os.environ.get("PATH", "")
        self._vacio = tempfile.mkdtemp(prefix="baton-sin-git-")
        os.environ["PATH"] = self._vacio
        gitinfo.limpiar_cache_git()
        return self

    def __exit__(self, *exc):
        os.environ["PATH"] = self._path
        shutil.rmtree(self._vacio, ignore_errors=True)
        gitinfo.limpiar_cache_git()


class TestSnapshot(CasoBase):
    def test_repo_limpio(self):
        self.init_git()
        s = gitinfo.snapshot(self.proyecto)
        self.assertTrue(s.hay_git)
        self.assertEqual(s.rama, "main")
        self.assertEqual(len(s.commit), 7)
        self.assertEqual(s.sucios, [])

    def test_ficheros_sin_commitear_aparecen(self):
        self.init_git()
        for nombre in ("a.txt", "b.txt", "c.txt"):
            (self.proyecto / nombre).write_text("x", encoding="utf-8")
        s = gitinfo.snapshot(self.proyecto)
        self.assertEqual(len(s.sucios), 3)
        self.assertIn("a.txt", s.sucios)

    def test_nombres_con_espacios_y_tildes(self):
        self.init_git()
        (self.proyecto / "un fichero con ñ y tildé.txt").write_text("x", encoding="utf-8")
        s = gitinfo.snapshot(self.proyecto)
        self.assertIn("un fichero con ñ y tildé.txt", s.sucios)

    def test_muchos_sucios_se_resumen(self):
        self.init_git()
        for i in range(30):
            (self.proyecto / f"f{i:02d}.txt").write_text("x", encoding="utf-8")
        s = gitinfo.snapshot(self.proyecto)
        bloque = gitinfo.bloque_contexto(s)
        self.assertLessEqual(len(bloque.split("\n")), 7, bloque)
        self.assertIn("+20 mas", bloque)

    def test_repo_sin_commits_no_revienta(self):
        self.init_git(commit=False)
        s = gitinfo.snapshot(self.proyecto)
        self.assertTrue(s.hay_git)
        self.assertEqual(s.commit, "sin-commits")

    def test_directorio_que_no_es_repo(self):
        s = gitinfo.snapshot(self.proyecto)
        self.assertFalse(s.hay_git)
        self.assertEqual(s.rama, "sin-git")
        self.assertEqual(s.commit, "sin-git")

    def test_sin_git_en_el_path(self):
        self.init_git()
        with SinGit():
            s = gitinfo.snapshot(self.proyecto)
        self.assertFalse(s.hay_git)
        self.assertEqual(s.commit, "sin-git")

    def test_el_bloque_de_contexto_nunca_pasa_de_seis_lineas(self):
        self.init_git()
        s = gitinfo.snapshot(self.proyecto)
        self.assertLessEqual(len(gitinfo.bloque_contexto(s).split("\n")), 6)


class TestFrescura(CasoBase):
    def test_documento_al_dia_no_dice_nada(self):
        self.init_git()
        s = gitinfo.snapshot(self.proyecto)
        f = gitinfo.frescura(self.proyecto, gitinfo.ahora_iso(), s.rama, s.commit)
        self.assertEqual(f.aviso(), "")

    def test_commits_nuevos_se_cuentan(self):
        self.init_git()
        viejo = gitinfo.snapshot(self.proyecto).commit
        for i in range(3):
            (self.proyecto / f"n{i}.txt").write_text("x", encoding="utf-8")
            self.git("add", "-A")
            self.git("commit", "-q", "-m", f"c{i}")
        f = gitinfo.frescura(self.proyecto, gitinfo.ahora_iso(), "main", viejo)
        self.assertEqual(f.commits_nuevos, 3)
        self.assertIn("3 commits", f.aviso())

    def test_rama_distinta_nombra_las_dos(self):
        self.init_git()
        s = gitinfo.snapshot(self.proyecto)
        f = gitinfo.frescura(self.proyecto, gitinfo.ahora_iso(), "otra-rama", s.commit)
        self.assertIn("otra-rama", f.aviso())
        self.assertIn("main", f.aviso())

    def test_commit_desaparecido_avisa_de_rebase(self):
        self.init_git()
        f = gitinfo.frescura(self.proyecto, gitinfo.ahora_iso(), "main", "0" * 7)
        self.assertTrue(f.commit_perdido)
        self.assertIn("ya no existe", f.aviso())

    def test_documento_viejo_dice_la_edad(self):
        self.init_git()
        s = gitinfo.snapshot(self.proyecto)
        f = gitinfo.frescura(self.proyecto, "2020-01-01T00:00:00Z", s.rama, s.commit)
        self.assertIn("dias", f.aviso())

    def test_sin_git_solo_puede_hablar_de_la_edad(self):
        f = gitinfo.frescura(self.proyecto, "2020-01-01T00:00:00Z", "main", "abc1234")
        aviso = f.aviso()
        self.assertIn("dias", aviso)
        self.assertIn("no es un repositorio git", aviso)

    def test_fecha_ilegible_no_revienta(self):
        self.init_git()
        f = gitinfo.frescura(self.proyecto, "ayer por la tarde", "main", "abc1234")
        self.assertIsInstance(f.aviso(), str)


if __name__ == "__main__":
    unittest.main()


class TestNoSeCuentaASiMismo(CasoBase):
    def test_los_ficheros_de_baton_no_son_trabajo_del_usuario(self):
        self.init_git()
        (self.proyecto / ".baton" / "local").mkdir(parents=True)
        (self.proyecto / ".baton" / "TRASPASO.md").write_text("x", encoding="utf-8")
        (self.proyecto / "codigo.py").write_text("y", encoding="utf-8")
        s = gitinfo.snapshot(self.proyecto)
        self.assertEqual(s.sucios, ["codigo.py"])

    def test_la_frescura_tampoco_cuenta_los_ficheros_de_baton(self):
        self.init_git()
        viejo = gitinfo.snapshot(self.proyecto).commit
        (self.proyecto / ".baton").mkdir()
        (self.proyecto / ".baton" / "TRASPASO.md").write_text("x", encoding="utf-8")
        (self.proyecto / "codigo.py").write_text("y", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "cambios")
        f = gitinfo.frescura(self.proyecto, gitinfo.ahora_iso(), "main", viejo)
        self.assertEqual(f.ficheros_cambiados, 1, "solo codigo.py es trabajo del usuario")
