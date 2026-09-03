"""El contrato del documento de traspaso. Todo lo demas depende de este modulo.

Estructura, y quien escribe cada parte:

    frontmatter YAML   <- SIEMPRE el codigo. 5 claves, ni una mas ni una menos
    comentario HTML    <- el codigo. Advertencia de reescritura
    ## Contexto        <- el codigo, desde git
    ## Estado, ...     <- el MODELO. Estado obligatorio, el resto opcionales

Que el frontmatter lo escriba el codigo no es un detalle de implementacion: es
lo que hace que `leer_modo` no pueda fallar por culpa del modelo, porque el
modelo nunca escribe esa linea.
"""
from __future__ import annotations

import re
import unicodedata

#: Version del formato. Sube solo si cambia de forma incompatible.
VERSION = 1

#: Ante cualquier ambiguedad se responde esto. Es la decision de seguridad
#: central del plugin: un documento ilegible no puede autorizar a continuar
#: trabajo. El fallo de los plugins equivalentes es justo el contrario.
MODO_SEGURO = "memoria"
MODOS = ("continuacion", "memoria")

#: Solo se inspecciona la cabeza del fichero. Un traspaso de 1 MB (editado a
#: mano, corrupto, lo que sea) no puede costar tiempo en cada arranque.
CABEZA = 4096

RE_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
# El \r de las clases finales no es cosmetico: con MULTILINE, `$` casa ANTES
# del \n, asi que en un fichero CRLF el \r se queda dentro de la linea y
# tumbaria el match. Un traspaso escrito en Windows debe leerse igual.
RE_MODO = re.compile(r"^modo:[ \t]*(continuacion|memoria)[ \t\r]*$", re.MULTILINE)
RE_VERSION = re.compile(r"^baton:[ \t]*(\d+)[ \t\r]*$", re.MULTILINE)
RE_CAMPO = re.compile(r"^(fecha|rama|commit):[ \t]*(\S.*?)[ \t\r]*$", re.MULTILINE)
RE_SECCION = re.compile(r"^##[ \t]+(.+?)[ \t\r]*$", re.MULTILINE)


def _frontmatter(texto) -> str | None:
    """Devuelve el cuerpo del frontmatter, o None si no hay uno bien formado."""
    if not isinstance(texto, str) or not texto:
        return None
    m = RE_FRONTMATTER.match(texto[:CABEZA])
    return m.group(1) if m else None


def leer_modo(texto) -> str:
    """Determinista y a prueba de basura.

    El valor es ASCII sin tilde a proposito (`continuacion`): es un enum, no
    prosa. Aceptar variantes -con tilde, en mayusculas- convertiria un campo de
    control en algo que se puede escribir "casi bien", y "casi bien" aqui
    significa que una sesion arranca sola cuando no debia.
    """
    cuerpo = _frontmatter(texto)
    if cuerpo is None:
        return MODO_SEGURO
    m = RE_MODO.search(cuerpo)
    return m.group(1) if m else MODO_SEGURO


def leer_version(texto):
    """Version del formato declarada en el documento, o None."""
    cuerpo = _frontmatter(texto)
    if cuerpo is None:
        return None
    m = RE_VERSION.search(cuerpo)
    return int(m.group(1)) if m else None


def leer_campos(texto) -> dict:
    """fecha / rama / commit del frontmatter. Ausentes si no estan."""
    cuerpo = _frontmatter(texto)
    if cuerpo is None:
        return {}
    return {k: v for k, v in RE_CAMPO.findall(cuerpo)}


def normalizar_etiqueta(texto: str) -> str:
    """Compara etiquetas de seccion sin que la tilde ni la caja importen.

    Aqui SI se es permisivo, al reves que con el modo: una etiqueta es prosa
    dirigida a un humano, y que el modelo escriba "Decisiones y su porque" en
    vez de "porqué" no debe costarle un rechazo.
    """
    plano = unicodedata.normalize("NFD", texto or "")
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    return " ".join(plano.casefold().split())
