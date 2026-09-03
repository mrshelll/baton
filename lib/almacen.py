"""Rutas, activacion y bitacora de baton.

Todo lo que toca el disco dentro del proyecto pasa por aqui. Dos reglas que se
repiten en el resto del codigo y nacen en este modulo:

1. Nada de lo que hay aqui puede lanzar hacia un hook. Un traspaso roto no
   puede impedir que arranque una sesion.
2. Todo lo volatil cuelga de `.baton/local/`, para que el usuario tenga UNA
   sola linea que poner en su .gitignore.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from lib import documento

#: Hasta donde subimos buscando la raiz del proyecto. Un tope evita que un cwd
#: raro nos haga recorrer el disco entero en el arranque de cada sesion.
MAX_NIVELES = 20

#: Marcas que identifican la raiz de un proyecto, en orden de prioridad.
MARCAS_RAIZ = (".git", ".claude", ".baton")

#: La bitacora es una prueba forense, no un log: se capa y no se rota.
BITACORA_MAX_LINEAS = 200


def raiz_proyecto(cwd) -> Path:
    """Sube desde `cwd` hasta encontrar la raiz del proyecto.

    `.git` vale tanto si es directorio como si es fichero: en un worktree de git
    es un fichero que apunta al repo real, y tratarlo solo como directorio deja
    fuera a quien trabaja con worktrees.

    Si no encuentra ninguna marca devuelve el propio `cwd`: es mejor operar en
    el directorio actual que fallar. Nunca lanza.
    """
    actual = Path(cwd)
    try:
        actual = actual.resolve(strict=False)
    except OSError:
        pass
    for _ in range(MAX_NIVELES):
        for marca in MARCAS_RAIZ:
            if (actual / marca).exists():
                return actual
        if actual.parent == actual:
            break
        actual = actual.parent
    try:
        return Path(cwd).resolve(strict=False)
    except OSError:
        return Path(cwd)


class Rutas:
    """Las rutas de baton dentro de un proyecto. Solo las calcula; no crea nada
    salvo que se lo pidas explicitamente."""

    def __init__(self, raiz, documento_rel: str = ".baton/TRASPASO.md"):
        self.raiz = Path(raiz)
        self.documento = self.raiz / documento_rel
        # Lo volatil cuelga SIEMPRE de .baton/local/, aunque el documento se
        # haya movido a otro sitio: asi el .gitignore sigue siendo una linea.
        self.baton = self.raiz / ".baton"
        self.local = self.baton / "local"
        self.historial = self.local / "historial"
        self.auto = self.local / "auto"
        self.borrador = self.local / "borrador.md"
        self.entregas = self.local / "entregas.json"
        self.intentos = self.local / "intentos.json"
        self.pendiente = self.local / "pendiente.json"
        self.bitacora = self.local / "bitacora.jsonl"
        self.lock = self.local / ".lock"

    def asegurar_local(self) -> None:
        self.local.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:  # pragma: no cover - ayuda al depurar
        return f"Rutas({self.raiz!s})"


def esta_activado(raiz) -> bool:
    """Un proyecto esta activado cuando existe su documento de traspaso.

    baton se instala a nivel de usuario, asi que corre en TODOS los proyectos.
    Sembrar ficheros en cada repo que alguien abre es intrusivo, y el propio
    documento es la senal mas limpia de que se quiso usar aqui: sin comando de
    init y sin un registro global que se desincronice al mover carpetas.
    """
    try:
        return Rutas(raiz).documento.is_file()
    except OSError:
        return False


def ahora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def desde_utc(texto):
    """La inversa de `ahora_utc`. None si no es una marca nuestra.

    Devolver None en vez de lanzar es lo que permite tratar una nota corrupta
    como una nota ausente, que es justo lo que hay que hacer con ella.
    """
    try:
        return datetime.strptime(texto or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _leer_json(ruta: Path) -> dict:
    """Lee una nota de estado (entregas, pendiente).

    Todo lo que pueda salir mal -que no exista, que este corrupta, que no sea
    un objeto- vale {}: ninguna de estas notas justifica un fallo.
    """
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return datos if isinstance(datos, dict) else {}


def _guardar_json(ruta: Path, datos: dict) -> None:
    """Escribe una nota de estado. Si no se puede, se pierde y ya."""
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos), encoding="utf-8")
    except OSError:
        pass


def anotar(rutas: Rutas, evento: str, resultado: str, **extra) -> None:
    """Deja constancia de que un hook corrio.

    Es lo unico que distingue "el hook no disparo" de "disparo y callo porque no
    habia documento": dos situaciones identicas desde fuera y con causas
    opuestas. Por eso se anota SIEMPRE, incluido el camino de silencio.

    Nunca lanza: si no se puede escribir, se pierde la anotacion y ya.
    """
    linea = {"ts": ahora_utc(), "evento": evento, "resultado": resultado}
    linea.update(extra)
    try:
        rutas.asegurar_local()
        previas = []
        if rutas.bitacora.exists():
            texto = rutas.bitacora.read_text(encoding="utf-8", errors="replace")
            previas = [l for l in texto.split("\n") if l.strip()]
        previas.append(json.dumps(linea, ensure_ascii=False))
        recortadas = previas[-BITACORA_MAX_LINEAS:]
        tmp = rutas.bitacora.with_suffix(f".jsonl.tmp-{os.getpid()}")
        tmp.write_text("\n".join(recortadas) + "\n", encoding="utf-8")
        os.replace(tmp, rutas.bitacora)
    except Exception:
        pass


# --- escritura del documento ----------------------------------------------

#: Un lock huerfano (proceso muerto, portatil suspendido) no puede dejar el
#: proyecto bloqueado para siempre. Pasado este tiempo se considera basura.
LOCK_CADUCA_SEGUNDOS = 60

#: Solo se borran del historial los ficheros que casan EXACTAMENTE con esto.
#: Si alguien deja sus propias notas ahi, baton no las toca.
RE_HISTORIAL = re.compile(r"^TRASPASO-\d{8}T\d{6}Z-(continuacion|memoria)(?:-\d+)?\.md$")


class OcupadoError(RuntimeError):
    """Otra sesion esta escribiendo el traspaso ahora mismo."""


class EntornoError(RuntimeError):
    """No se puede escribir: permisos, disco, ruta imposible."""


#: Mismo texto tanto si el lock esta vivo como si perdemos la carrera por
#: robarlo: para quien llama es la misma situacion y el mismo remedio.
_OCUPADO = "otra sesion esta escribiendo el traspaso; vuelve a intentarlo"


class _Lock:
    """Lock por fichero, con caducidad.

    O_CREAT|O_EXCL es atomico en POSIX y en Windows, asi que dos procesos no
    pueden crearlo a la vez. La caducidad existe porque un lock sin ella
    convierte cualquier proceso muerto en un bloqueo permanente.
    """

    def __init__(self, ruta: Path):
        self.ruta = ruta
        self._mio = False

    def __enter__(self):
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise EntornoError(f"no puedo crear {self.ruta.parent}: {exc}") from exc
        if self._tomar():
            return self
        if self._edad() <= LOCK_CADUCA_SEGUNDOS:
            raise OcupadoError(_OCUPADO)
        self.ruta.unlink(missing_ok=True)  # lock caducado: se roba
        if not self._tomar():  # alguien se nos adelanto al robarlo
            raise OcupadoError(_OCUPADO)
        return self

    def __exit__(self, *exc):
        if self._mio:
            try:
                self.ruta.unlink(missing_ok=True)
            except OSError:
                pass
        return False

    def _tomar(self) -> bool:
        """Crea el lock. False si ya existia; EntornoError si no se pudo."""
        try:
            fd = os.open(self.ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError:
            return False
        except OSError as exc:
            raise EntornoError(f"no puedo bloquear {self.ruta}: {exc}") from exc
        self._mio = True
        return True

    def _edad(self) -> float:
        """Segundos desde que se creo el lock. Sin mtime vale 0, que equivale a
        considerarlo vivo: no se roba un lock sin pruebas de que caduco."""
        try:
            return time.time() - self.ruta.stat().st_mtime
        except OSError:
            return 0


def _marca_utc() -> str:
    """UTC a proposito: el orden alfabetico es el cronologico, sin sorpresas
    por husos horarios ni por el cambio de hora."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _destino_libre(carpeta: Path, nombre: str) -> Path:
    """`carpeta/nombre`, con -2, -3... si ya existe.

    Dos escrituras dentro del mismo segundo comparten marca de tiempo, y la
    segunda no puede pisar a la primera.
    """
    destino = carpeta / nombre
    tronco, extension = destino.stem, destino.suffix
    sufijo = 2
    while destino.exists():
        destino = carpeta / f"{tronco}-{sufijo}{extension}"
        sufijo += 1
    return destino


