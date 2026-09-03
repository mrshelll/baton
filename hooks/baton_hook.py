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

from lib import almacen, config, documento, gitinfo, salida  # noqa: E402


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
# Todos reciben (entrada, rutas, cfg) y devuelven
# (carga_de_salida, resultado_para_la_bitacora). `main` solo los llama con el
# proyecto ya activado, asi que ninguno tiene que comprobarlo.

def _session_start(entrada: dict, rutas: almacen.Rutas, cfg: dict) -> tuple[dict, str]:
    """Inyecta el traspaso al arrancar la sesion."""
    origen = entrada.get("source") or "startup"
    if origen not in cfg["inyectar_en"]:
        return {}, f"silencio: '{origen}' no esta en inyectar_en"

    texto = rutas.documento.read_text(encoding="utf-8", errors="replace")
    modo = documento.leer_modo(texto)
    campos = documento.leer_campos(texto)
    textos = salida.cargar_textos()

    aviso = gitinfo.frescura(rutas.raiz, campos.get("fecha"),
                             campos.get("rama", ""), campos.get("commit", "")).aviso()

    # Una compactacion no es una sesion nueva: si contara, el aviso de "esto ya
    # te lo entregue" saltaria por algo que el usuario no hizo.
    repetido = almacen.registrar_entrega(
        rutas, documento.huella(texto, textos["seccion_contexto"]),
        cuenta=(origen != "compact"),
    )

    contexto = salida.envolver(
        documento=documento.extraer_cuerpo(texto, textos["seccion_contexto"]) or texto,
        modo=modo, escrito=campos.get("fecha", "?"),
        origen=str(rutas.documento.relative_to(rutas.raiz)),
        aviso_frescura=aviso, repetido=repetido, textos=textos,
    )

    carga = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                    "additionalContext": contexto}}
    if cfg["recibo"]:
        # El recibo es lo mas barato que convierte un fallo silencioso en uno
        # visible: si no aparece esta linea, el hook no disparo.
        n = len(contexto.split("\n"))
        carga["systemMessage"] = (
            f"baton: traspaso inyectado -- modo {modo}, {n} lineas"
            + (", con aviso de frescura" if aviso else "")
        )
    return carga, f"inyectado modo {modo}"


def _post_compact(entrada: dict, rutas: almacen.Rutas, cfg: dict) -> tuple[dict, str]:
    """Guarda el resumen de la compactacion y arma la bandera. Nada mas.

    Aqui no se puede redactar: en la compactacion no hay turno de modelo, y el
    propio binario lo dice al rechazar los hooks de tipo `prompt` -- "no
    conversation context is available". Lo que si hay es `compact_summary`, el
    resumen que el harness acaba de producir. Se guarda como INSUMO para que el
    siguiente Stop pida un traspaso redactado de verdad.

    Y no toca el traspaso. Jamas: un resumen que nadie redacto no puede pisar
    uno escrito con criterio.
    """
    resumen = entrada.get("compact_summary") or ""
    almacen.guardar_resumen(rutas, resumen, trigger=entrada.get("trigger") or "auto")
    almacen.armar_pendiente(rutas, entrada.get("session_id") or "")
    return {}, "resumen guardado y traspaso pendiente"


def _stop(entrada: dict, rutas: almacen.Rutas, cfg: dict) -> tuple[dict, str]:
    """Pide el traspaso, pero solo en el momento correcto.

    Ese momento es justo despues de una compactacion: el contexto se acaba de
    vaciar, asi que redactar es lo mas barato de toda la sesion. Hacerlo antes,
    al 70-80 % de la ventana, saldria caro y ademas la propia redaccion podria
    disparar la compactacion que se intentaba anticipar.

    Cuatro puertas antes de interrumpir a nadie: proyecto activado (esa la
    mira `main`), `stop_hook_active` falso (anti-bucle del harness), bandera
    armada y cooldown.
    """
    if entrada.get("stop_hook_active"):
        return {}, "silencio: ya estamos dentro de un Stop bloqueado"

    if not almacen.hay_pendiente(rutas, cfg["cooldown_minutos"]):
        return {}, "silencio: nada pendiente"

    # Se consume ANTES de pedirlo: si algo falla despues, como mucho se pierde
    # una peticion. Al reves se pediria en bucle, que es mucho peor.
    almacen.consumir_pendiente(rutas)

    return ({
        "decision": "block",
        "reason": (
            "baton: esta sesion acaba de compactarse, asi que el resumen de la "
            "compactacion sigue fresco en tu contexto y es el mejor momento para "
            "dejar el traspaso al dia.\n\n"
            "Escribe ahora el traspaso siguiendo la skill `baton`: pide el contexto "
            "con `baton.py contexto`, redacta SOLO el cuerpo en el borrador y "
            "escribelo con `baton.py escribir --modo <memoria|continuacion>`. "
            "Destila el resumen, no lo copies: hay un presupuesto y se valida.\n\n"
            "Cuando termines, retoma lo que estabas haciendo o sigue esperando al "
            "usuario, segun corresponda. baton no volvera a pedirtelo por esta "
            "compactacion."
        ),
    }, "traspaso pedido tras compactacion")


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
        # Las rutas se calculan antes de la config para que la bitacora sea
        # localizable pase lo que pase; luego se rehacen porque el documento
        # puede estar configurado en otro sitio (la bitacora no se mueve).
        rutas = almacen.Rutas(_raiz(entrada))
        cfg = config.cargar(rutas.raiz)
        rutas = almacen.Rutas(rutas.raiz, documento_rel=cfg["documento"])
        if rutas.documento.is_file():
            carga, resultado = manejador(entrada, rutas, cfg)
        else:
            # Sin documento los tres eventos callan igual: es el caso
            # mayoritario del mundo -todo proyecto donde nunca se uso /baton- y
            # no puede ser ruido.
            carga, resultado = {}, "silencio: proyecto sin activar"
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
