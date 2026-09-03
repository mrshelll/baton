"""Todo lo que baton sabe de git. Y solo aqui.

Dos usos:

1. **Snapshot**: rama, commit y ficheros sin commitear, que van al documento
   generados por CODIGO. El modelo no los escribe, asi que no puede
   equivocarse en ellos ni gastar presupuesto contandolos.
2. **Frescura**: al inyectar, comparar el documento con el repo de ahora y
   avisar de lo que ha cambiado. Avisar, nunca caducar: un proyecto parado dos
   semanas no invalida su traspaso.

Regla del modulo: ninguna funcion lanza y ninguna tarda. Cada llamada a git
lleva timeout, y si git falta o se cuelga se degrada a "sin-git".
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: Un arranque de sesion no puede esperar a un git colgado (repo enorme, disco
#: de red, index bloqueado). Tres segundos y seguimos sin esos datos.
TIMEOUT = 3

#: Cuantos ficheros sucios se nombran antes de resumir. El resto se cuenta.
MAX_SUCIOS = 10

#: Los ficheros del propio baton no son trabajo del usuario. Sin filtrarlos,
#: cada traspaso informaria de que baton acaba de escribir un traspaso, y el
#: aviso de frescura contaria como "codigo que ha cambiado" sus propios
#: ficheros. Ruido en los dos sitios, y por la misma razon.
PREFIJO_PROPIO = ".baton/"


def _es_propio(nombre: str) -> bool:
    return nombre.startswith(PREFIJO_PROPIO)


SIN_GIT = "sin-git"

_hay_git = None


def limpiar_cache_git() -> None:
    """Los tests manipulan el PATH; sin esto la deteccion queda pegada."""
    global _hay_git
    _hay_git = None


def _git_disponible() -> bool:
    global _hay_git
    if _hay_git is None:
        _hay_git = shutil.which("git") is not None
    return _hay_git


def _git(raiz, *args):
    """Ejecuta git y devuelve stdout, o None ante cualquier problema."""
    if not _git_disponible():
        return None
    try:
        p = subprocess.run(
            ("git", "-C", str(raiz)) + args,
            capture_output=True, timeout=TIMEOUT, check=False,
        )
    except Exception:
        return None
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", errors="replace")


def ahora_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Snapshot:
    hay_git: bool
    rama: str
    commit: str
    asunto: str = ""
    fecha_commit: str = ""
    sucios: list = field(default_factory=list)
    adelanto: str = ""


def _cabeza(raiz) -> tuple[str, str, str]:
    """(commit, asunto, fecha) del ultimo commit."""
    salida = _git(raiz, "log", "-1", "--format=%h%x00%s%x00%cs")
    if not salida:
        # Repo recien iniciado: hay git, pero todavia no hay historia.
        return "sin-commits", "", ""
    partes = (salida.strip("\n").split("\0") + ["", "", ""])[:3]
    return partes[0], partes[1], partes[2]


def _sucios(raiz) -> list:
    """Ficheros sin commitear, sin contar los del propio baton.

    -z + separacion por NUL: los nombres con espacios, tildes o saltos de linea
    dejan de ser un caso especial.
    """
    crudo = _git(raiz, "status", "--porcelain=v1", "-z") or ""
    return [e[3:] for e in crudo.split("\0") if len(e) > 3 and not _es_propio(e[3:])]


def _adelanto(raiz) -> str:
    """Como estamos respecto al upstream. Cadena vacia si no hay upstream."""
    conteo = _git(raiz, "rev-list", "--count", "--left-right", "@{upstream}...HEAD")
    if not conteo or "\t" not in conteo:
        return ""
    detras, delante = conteo.strip().split("\t")[:2]
    trozos = []
    if delante != "0":
        trozos.append(f"{delante} commits por delante")
    if detras != "0":
        trozos.append(f"{detras} por detras")
    return " y ".join(trozos)


def snapshot(raiz) -> Snapshot:
    """Los hechos del repo ahora mismo. Sin git, todo queda en 'sin-git'."""
    raiz = Path(raiz)
    if _git(raiz, "rev-parse", "--git-dir") is None:
        return Snapshot(hay_git=False, rama=SIN_GIT, commit=SIN_GIT)
    rama = (_git(raiz, "rev-parse", "--abbrev-ref", "HEAD") or "").strip() or SIN_GIT
    commit, asunto, fecha = _cabeza(raiz)
    return Snapshot(True, rama, commit, asunto, fecha, _sucios(raiz), _adelanto(raiz))


def bloque_contexto(s: Snapshot) -> str:
    """El `## Contexto` del documento. Acotado a 6 lineas por contrato.

    Si un `git status` ruidoso pudiera crecer sin limite, se comeria el
    presupuesto del modelo. Por eso se resume en vez de listarlo todo.
    """
    lineas = []
    if not s.hay_git:
        lineas.append("- sin repositorio git: no hay datos de rama ni de commits")
        return "\n".join(lineas)

    if s.sucios:
        nombres = s.sucios[:MAX_SUCIOS]
        resto = len(s.sucios) - len(nombres)
        listado = ", ".join(nombres) + (f", +{resto} mas" if resto > 0 else "")
        lineas.append(f"- rama `{s.rama}`, {len(s.sucios)} sin commitear: {listado}")
    else:
        lineas.append(f"- rama `{s.rama}`, arbol limpio")

    if s.commit != "sin-commits":
        fecha = f" ({s.fecha_commit})" if s.fecha_commit else ""
        lineas.append(f"- ultimo commit `{s.commit}` {s.asunto}{fecha}".rstrip())
    else:
        lineas.append("- todavia sin commits")

    if s.adelanto:
        lineas.append(f"- {s.adelanto} respecto al remoto")
    return "\n".join(lineas[:6])


@dataclass
class Frescura:
    hay_git: bool
    dias: float | None
    rama_doc: str
    rama_actual: str
    commits_nuevos: int
    ficheros_cambiados: int
    commit_perdido: bool

    def aviso(self) -> str:
        """El texto del aviso, o cadena vacia si no hay nada que decir.

        Que el caso bueno no gaste ni una linea es deliberado: el presupuesto
        es para el traspaso, no para decir que todo esta bien.
        """
        if self.commit_perdido:
            return (
                "[baton] Aviso de frescura: el commit que registro este traspaso ya no "
                "existe en esta rama -- hubo rebase, squash o cambio de rama. No puedo "
                "medir cuanto ha cambiado el codigo desde entonces. Tratalo como una "
                "nota antigua."
            )

        viejo = self.dias is not None and self.dias >= 1
        if not self.hay_git:
            if not viejo:
                return ""
            # Mismo prefijo que los demas avisos: un solo marcador que
            # buscar, en vez de tres redacciones que dicen lo mismo.
            return (
                f"[baton] Aviso de frescura: este proyecto no es un repositorio git "
                f"(o git no esta disponible), asi que solo puedo decirte la edad: el "
                f"traspaso se escribio hace {self.dias:.0f} dias."
            )

        cambio_rama = self.rama_doc not in ("", SIN_GIT) and self.rama_doc != self.rama_actual
        if not (viejo or cambio_rama or self.commits_nuevos):
            return ""

        edad = f"hace {self.dias:.0f} dias" if viejo else "hoy"
        frase = f"[baton] Aviso de frescura: este traspaso se escribio {edad}"
        if cambio_rama:
            frase += f", en la rama `{self.rama_doc}`, y ahora estas en `{self.rama_actual}`"
        if self.commits_nuevos:
            frase += (f". Desde entonces hay {self.commits_nuevos} commits nuevos y "
                      f"{self.ficheros_cambiados} ficheros cambiados")
        return frase + (
            ". Da por incierto lo que diga del estado del codigo: verificalo contra el "
            "repo. Las decisiones y las trampas suelen seguir valiendo; el estado y el "
            "siguiente paso, no."
        )


def _dias_desde(fecha_iso) -> float | None:
    if not isinstance(fecha_iso, str) or not fecha_iso.strip():
        return None
    texto = fecha_iso.strip().replace("Z", "+00:00")
    try:
        cuando = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - cuando).total_seconds() / 86400


def frescura(raiz, fecha_doc, rama_doc, commit_doc) -> Frescura:
    """Compara el documento con el repo de ahora. Nunca lanza."""
    dias = _dias_desde(fecha_doc)
    s = snapshot(raiz)
    if not s.hay_git:
        return Frescura(False, dias, rama_doc or "", SIN_GIT, 0, 0, False)

    perdido = False
    nuevos = cambiados = 0
    if commit_doc and commit_doc not in (SIN_GIT, "sin-commits"):
        if _git(raiz, "cat-file", "-e", f"{commit_doc}^{{commit}}") is None:
            perdido = True
        else:
            salida = _git(raiz, "rev-list", "--count", f"{commit_doc}..HEAD")
            try:
                nuevos = int((salida or "0").strip())
            except ValueError:
                nuevos = 0
            if nuevos:
                lista = _git(raiz, "diff", "--name-only", "-z", f"{commit_doc}..HEAD") or ""
                cambiados = len([x for x in lista.split("\0") if x and not _es_propio(x)])

    return Frescura(True, dias, rama_doc or "", s.rama, nuevos, cambiados, perdido)