def _rotar(rutas: "Rutas", historial_max: int) -> None:
    """Archiva el documento ACTUAL antes de sustituirlo.

    El modo del nombre se lee del fichero que se archiva, no del que va a
    entrar: quien busca "el ultimo traspaso de continuacion" quiere el modo con
    el que se escribio aquel, no el del que lo reemplaza.
    """
    if historial_max <= 0 or not rutas.documento.is_file():
        return
    try:
        modo = documento.leer_modo(rutas.documento.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        modo = documento.MODO_SEGURO
    rutas.historial.mkdir(parents=True, exist_ok=True)
    destino = _destino_libre(rutas.historial, f"TRASPASO-{_marca_utc()}-{modo}.md")
    shutil.copy2(rutas.documento, destino)
    _podar(rutas, historial_max)


def _podar(rutas: "Rutas", historial_max: int) -> None:
    """`historial_max` siempre llega > 0: con 0 `_rotar` ni siquiera archiva."""
    mios = sorted(p for p in rutas.historial.glob("*.md") if RE_HISTORIAL.match(p.name))
    for viejo in mios[:-historial_max]:
        try:
            viejo.unlink()
        except OSError:
            pass


def escribir_documento(rutas: "Rutas", contenido: str, historial_max: int = 10) -> Path:
    """Escribe el traspaso de forma atomica, rotando el anterior.

    El orden importa: nada se toca hasta que el contenido esta listo, y el
    fichero final aparece de una vez con os.replace(). Un lector concurrente ve
    el documento viejo entero o el nuevo entero, nunca uno a medias.
    """
    with _Lock(rutas.lock):
        try:
            rutas.documento.parent.mkdir(parents=True, exist_ok=True)
            _rotar(rutas, historial_max)
            tmp = rutas.documento.with_name(f".{rutas.documento.name}.tmp-{os.getpid()}")
            tmp.write_text(contenido, encoding="utf-8")
            os.replace(tmp, rutas.documento)
        except OSError as exc:
            raise EntornoError(f"no puedo escribir {rutas.documento}: {exc}") from exc
        try:
            rutas.borrador.unlink(missing_ok=True)
            rutas.intentos.unlink(missing_ok=True)
        except OSError:
            pass
    return rutas.documento


# --- registro de entregas -------------------------------------------------

def registrar_entrega(rutas: "Rutas", huella: str, cuenta: bool = True):
    """Lleva la cuenta de cuantas veces se ha entregado ESTE traspaso.

    Sirve para poder decirle al modelo "esto ya te lo di 3 veces": sin ese
    aviso, un traspaso que nadie ha reemplazado parece novedad en cada sesion y
    el modelo repite trabajo ya hecho.

    Nunca destruye la nota al leerla. Muchas sesiones arrancan y terminan sin
    escribir un traspaso nuevo -- una invocacion de un solo tiro, por ejemplo-,
    y consumir la nota ahi dejaria sin contexto a la siguiente sesion humana.

    Devuelve None la primera vez, o {"veces": N, "cuando": "..."} si repite.
    """
    datos = _leer_json(rutas.entregas)
    if datos.get("huella") != huella:
        datos = {"huella": huella, "veces": 0, "primera": ahora_utc(), "ultima": ""}

    previas = int(datos.get("veces") or 0)
    anterior = datos.get("ultima") or datos.get("primera") or ""

    if cuenta:
        datos["veces"] = previas + 1
        datos["ultima"] = ahora_utc()
        _guardar_json(rutas.entregas, datos)

    if previas <= 0:
        return None
    return {"veces": previas, "cuando": anterior or "antes"}


# --- ciclo automatico: resumen de compactacion y bandera ------------------

#: Cuantos resumenes de compactacion se conservan. Son material de trabajo, no
#: un archivo historico: con los ultimos basta y el coste queda acotado.
RESUMENES_MAX = 3


def guardar_resumen(rutas: "Rutas", resumen: str, trigger: str = "auto") -> None:
    """Deja el `compact_summary` en disco para que se pueda usar despues."""
    try:
        rutas.auto.mkdir(parents=True, exist_ok=True)
        destino = _destino_libre(rutas.auto, f"resumen-{_marca_utc()}.md")
        destino.write_text(
            f"<!-- resumen de compactacion (trigger: {trigger}), guardado por baton -->\n\n"
            + (resumen or "(la compactacion no aporto resumen)\n"),
            encoding="utf-8")
        guardados = sorted(rutas.auto.glob("resumen-*.md"))
        for viejo in guardados[:-RESUMENES_MAX]:
            viejo.unlink(missing_ok=True)
    except OSError:
        pass


def armar_pendiente(rutas: "Rutas", session_id: str = "") -> None:
    """Marca que hay una compactacion sin traspaso.

    Conserva `ultima_peticion` a proposito: el cooldown mide desde la ultima
    vez que se interrumpio al usuario, y si se borrara aqui, cada compactacion
    nueva lo reiniciaria y el cooldown no frenaria nada.
    """
    datos = _leer_json(rutas.pendiente)
    datos.update({"armada": ahora_utc(), "session": session_id, "pedido": False})
    _guardar_json(rutas.pendiente, datos)


def hay_pendiente(rutas: "Rutas", cooldown_minutos: int = 30) -> bool:
    """True si toca pedir el traspaso.

    El cooldown mide desde la ULTIMA peticion, no desde la compactacion: lo que
    hay que evitar es interrumpir dos veces seguidas al usuario, no perder una
    compactacion.
    """
    datos = _leer_json(rutas.pendiente)
    if not datos or datos.get("pedido"):
        return False
    ultima = desde_utc(datos.get("ultima_peticion"))
    if ultima and cooldown_minutos:
        transcurrido = (datetime.now(timezone.utc) - ultima).total_seconds()
        return transcurrido >= cooldown_minutos * 60
    return True


def consumir_pendiente(rutas: "Rutas") -> None:
    """Marca la bandera como usada. Como mucho una peticion por compactacion."""
    datos = _leer_json(rutas.pendiente)
    datos.update({"pedido": True, "ultima_peticion": ahora_utc()})
    _guardar_json(rutas.pendiente, datos)
