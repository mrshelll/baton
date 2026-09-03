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

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

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


# --- validacion del borrador y composicion del fichero final --------------
#
# El modelo escribe SOLO el cuerpo, en un borrador aparte. El fichero final lo
# compone el codigo. De ahi salen cuatro garantias que no dependen de que el
# modelo se porte bien: la reescritura es siempre entera, el frontmatter
# siempre es valido, los campos de git siempre son correctos, y un intento
# fallido deja el traspaso anterior intacto.


@dataclass
class Parte:
    valido: bool
    cuerpo: str = ""
    secciones: dict = field(default_factory=dict)
    errores: list = field(default_factory=list)


def _quitar_frontmatter(texto: str) -> str:
    """El modelo no escribe el frontmatter. Si lo cuela, se descarta."""
    m = RE_FRONTMATTER.match(texto[:CABEZA])
    return texto[m.end():] if m else texto


def _trocear(texto: str):
    """Devuelve (preambulo, {etiqueta: contenido}) respetando el orden."""
    marcas = list(RE_SECCION.finditer(texto))
    if not marcas:
        return texto.strip(), {}
    preambulo = texto[:marcas[0].start()].strip()
    secciones = {}
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        secciones[m.group(1)] = texto[m.end():fin].strip()
    return preambulo, secciones


def validar_borrador(texto, modo: str, textos: dict) -> Parte:
    """Comprueba la ESTRUCTURA del borrador. El tamano lo mira `presupuesto`.

    Son dos preguntas distintas y merecen codigos de salida distintos: "esto no
    cabe" se arregla recortando, "esto esta mal montado" se arregla cambiando
    la forma. Mezclarlas hace que el modelo pruebe la solucion equivocada.
    """
    errores = []
    cuerpo = _quitar_frontmatter(texto if isinstance(texto, str) else "").strip()
    if not cuerpo:
        return Parte(False, errores=["el borrador esta vacio: escribe al menos la seccion Estado"])

    validas = textos["secciones"]
    obligatoria = validas[textos["seccion_obligatoria"]]
    por_etiqueta = {normalizar_etiqueta(v): (k, v) for k, v in validas.items()}
    relleno = {normalizar_etiqueta(x) for x in textos["relleno_prohibido"]}

    preambulo, crudas = _trocear(cuerpo)
    if preambulo:
        errores.append(
            "hay texto suelto antes de la primera seccion; todo el contenido tiene que "
            "vivir dentro de una seccion"
        )

    secciones = {}
    for etiqueta, contenido in crudas.items():
        clave = por_etiqueta.get(normalizar_etiqueta(etiqueta))
        if clave is None:
            errores.append(
                f"seccion desconocida '{etiqueta}'. Las validas son: "
                + ", ".join(validas.values())
            )
            continue
        slug, canonica = clave
        if not contenido or normalizar_etiqueta(contenido) in relleno:
            errores.append(
                f"la seccion '{canonica}' no dice nada. Si no aplica, BORRALA entera: "
                "baton no escribe 'ninguno' ni 'N/A'"
            )
            continue
        secciones[slug] = (canonica, contenido)

    if textos["seccion_obligatoria"] not in secciones:
        errores.append(f"falta la seccion obligatoria '{obligatoria}'")

    if modo == "continuacion" and "siguiente" not in secciones:
        errores.append(
            f"modo continuacion exige '{validas['siguiente']}': o escribes que retomar, "
            "o el modo es memoria"
        )

    if errores:
        return Parte(False, errores=errores)

    orden = [s for s in validas if s in secciones]
    limpio = "\n\n".join(f"## {secciones[s][0]}\n{secciones[s][1]}" for s in orden)
    return Parte(True, cuerpo=limpio + "\n", secciones=secciones)


def componer(cuerpo, modo, fecha, rama, commit, contexto, textos) -> str:
    """Monta el fichero final. Es el UNICO sitio que lo escribe."""
    cabecera = [
        "---",
        f"baton: {VERSION}",
        f"modo: {modo}",
        f"fecha: {fecha}",
        f"rama: {rama}",
        f"commit: {commit}",
        "---",
        f"<!-- {textos['cabecera_generado']} -->",
        "",
        f"## {textos['seccion_contexto']}",
        contexto.rstrip(),
        "",
        "",
    ]
    return "\n".join(cabecera) + cuerpo.strip() + "\n"


def extraer_cuerpo(texto, nombre_contexto: str = "Contexto") -> str:
    """Lo que escribio el modelo: sin frontmatter y sin la seccion de git."""
    resto = _quitar_frontmatter(texto if isinstance(texto, str) else "")
    saltar = normalizar_etiqueta(nombre_contexto)
    for m in RE_SECCION.finditer(resto):
        if normalizar_etiqueta(m.group(1)) != saltar:
            return resto[m.start():].strip() + "\n"
    return ""


def huella(texto, nombre_contexto: str = "Contexto") -> str:
    """Identidad de un traspaso: solo su cuerpo.

    Deliberadamente ignora el frontmatter y `## Contexto`. Si contara el git,
    cada commit haria que el mismo traspaso pareciera nuevo, y el aviso de
    "esto ya te lo entregue" no serviria de nada.
    """
    return hashlib.sha256(
        extraer_cuerpo(texto, nombre_contexto).encode("utf-8")
    ).hexdigest()[:16]
