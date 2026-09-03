"""Medir el traspaso y decidir si cabe. Aqui vive el requisito central.

El techo NO es una preferencia de diseno. Verificado en el binario de Claude
Code 2.1.259, el contexto que un hook inyecta por `additionalContext` se trunca
a 8.000 caracteres o 200 lineas, lo que ocurra primero -- y en silencio:

    hKr = {..., additionalContext: 8000}   # caracteres
    yKr = {..., additionalContext: 200}    # lineas

Por eso un traspaso de 931 lineas no es solo caro: no cabe. Llega cortado y
nadie avisa. Los topes por defecto se derivan hacia atras desde ese techo,
reservando sitio para el envoltorio (instruccion de modo, aviso de frescura,
advertencias) que viaja en el mismo campo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TECHO_CARACTERES = 8000
TECHO_LINEAS = 200

#: Lo que ocupa el envoltorio en el peor caso razonable: instruccion de modo
#: larga + aviso de frescura + aviso de repetido + etiquetas.
RESERVA_ENVOLTORIO_CARACTERES = 1800
RESERVA_ENVOLTORIO_LINEAS = 60

TOPES_POR_DEFECTO = {
    # Vinculante: es la unidad en la que trunca el harness.
    "caracteres": 6000,
    # La unica que un humano ve y sabe arreglar. Sale primero en el error.
    "lineas": 120,
    # Informativa: lo que le cuesta el arranque. No rechaza por si sola.
    "tokens": 1700,
}

#: `tokens` no rechaza: es una estimacion, y rechazar por una estimacion seria
#: pedirle al modelo que adivine el tokenizador.
MEDIDAS_QUE_RECHAZAN = ("caracteres", "lineas")

_PALABRA = re.compile(r"\S+")
_SECCION = re.compile(r"^##[ \t]+(.+?)[ \t\r]*$", re.MULTILINE)


def estimar_tokens(texto) -> int:
    """Estimador determinista, sin dependencias y deliberadamente PESIMISTA.

    3.6 caracteres por token: BPE sobre espanol con markdown ronda 3.7-4.2, asi
    que 3.6 sobreestima alrededor de un 10%. El max() con palabras*1.3 cubre el
    texto de palabras cortas -listas, rutas, codigo-, donde dividir por
    caracteres subestima.

    Es informativo. El tope que manda es `caracteres`, que es exacto y es lo
    que mide el harness.
    """
    if not isinstance(texto, str) or not texto:
        return 0
    return int(max(len(texto) / 3.6, len(_PALABRA.findall(texto)) * 1.3) + 0.5)


@dataclass(frozen=True)
class Medida:
    lineas: int
    caracteres: int
    tokens: int


def medir(texto) -> Medida:
    if not isinstance(texto, str) or not texto:
        return Medida(0, 0, 0)
    # rstrip: el salto final no es una linea de mas.
    return Medida(
        lineas=len(texto.rstrip("\n").split("\n")),
        caracteres=len(texto),
        tokens=estimar_tokens(texto),
    )


@dataclass(frozen=True)
class Veredicto:
    cabe: bool
    medida: Medida
    topes: dict
    excesos: dict = field(default_factory=dict)


def evaluar(texto, topes=None) -> Veredicto:
    topes = dict(topes or TOPES_POR_DEFECTO)
    m = medir(texto)
    excesos = {}
    for nombre in MEDIDAS_QUE_RECHAZAN:
        tope = topes.get(nombre)
        valor = getattr(m, nombre)
        if tope and valor > tope:
            excesos[nombre] = valor - tope
    return Veredicto(cabe=not excesos, medida=m, topes=topes, excesos=excesos)


def lineas_por_seccion(texto) -> dict:
    """Cuantas lineas ocupa cada seccion. Sirve para senalar a la culpable."""
    if not isinstance(texto, str) or not texto:
        return {}
    marcas = list(_SECCION.finditer(texto))
    conteo = {}
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        trozo = texto[m.start():fin].rstrip("\n")
        conteo[m.group(1)] = len(trozo.split("\n"))
    return conteo


def informe(veredicto: Veredicto, texto, intento: int, maximo: int,
            ruta_anterior: str = ".baton/TRASPASO.md") -> str:
    """El mensaje de rechazo.

    Tres cosas que tiene que conseguir: que quede claro que no se ha perdido
    nada, senalar DONDE sobra, y decir cuantos intentos quedan. El contador
    visible corta mas bucles que cualquier instruccion.
    """
    m, t = veredicto.medida, veredicto.topes
    filas = [
        ("caracteres", m.caracteres, t.get("caracteres")),
        ("lineas", m.lineas, t.get("lineas")),
        ("tokens~", m.tokens, t.get("tokens")),
    ]
    out = [
        "baton: el traspaso NO cabe en el presupuesto. No se ha escrito nada.",
        f"El traspaso anterior ({ruta_anterior}) sigue intacto.",
        "",
    ]
    for nombre, valor, tope in filas:
        if not tope:
            continue
        estado = "ok" if valor <= tope else f"{valor - tope} de mas"
        out.append(f"  {nombre:<11} {valor:>6} / {tope:<6} {estado}")

    conteo = lineas_por_seccion(texto)
    if conteo:
        peor = max(conteo, key=conteo.get)
        out += ["", "Lineas por seccion:"]
        for nombre, n in conteo.items():
            marca = "  <-- la mas gorda" if nombre == peor else ""
            out.append(f"  {nombre:<26} {n:>4}{marca}")

    out += [
        "",
        "Como recortar (en este orden, no negocies con el presupuesto):",
        "  1. BORRA ENTERA la seccion que menos ayude a arrancar la proxima sesion.",
        "     Criterio: si se recupera leyendo el codigo en 30 s, fuera.",
        "  2. Una decision = UNA linea: \"decision -- porque\". Sin parrafos.",
        "  3. Corta lo que sobra; no acortes por igual lo que importa.",
        "  4. Reescribe el borrador ENTERO con Write (nunca Edit) y repite el comando.",
        "",
        f"Intento {intento} de {maximo}. Al ultimo baton escribe un traspaso minimo y lo declara.",
    ]
    return "\n".join(out)


def recortar_por_lineas(texto, max_caracteres: int, max_lineas: int):
    """Recorta por limite de LINEA COMPLETA. Devuelve (texto, se_recorto).

    Nunca corta a media frase: un traspaso cortado por la mitad miente, y una
    mentira con aspecto de verdad es peor que una ausencia. Quien llama a esto
    tiene que declarar el recorte en el propio documento.
    """
    if not isinstance(texto, str) or not texto:
        return "", False
    lineas = texto.split("\n")
    cabidas, total = [], 0
    for linea in lineas:
        coste = len(linea) + 1
        if len(cabidas) >= max_lineas or total + coste > max_caracteres:
            break
        cabidas.append(linea)
        total += coste
    if len(cabidas) == len(lineas):
        return texto, False
    recortado = "\n".join(cabidas)
    if recortado and not recortado.endswith("\n"):
        recortado += "\n"
    return recortado, True
