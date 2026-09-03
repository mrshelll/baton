#!/usr/bin/env python3
"""CLI de baton. Lo invocan la skill y tambien tu, a mano.

Subcomandos:
  contexto  lo que el modelo necesita saber antes de redactar (breve)
  escribir  valida el borrador, lo mide, lo compone y lo escribe
  doctor    diagnostica por que baton no esta haciendo lo que esperas

Los codigos de salida son el protocolo con el modelo, no decoracion, y por eso
son distintos entre si: "no cabe" se arregla recortando y "esta mal montado" se
arregla cambiando la forma. Con un unico codigo de error el modelo probaria la
solucion equivocada.

  0 escrito   1 presupuesto excedido   2 borrador invalido   3 entorno
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

from lib import almacen, config, documento, gitinfo, presupuesto, salida  # noqa: E402

RAIZ_PLUGIN = Path(__file__).resolve().parent.parent

OK, PRESUPUESTO, INVALIDO, ENTORNO = 0, 1, 2, 3

#: Tres intentos y baton se hace cargo. Un contador visible corta mas bucles
#: que cualquier instruccion, y un tope bajo evita que el modelo se atasque
#: justo cuando ibas a cerrar la sesion.
MAX_INTENTOS = 3


def _edad_bitacora(rutas: almacen.Rutas):
    """Devuelve (ultima_marca, horas_desde_entonces) o (None, None)."""
    try:
        lineas = [l for l in rutas.bitacora.read_text(encoding="utf-8").split("\n") if l.strip()]
        ts = json.loads(lineas[-1])["ts"] if lineas else ""
    except Exception:
        return None, None
    cuando = almacen.desde_utc(ts)
    if cuando is None:
        return None, None
    return ts, (datetime.now(timezone.utc) - cuando) / timedelta(hours=1)


def _plugin_habilitado() -> bool | None:
    """True/False segun ~/.claude/settings.json; None si no se puede saber."""
    try:
        ajustes = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8"))
        habilitados = ajustes.get("enabledPlugins") or {}
        return any(k.split("@")[0] == "baton" and v for k, v in habilitados.items())
    except Exception:
        return None


def _contexto_de(args):
    """Raiz, config y textos: el preambulo de casi todos los subcomandos."""
    raiz = almacen.raiz_proyecto(args.cwd or os.getcwd())
    cfg = config.cargar(raiz)
    rutas = almacen.Rutas(raiz, documento_rel=cfg["documento"])
    textos = salida.cargar_textos()
    return raiz, cfg, rutas, textos


def cmd_contexto(args) -> int:
    """Lo que el modelo necesita ANTES de redactar. Corto a proposito.

    Si este comando fuera largo, se comeria en el contexto justo lo que baton
    intenta ahorrar.
    """
    raiz, cfg, rutas, textos = _contexto_de(args)
    s = gitinfo.snapshot(raiz)
    out = [f"proyecto: {raiz}", f"documento: {rutas.documento}",
           f"borrador: escribe SOLO el cuerpo en {rutas.borrador}"]

    t = cfg["topes"]
    out.append(f"presupuesto: {t['lineas']} lineas / {t['caracteres']} caracteres (todo el documento)")
    out.append("secciones validas: " + ", ".join(textos["secciones"].values()))
    out.append(f"obligatoria: {textos['secciones'][textos['seccion_obligatoria']]}"
               " -- las demas, solo si aplican (nunca escribas 'ninguno')")
    out.append("")
    out.append("contexto de git (lo pone baton, no lo escribas tu):")
    out += ["  " + l for l in gitinfo.bloque_contexto(s).split("\n")]

    if rutas.documento.is_file():
        try:
            actual = rutas.documento.read_text(encoding="utf-8", errors="replace")
            m = presupuesto.medir(actual)
            campos = documento.leer_campos(actual)
            out.append("")
            out.append(f"traspaso actual: modo {documento.leer_modo(actual)}, "
                       f"{m.lineas} lineas, escrito {campos.get('fecha', '?')}")
        except OSError:
            pass
    else:
        out.append("")
        out.append("traspaso actual: no hay. Este /baton activa baton en este proyecto.")

    if s.hay_git and not _gitignore_cubre(raiz):
        out.append("")
        out.append("falta en .gitignore (una linea):  .baton/local/")

    for aviso in cfg.avisos:
        out.append(f"aviso de config: {aviso}")

    print("\n".join(out))
    return OK


def _gitignore_cubre(raiz: Path) -> bool:
    try:
        texto = (raiz / ".gitignore").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(l.strip().rstrip("/") == ".baton/local" for l in texto.split("\n"))


def _intentos(rutas: almacen.Rutas, huella: str) -> int:
    """Cuantas veces seguidas ha fallado ESTE borrador por presupuesto."""
    try:
        datos = json.loads(rutas.intentos.read_text(encoding="utf-8"))
        if datos.get("huella") != huella:
            return 0
        cuando = almacen.desde_utc(datos.get("ts"))
        if cuando is None or datetime.now(timezone.utc) - cuando > timedelta(minutes=30):
            return 0  # una sesion vieja no arrastra intentos a la de hoy
        return int(datos.get("intentos", 0))
    except Exception:
        return 0


def _anotar_intento(rutas: almacen.Rutas, huella: str, n: int) -> None:
    try:
        rutas.asegurar_local()
        rutas.intentos.write_text(json.dumps(
            {"huella": huella, "intentos": n, "ts": almacen.ahora_utc()}), encoding="utf-8")
    except OSError:
        pass


def cmd_escribir(args) -> int:
    """Valida, mide, compone y escribe. El modelo NUNCA escribe el fichero."""
    raiz, cfg, rutas, textos = _contexto_de(args)
    if args.modo not in documento.MODOS:
        print(f"baton: modo invalido '{args.modo}'. Usa: {' o '.join(documento.MODOS)}",
              file=sys.stderr)
        return INVALIDO

    ruta_borrador = Path(args.borrador) if args.borrador else rutas.borrador
    try:
        crudo = ruta_borrador.read_text(encoding="utf-8")
    except OSError:
        print(f"baton: no encuentro el borrador en {ruta_borrador}.\n"
              f"Escribe ahi SOLO el cuerpo del traspaso (con Write) y repite el comando.",
              file=sys.stderr)
        return INVALIDO

    parte = documento.validar_borrador(crudo, modo=args.modo, textos=textos)
    if not parte.valido:
        print("baton: el borrador no cumple el contrato. No se ha escrito nada.",
              file=sys.stderr)
        for e in parte.errores:
            print(f"  - {e}", file=sys.stderr)
        return INVALIDO

    s = gitinfo.snapshot(raiz)
    def _montar(cuerpo):
        return documento.componer(
            cuerpo=cuerpo, modo=args.modo, fecha=gitinfo.ahora_iso(),
            rama=s.rama, commit=s.commit,
            contexto=gitinfo.bloque_contexto(s), textos=textos)

    final = _montar(parte.cuerpo)
    veredicto = presupuesto.evaluar(final, cfg["topes"])

    if not veredicto.cabe:
        huella_borrador = documento.huella(final, textos["seccion_contexto"])
        intento = _intentos(rutas, huella_borrador) + 1
        if intento < MAX_INTENTOS:
            _anotar_intento(rutas, huella_borrador, intento)
            print(presupuesto.informe(veredicto, parte.cuerpo, intento, MAX_INTENTOS,
                                      str(rutas.documento)), file=sys.stderr)
            return PRESUPUESTO
        # Ultimo recurso: un minimo honesto y declarado, cortado por lineas
        # completas. Nunca una frase a medias fingiendo estar entera.
        final = _escape_minimo(parte, textos, cfg, _montar, intento)

    try:
        almacen.escribir_documento(rutas, final, historial_max=cfg["historial_max"])
    except (almacen.OcupadoError, almacen.EntornoError) as exc:
        print(f"baton: {exc}", file=sys.stderr)
        return ENTORNO

    m = presupuesto.medir(final)
    print(f"baton: traspaso escrito en {rutas.documento}\n"
          f"  modo {args.modo} - {m.lineas}/{cfg['topes']['lineas']} lineas, "
          f"{m.caracteres}/{cfg['topes']['caracteres']} caracteres (~{m.tokens} tokens)")
    return OK


def _escape_minimo(parte, textos, cfg, montar, intentos):
    """Compone un traspaso minimo cuando el borrador no cabe tras N intentos.

    Se queda con la seccion obligatoria, recortada por LINEAS COMPLETAS, y lo
    declara dentro del propio documento. Es truncar, si -- pero truncar
    diciendolo, que es lo contrario de dejar una frase a medias con aspecto de
    estar entera.
    """
    slug = textos["seccion_obligatoria"]
    canonica, contenido = parte.secciones[slug]
    marca = textos["marca_recorte_escritura"].format(intentos=intentos)
    fijo = len(montar(f"## {canonica}\n\n{marca}\n"))
    margen_c = max(cfg["topes"]["caracteres"] - fijo, 200)
    margen_l = max(cfg["topes"]["lineas"] - len(montar("## x\n").split("\n")) - 2, 3)
    recortado, _ = presupuesto.recortar_por_lineas(contenido, margen_c, margen_l)
    return montar(f"## {canonica}\n{recortado.rstrip()}\n\n{marca}\n")


def cmd_ver(args) -> int:
    """Muestra el traspaso actual y lo que costaria inyectarlo."""
    raiz, cfg, rutas, _ = _contexto_de(args)
    if not rutas.documento.is_file():
        print(f"baton: este proyecto no tiene traspaso todavia ({rutas.documento}).\n"
              "Corre /baton para crearlo.")
        return OK
    texto = rutas.documento.read_text(encoding="utf-8", errors="replace")
    m = presupuesto.medir(texto)
    campos = documento.leer_campos(texto)
    modo = documento.leer_modo(texto)
    fresco = gitinfo.frescura(raiz, campos.get("fecha"), campos.get("rama", ""),
                              campos.get("commit", ""))
    print(f"{rutas.documento}")
    print(f"  modo {modo} - {m.lineas}/{cfg['topes']['lineas']} lineas, "
          f"{m.caracteres}/{cfg['topes']['caracteres']} caracteres (~{m.tokens} tokens)")
    print(f"  escrito {campos.get('fecha', '?')} en `{campos.get('rama', '?')}` "
          f"@ {campos.get('commit', '?')}")
    aviso = fresco.aviso()
    print(f"  {aviso}" if aviso else "  frescura: al dia")
    if args.completo:
        print("\n" + texto)
    return OK


def cmd_doctor(args) -> int:
    """Un hook que no dispara no da error: no da nada.

    Este comando existe para convertir ese silencio en un diagnostico. Ordena
    las causas por probabilidad real, empezando por la que acierta casi siempre:
    instalar el plugin sin reiniciar Claude Code.
    """
    raiz = almacen.raiz_proyecto(args.cwd or os.getcwd())
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
    # Sirven para las dos preguntas que quedan: donde esta el documento (puede
    # estar configurado en otro sitio) y donde la bitacora (nunca se mueve).
    rutas = almacen.Rutas(raiz, documento_rel=config.cargar(raiz)["documento"])
    if not rutas.documento.is_file():
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
    def con_cwd(nombre, ayuda, func):
        sp = sub.add_parser(nombre, help=ayuda)
        sp.add_argument("--cwd", default=None, help="directorio del proyecto (por defecto, el actual)")
        sp.set_defaults(func=func)
        return sp

    con_cwd("contexto", "lo que el modelo necesita antes de redactar", cmd_contexto)
    esc = con_cwd("escribir", "valida el borrador y escribe el traspaso", cmd_escribir)
    # Sin `choices`: el modo lo valida cmd_escribir, que puede explicar la
    # diferencia entre los dos en vez de soltar un error de argparse.
    esc.add_argument("--modo", required=True,
                     help="continuacion (hay tarea a medias) o memoria (solo contexto)")
    esc.add_argument("--borrador", default=None, help="ruta del borrador (por defecto, .baton/local/borrador.md)")
    ver = con_cwd("ver", "muestra el traspaso actual y lo que cuesta inyectarlo", cmd_ver)
    ver.add_argument("--completo", action="store_true", help="imprime tambien el documento entero")
    con_cwd("doctor", "diagnostica la instalacion y el estado del proyecto", cmd_doctor)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
