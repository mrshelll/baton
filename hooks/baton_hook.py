#!/usr/bin/env python3
"""Despachador unico de los hooks de baton.

Contrato inviolable, y la razon por la que este fichero existe en vez de tres:
**este proceso SIEMPRE sale con codigo 0**. Un traspaso corrupto, un stdin que
no es JSON o un disco lleno no pueden impedir que arranque una sesion de Claude
Code. Toda la logica va dentro de un `except BaseException` que degrada a un
mensaje legible.

El evento llega como argv[1] (`session-start`, `post-compact`, `stop`) porque
hooks.json usa la forma `command: python3` + `args: [...]`, que no pasa por el
shell y por tanto es inmune a rutas con espacios.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import almacen  # noqa: E402


def _leer_entrada() -> dict:
    """Lee el payload de stdin. Cualquier basura se convierte en {}."""
    try:
        crudo = sys.stdin.read()
    except Exception:
        return {}
    if not crudo or not crudo.strip():
        return {}
    try:
        datos = json.loads(crudo)
    except Exception:
        return {}
    return datos if isinstance(datos, dict) else {}


def _emitir(carga: dict) -> None:
    """Escribe el JSON de salida. Un dict vacio significa silencio."""
    if not carga:
        return
    try:
        sys.stdout.write(json.dumps(carga, ensure_ascii=False))
    except Exception:
        pass


def _aviso(texto: str) -> dict:
    """Un problema de baton se cuenta, no se esconde -- pero nunca bloquea."""
    return {"systemMessage": f"baton: {texto}"}


def _raiz(entrada: dict) -> Path:
    """La raiz del proyecto sale del `cwd` del payload.

    Nunca de os.getcwd(): el directorio de trabajo de un hook no es de fiar.
    """
    cwd = entrada.get("cwd") or os.getcwd()
    return almacen.raiz_proyecto(cwd)


# --- manejadores ---------------------------------------------------------
# Cada uno devuelve (carga_de_salida, resultado_para_la_bitacora).

def _session_start(entrada: dict, rutas: almacen.Rutas) -> tuple[dict, str]:
    if not almacen.esta_activado(rutas.raiz):
        return {}, "silencio: proyecto sin activar"
    return {}, "pendiente: inyeccion no implementada"


def _post_compact(entrada: dict, rutas: almacen.Rutas) -> tuple[dict, str]:
    if not almacen.esta_activado(rutas.raiz):
        return {}, "silencio: proyecto sin activar"
    return {}, "pendiente: captura no implementada"


def _stop(entrada: dict, rutas: almacen.Rutas) -> tuple[dict, str]:
    if not almacen.esta_activado(rutas.raiz):
        return {}, "silencio: proyecto sin activar"
    return {}, "pendiente: peticion no implementada"


MANEJADORES = {
    "session-start": _session_start,
    "post-compact": _post_compact,
    "stop": _stop,
}


def main() -> int:
    evento = sys.argv[1] if len(sys.argv) > 1 else ""
    entrada = _leer_entrada()
    rutas = None
    try:
        manejador = MANEJADORES.get(evento)
        if manejador is None:
            # Un evento que no conocemos no es un error nuestro: callamos.
            return 0
        rutas = almacen.Rutas(_raiz(entrada))
        carga, resultado = manejador(entrada, rutas)
        _emitir(carga)
        almacen.anotar(rutas, evento=evento, resultado=resultado,
                       source=entrada.get("source") or entrada.get("trigger") or "")
    except BaseException as exc:  # noqa: BLE001 - degradar es el requisito
        _emitir(_aviso(
            f"no pude completar '{evento}' ({type(exc).__name__}: {exc}). "
            "La sesion sigue con normalidad."
        ))
        if rutas is not None:
            almacen.anotar(rutas, evento=evento, resultado="error",
                           error=f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
