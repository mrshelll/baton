"""De un fichero en disco al contexto del modelo: sanear, envolver, acotar.

El documento de traspaso se commitea y viaja con el repo. Quien clone un repo
ajeno se inyecta en su contexto lo que ese fichero diga, asi que aqui se trata
como entrada NO confiable: se limpia, se le impide cerrar su propia etiqueta y
se declara explicitamente como datos y no como instrucciones.

La otra mitad del trabajo es no pasarse del techo del harness (8.000 caracteres
/ 200 lineas). Si el documento fue editado a mano y se pasa, lo recorta baton
por lineas completas y lo dice -- en vez de dejar que el harness corte en
silencio a mitad de una frase.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from lib import presupuesto

RAIZ_PLUGIN = Path(__file__).resolve().parent.parent

#: Caracteres que nunca deben llegar al contexto: controles C0/C1 (salvo salto
#: y tabulador), overrides de direccion y espacios de ancho cero. Los ultimos
#: dos grupos sirven para que un texto parezca decir algo distinto de lo que
#: dice, que es justo lo que no queremos en un fichero que viaja en un repo.
_PERMITIDOS = {"\n", "\t"}
_INVISIBLES = {
    "​", "‌", "‍", "⁠", "﻿",
    "‪", "‫", "‬", "‭", "‮",
    "⁦", "⁧", "⁨", "⁩",
}


def cargar_textos(idioma: str = "es") -> dict:
    """Los textos que ve el modelo viven en templates/, no en el codigo."""
    return json.loads((RAIZ_PLUGIN / "templates" / f"{idioma}.json").read_text(encoding="utf-8"))


def sanear(texto) -> str:
    """Limpia el documento antes de que toque el contexto. Nunca lanza."""
    if isinstance(texto, bytes):
        texto = texto.decode("utf-8", errors="replace")
    if not isinstance(texto, str):
        return ""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    limpio = []
    for c in texto:
        if c in _PERMITIDOS:
            limpio.append(c)
        elif c in _INVISIBLES:
            continue
        elif unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs"):
            continue
        else:
            limpio.append(c)
    return "".join(limpio)


def _desactivar_cierre(texto: str, etiqueta: str) -> str:
    """Impide que el contenido cierre su propia etiqueta.

    Sin esto, un documento que contenga el cierre podria sacar el resto del
    texto fuera del bloque marcado como datos, y lo que venga despues se leeria
    como instrucciones de nivel superior.
    """
    return texto.replace(f"</{etiqueta}>", f"<⁄{etiqueta}>")


def envolver(documento, modo, escrito, origen, aviso_frescura="", repetido=None,
             textos=None, techo_caracteres=None, techo_lineas=None) -> str:
    """Arma el texto exacto que se inyecta como `additionalContext`.

    Orden deliberado: primero la instruccion de modo (es lo unico que no puede
    perderse), luego los avisos (cambian como hay que leer el documento) y por
    ultimo el documento. Asi lo importante sobrevive a cualquier recorte.
    """
    t = textos or cargar_textos()
    etiqueta = t["etiqueta"]
    techo_c = techo_caracteres or presupuesto.TECHO_CARACTERES
    techo_l = techo_lineas or presupuesto.TECHO_LINEAS

    cabeza = [
        f'<{etiqueta} modo="{modo}" escrito="{escrito}" origen="{origen}">',
        "",
        t["instruccion"].get(modo, t["instruccion"]["memoria"]),
        "",
    ]
    if aviso_frescura:
        cabeza += [aviso_frescura, ""]
    if repetido:
        cabeza += [t["repetido"].format(**repetido), ""]
    cabeza += [t["advertencia_datos"], ""]

    cola = [t["cierra_documento"], f"</{etiqueta}>"]

    cuerpo_limpio = _desactivar_cierre(sanear(documento), etiqueta)

    # Lo que le queda al documento es el techo menos todo lo demas. Se calcula
    # aqui, con el envoltorio ya construido, en vez de con una reserva fija:
    # asi un aviso de frescura largo no puede empujar el total por encima.
    fijo = "\n".join(cabeza + [t["abre_documento"]] + cola) + "\n"
    aviso_recorte = t["recortado_al_inyectar"]
    margen_c = techo_c - len(fijo) - len(aviso_recorte) - 2
    margen_l = techo_l - len(fijo.split("\n")) - 2

    cuerpo, recortado = presupuesto.recortar_por_lineas(cuerpo_limpio, margen_c, margen_l)

    partes = list(cabeza)
    if recortado:
        partes += [aviso_recorte, ""]
    partes += [t["abre_documento"], cuerpo.rstrip("\n")] + cola
    return "\n".join(partes)
