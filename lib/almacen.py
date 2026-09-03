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
from datetime import datetime, timezone
from pathlib import Path

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

    def __init__(self, raiz, nombre_documento: str = "TRASPASO.md"):
        self.raiz = Path(raiz)
        self.baton = self.raiz / ".baton"
        self.documento = self.baton / nombre_documento
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
