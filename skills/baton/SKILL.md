---
name: baton
description: Use when the user wants to hand off context to a new Claude Code session - "escribe el traspaso", "/baton", "me estoy quedando sin contexto", "vamos a abrir sesión nueva", "guarda dónde vamos", "cierra esto y seguimos mañana". Writes a size-capped handoff document that the next session receives automatically.
user-invocable: true
allowed-tools: Bash, Read, Write, Glob, Grep
---

# Escribir el traspaso

Tú redactas **solo el cuerpo**. El fichero final lo compone el código: frontmatter,
fecha, rama, commit y contexto de git. No escribas nada de eso.

## 1. Pide el contexto

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" contexto
```

Te dice dónde escribir el borrador, cuál es el presupuesto y qué secciones son
válidas. Léelo antes de redactar.

## 2. Elige el modo

Si el usuario te dio el modo en los argumentos, úsalo y salta al paso 3.

Elige `continuacion` **solo** si respondes que sí a las tres:

1. ¿Hay una tarea concreta, ya empezada, sin terminar?
2. ¿Puedes nombrar el siguiente paso en una frase imperativa con fichero y línea?
3. ¿El usuario espera que la retomes **sin preguntarle nada primero**?

Si alguna es «no», o si dudas: `memoria`. Sin excepciones.

`memoria` no es el modo de consolación, es el correcto casi siempre: el trabajo
terminó, fue una exploración sin tarea abierta, o el usuario dijo «para aquí».
Elegir `continuacion` de más es el fallo que hace que la sesión siguiente arranque
sola y toque trabajo que nadie pidió.

## 3. Redacta el cuerpo

Escribe con `Write` en la ruta de borrador que te dio el paso 1. **Solo el cuerpo**,
empezando directamente por `## Estado`.

Secciones, en este orden. Solo `Estado` es obligatoria:

| Sección | Qué va | Qué NO va |
|---|---|---|
| `## Estado` | Qué está hecho y qué no, con rutas concretas | Narrar la sesión |
| `## Decisiones y su porque` | Una línea por decisión: «qué — por qué» | El qué sin el porqué |
| `## Bloqueos` | Lo que impide avanzar y de qué depende | Dificultades ya resueltas |
| `## Siguiente paso` | Una frase imperativa con fichero y línea | Una lista de opciones |
| `## Trampas` | Lo que te hizo perder tiempo y volvería a hacerlo | Lo obvio del lenguaje |

**Regla dura: si una sección no aplica, no la escribas.** Nada de «Bloqueos:
ninguno», «N/A» ni «—». El validador las rechaza, y las secciones vacías son
exactamente por donde estos documentos engordan.

Qué merece el presupuesto:

- **El porqué de las decisiones.** El *qué* ya está en el código y en git; el
  *porqué* no está en ninguna parte y es lo que se pierde al cerrar la sesión.
- **Rutas y líneas concretas**, no descripciones («`src/pagos.ts:214`», no «el
  módulo de pagos»).
- **Lo que no se deduce leyendo el repo.** Si se recupera en 30 segundos mirando
  el código, no lo escribas.

No repitas la rama, el commit ni los ficheros modificados: eso lo pone el código.

## 4. Escribe

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" escribir --modo <memoria|continuacion>
```

Según el código de salida:

- **0** — escrito. Reporta al usuario la ruta, el modo y las líneas usadas. **Para
  ahí**: no abras sesión nueva y no sigas trabajando.
- **1 — no cabe.** Recorta y repite. Si te rechaza dos veces, la tercera **no
  reescribas más corto: borra una sección entera**. Acortar frases no baja 27
  líneas; borrar `Trampas` sí. Reescribe el borrador **entero** con `Write`, nunca
  con `Edit`.
- **2 — estructura mal.** Arregla lo que diga el error (falta `Estado`, sección
  inventada, relleno, `continuacion` sin `Siguiente paso`). No es un problema de
  tamaño: no recortes.
- **3 — entorno.** Para y cuéntaselo al usuario. No reintentes.

## Cuando te lo pide el hook tras una compactación

Si llegas aquí porque baton te lo pidió al terminar un turno, el resumen de la
compactación está en tu contexto: es tu mejor material. Haz lo mismo de siempre y
sigue el presupuesto — **no copies el resumen**, destílalo.
