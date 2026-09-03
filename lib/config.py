"""Configuracion de baton: defaults, global y proyecto.

Dos ficheros opcionales, misma forma que `settings.json` de Claude Code para
que no haya un concepto nuevo que aprender:

    ~/.claude/baton.json              tu preferencia en todos los proyectos
    <proyecto>/.claude/baton.json     solo en ese repo; gana sobre el global

Sin ninguno de los dos, funcionan los defaults. Una config rota nunca impide
usar baton: se avisa nombrando el fichero y se sigue con los valores buenos.
"""
from __future__ import annotations

import json
from pathlib import Path

from lib import presupuesto

POR_DEFECTO = {
    "topes": dict(presupuesto.TOPES_POR_DEFECTO),
    # Relativo a la raiz del proyecto, siempre.
    "documento": ".baton/TRASPASO.md",
    "historial_max": 10,
    # En que arranques se inyecta el traspaso.
    "inyectar_en": ["startup", "clear", "compact", "resume", "fork"],
    # Minutos entre dos peticiones automaticas de traspaso.
    "cooldown_minutos": 30,
    # El recibo de una linea que demuestra que el hook disparo.
    "recibo": True,
}

#: Errores de tecleo que merecen una pista concreta en vez de un "clave
#: desconocida" que no ayuda a nadie.
SUGERENCIAS = {
    "lineas_max": "topes.lineas",
    "max_lineas": "topes.lineas",
    "caracteres_max": "topes.caracteres",
    "tokens_max": "topes.tokens",
    "max_tokens": "topes.tokens",
    "historial": "historial_max",
    "ruta": "documento",
}


class Config(dict):
    """Un dict con la lista de problemas encontrados al cargarlo."""

    def __init__(self, datos, avisos=None):
        super().__init__(datos)
        self.avisos = list(avisos or [])


def _leer(ruta: Path, avisos: list):
    """Lee un JSON de config. Cualquier problema se convierte en aviso."""
    if ruta is None or not ruta.is_file():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as exc:
        avisos.append(f"{ruta.name}: no se pudo leer ({type(exc).__name__}); uso los valores por defecto")
        return {}
    if not isinstance(datos, dict):
        avisos.append(f"{ruta.name}: se esperaba un objeto JSON y hay {type(datos).__name__}; uso los valores por defecto")
        return {}
    return datos


def _fusionar(base: dict, encima: dict, ruta: Path, avisos: list) -> dict:
    """Merge de UN nivel: `topes` se fusiona clave a clave, el resto se pisa.

    Un merge de un nivel es justo lo que hace falta: tocar `topes.lineas` no
    puede dejarte sin `topes.caracteres`, y a la vez no hay que razonar sobre
    fusiones profundas que nadie necesita.
    """
    salida = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for clave, valor in encima.items():
        if clave in SUGERENCIAS:
            avisos.append(f"{ruta.name}: clave desconocida '{clave}'. Querias '{SUGERENCIAS[clave]}'?")
            continue
        if clave not in POR_DEFECTO:
            avisos.append(f"{ruta.name}: clave desconocida '{clave}'; la ignoro")
            continue
        if clave == "topes" and isinstance(valor, dict):
            for nombre, numero in valor.items():
                if nombre not in POR_DEFECTO["topes"]:
                    avisos.append(f"{ruta.name}: tope desconocido 'topes.{nombre}'; lo ignoro")
                elif isinstance(numero, bool) or not isinstance(numero, int) or numero <= 0:
                    avisos.append(f"{ruta.name}: 'topes.{nombre}' debe ser un entero positivo; uso {POR_DEFECTO['topes'][nombre]}")
                else:
                    salida["topes"][nombre] = numero
        elif clave == "documento":
            if not _ruta_segura(valor):
                avisos.append(f"{ruta.name}: 'documento' apunta fuera del proyecto; uso {POR_DEFECTO['documento']}")
            else:
                salida["documento"] = valor
        elif clave == "historial_max":
            if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0:
                salida["historial_max"] = valor
            else:
                avisos.append(f"{ruta.name}: 'historial_max' debe ser un entero >= 0; uso {POR_DEFECTO['historial_max']}")
        else:
            salida[clave] = valor
    return salida


def _ruta_segura(valor) -> bool:
    """El documento vive DENTRO del proyecto. Sin absolutas ni '..'."""
    if not isinstance(valor, str) or not valor.strip():
        return False
    p = Path(valor)
    return not p.is_absolute() and ".." not in p.parts


def ruta_global_por_defecto() -> Path:
    return Path.home() / ".claude" / "baton.json"


def cargar(raiz, ruta_global=None) -> Config:
    """Defaults -> global -> proyecto. El del proyecto manda.

    `ruta_global` existe para que los tests no dependan del HOME de quien los
    corre; en produccion nadie la pasa.
    """
    avisos: list = []
    datos = dict(POR_DEFECTO)
    datos["topes"] = dict(POR_DEFECTO["topes"])
    globales = Path(ruta_global) if ruta_global else ruta_global_por_defecto()
    for ruta in (globales, Path(raiz) / ".claude" / "baton.json"):
        crudo = _leer(ruta, avisos)
        if crudo:
            datos = _fusionar(datos, crudo, ruta, avisos)
    return Config(datos, avisos)
