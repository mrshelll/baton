#!/usr/bin/env python3
"""CLI de baton. Lo invocan la skill y tambien tu, a mano.

Subcomandos:
  doctor    diagnostica por que baton no esta haciendo lo que esperas

Los codigos de salida son el protocolo con el modelo, no decoracion:
  0 todo bien   1 presupuesto excedido   2 borrador invalido   3 entorno
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import almacen  # noqa: E402

RAIZ_PLUGIN = Path(__file__).resolve().parent.parent


def _edad_bitacora(rutas: almacen.Rutas):
    """Devuelve (ultima_marca, horas_desde_entonces) o (None, None)."""
    try:
        lineas = [l for l in rutas.bitacora.read_text(encoding="utf-8").split("\n") if l.strip()]
        if not lineas:
            return None, None
        ts = json.loads(lineas[-1])["ts"]
        cuando = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return ts, (datetime.now(timezone.utc) - cuando) / timedelta(hours=1)
    except Exception:
        return None, None


def _plugin_habilitado() -> bool | None:
    """True/False segun ~/.claude/settings.json; None si no se puede saber."""
    try:
        ajustes = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8"))
        habilitados = ajustes.get("enabledPlugins") or {}
        return any(k.split("@")[0] == "baton" and v for k, v in habilitados.items())
    except Exception:
        return None


def cmd_doctor(args) -> int:
    """Un hook que no dispara no da error: no da nada.

    Este comando existe para convertir ese silencio en un diagnostico. Ordena
    las causas por probabilidad real, empezando por la que acierta casi siempre:
    instalar el plugin sin reiniciar Claude Code.
    """
    raiz = almacen.raiz_proyecto(args.cwd or os.getcwd())
    rutas = almacen.Rutas(raiz)
    lineas = [f"baton doctor -- proyecto: {raiz}", ""]

    hooks_json = RAIZ_PLUGIN / "hooks" / "hooks.json"
    try:
        eventos = ", ".join(json.loads(hooks_json.read_text(encoding="utf-8"))["hooks"])
        lineas.append(f"  [ok] hooks.json valido      ({eventos})")
    except Exception as exc:
        lineas.append(f"  [!!] hooks.json ILEGIBLE    {type(exc).__name__}: {exc}")

    lineas.append(f"  [ok] python3                {sys.version.split()[0]}")
    git = shutil.which("git")
    if git:
        try:
            v = subprocess.run([git, "--version"], capture_output=True, text=True, timeout=3)
            lineas.append(f"  [ok] git                    {v.stdout.strip()}")
        except Exception:
            lineas.append("  [--] git                    presente pero no responde")
    else:
        lineas.append("  [--] git                    ausente (baton funciona igual, sin datos de git)")

    habilitado = _plugin_habilitado()
    if habilitado is True:
        lineas.append("  [ok] plugin habilitado      en ~/.claude/settings.json")
    elif habilitado is False:
        lineas.append("  [!!] plugin NO habilitado   revisalo con /plugin")
    else:
        lineas.append("  [--] plugin                 no pude leer ~/.claude/settings.json")

    lineas.append("")
    if not almacen.esta_activado(raiz):
        lineas.append("  Este proyecto aun no usa baton.")
        lineas.append("  Corre /baton una vez para activarlo aqui; hasta entonces los hooks callan")
        lineas.append("  a proposito, y eso NO es un fallo.")
        print("\n".join(lineas))
        return 0

    lineas.append(f"  Documento: {rutas.documento}")
    ts, horas = _edad_bitacora(rutas)
    if ts is None:
        lineas.append("")
        lineas.append("  El hook NO ha dejado ni un rastro. Causas por probabilidad:")
        lineas.append("    1. Instalaste el plugin sin reiniciar Claude Code (los hooks se")
        lineas.append("       cargan al arrancar).")
        lineas.append("    2. El plugin esta deshabilitado -- compruebalo con /plugin.")
        lineas.append(f"    3. python3 no esta en el PATH del harness (aqui si: {sys.version.split()[0]}).")
    elif horas is not None and horas > 24:
        lineas.append("")
        lineas.append(f"  El hook no dispara desde {ts} ({horas:.0f} h). Mismas causas que arriba.")
    else:
        lineas.append(f"  Ultimo disparo del hook: {ts}")

    print("\n".join(lineas))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="baton", description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("doctor", help="diagnostica la instalacion y el estado del proyecto")
    p.add_argument("--cwd", default=None, help="directorio del proyecto (por defecto, el actual)")
    p.set_defaults(func=cmd_doctor)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
