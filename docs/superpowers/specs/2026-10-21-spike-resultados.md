# Prueba previa (spike) del traspaso al compactar y del mod — resultados

Fecha: 2026-10-21. Claude Code: 2.1.307, llamado por su ruta fija
(`~/.local/share/claude/versions/2.1.307`) con `DISABLE_AUTOUPDATER=1`. baton de partida: `0e4e0fc`.
Diseño que se comprueba: `2026-10-21-traspaso-al-compactar-y-panel-design.md`.

## Cómo se hizo

Nada de esto tocó una sesión ni un proyecto real de Miguel.

- **Plugin de prueba:** una copia de baton en el scratchpad con cuatro añadidos:
  - `"modules": ["./mod/register.tsx"]` en `hooks/hooks.json`, junto a `"hooks"`;
  - un mod mínimo: toast en `session.start`, `baton_mod: true` en los eventos clásicos y dos intentos
    de abrir un panel tras `/clear`;
  - un hook de Python que vuelca su stdin a un archivo;
  - un `PreCompact` y un `PostCompact` provisionales, escritos a mano.
- **Proyecto desechable:** un repositorio git con copia de baton, `language: es` y un `.baton/HANDOFF.md`
  escrito con `baton.py write`.
- **Para que no corrieran dos baton a la vez:** cada corrida llevó `--plugin-dir <copia>` y
  `--settings '{"enabledPlugins":{"baton@baton":false}}'`. El log de depuración confirma que solo cargó
  la copia: `Plugin "baton" from --plugin-dir overrides installed version` y
  `enabled=false; will NOT register` para la instalada.
- **Sesiones interactivas:** con `expect` en una pseudoterminal de 160×50 (y de 120×50 para S4), sin
  tmux. Así se vio lo que ve una persona, no solo lo que queda en la transcripción.
- **Sesión grande:** `claude -p` leyendo el código de baton en tres turnos, hasta 114 140 tokens
  (`preTokens`). Después, `claude -p --resume <id> --fork-session ... "/compact"` dos veces, cada una
  sobre una bifurcación, así que la sesión base quedó sin compactar.
- **Versión de Claude Code.** Durante el spike, Claude Code se actualizó solo a 2.1.308. Pasó durante
  la primera sesión interactiva de S1, lanzada con el comando `claude`. Esa sesión todavía corrió en
  2.1.307: su banner dice `Claude Code v2.1.307` y al final sale `✔ Update installed · Restart to update`.
  - **Antes de la actualización, con `claude`, que aún era 2.1.307:** el primer
    `claude plugin validate`, la corrida corta `-p` de S1, S2 y S3, y las sesiones interactivas de S1.
  - **Después, todo con la ruta fija `~/.local/share/claude/versions/2.1.307` y
    `DISABLE_AUTOUPDATER=1`:** los `validate` siguientes, S4 a 160 y 120 columnas, los tres turnos que
    hicieron crecer la sesión, las dos compactaciones `-p` y la compactación interactiva de S6.
  - **Ningún resultado se obtuvo en 2.1.308.** Las búsquedas en el binario también se hicieron en el
    de 2.1.307.
  - **Queda cambiado en la máquina:** `~/.local/bin/claude` apunta ahora a `versions/2.1.308`.

## S1 — Hooks clásicos y `modules` en un mismo `hooks/hooks.json`: **pasa**

- `claude plugin validate` → `✔ Validation passed`. Lista los hooks del módulo y no se queja de que
  convivan con `"hooks"`. Solo avisa `gating hook without .catch` en cada `classic.*`: el mod de verdad
  tiene que ponerles `.catch`.
- En la terminal real se ve el toast, dibujado en su recuadro:
  ```
  ╭── ╮
  │ baton mod ok │
  ╰── ╯
  ```
- El log de baton registra el arranque:
  `{"event": "session-start", "result": "injected memory mode", "source": "startup"}`.
- En `-p` el toast no se pinta, y el log de depuración lo dice:
  `$.ui.toast (baton): no notification bar in a headless session; kept here: baton mod ok`.
- Debug: `hooks module baton@inline loaded (worker, environment 1, tier user); events: session.start,…`
  y `plugin.register: baton (user, baton@inline), judged by core alone: admitted`.
- **Aviso para el mod de verdad:** cada `$.ui.log` aparece en la transcripción como una fila propia
  (`⏺ baton: baton-spike: classic.SessionStart`). No hay que usarlo para cosas de rutina.

## S2 — Cómo encuentra el mod su carpeta: **`$.plugin.root`**

Las dos formas funcionan. Esto es lo que dejó escrito el mod en `session.start`:

```
"pluginRoot": "/private/tmp/…/scratchpad/spike/plugin",
"importMetaUrl": "file:///private/tmp/…/scratchpad/spike/plugin/hooks/mod/register.tsx"
```

- **Para la Tarea 7, `$.plugin.root`.** Está en los tipos (`CoreEngineInterface.plugin.root`: «The
  plugin's directory (the one holding plugin.json), absolute»). Es una ruta normal, mientras que
  `import.meta.url` es una URL `file://` donde los espacios salen como `%20`.
- La ruta a Python queda `` `${$.plugin.root}/scripts/baton.py` ``.

## S3 — Señal «mod activo» hacia Python: **sí llega**

`next({ ...e, baton_mod: true })` en `classic.*` hace llegar el campo al stdin de los hooks de Python,
en los cuatro eventos. Lo muestra el volcado de `spike_dump.py`:

```
SessionStart fork    baton_mod= True
PreCompact   manual  baton_mod= True
SessionStart compact baton_mod= True
PostCompact  manual  baton_mod= True
Stop (sesión corta)  baton_mod= True
```

Tras un `/clear` también llega, porque el mod recibe `classic.SessionStart` con `source: "clear"`.
Así que la señal vale también para el caso que el diseño exige.

## S4 — Abrir el panel tras `/clear`: **los dos caminos lo abren** (repetir en la Tarea 12)

- **En los tipos.** Un mod puede engancharse a `classic.SessionStart` con matcher `{ source: 'clear' }`
  (`ClassicEventOf`) y llamar `$.ui.open` (`ui.open(pane: PaneOpenArgs): Promise<UiOpenResult>`).
  Los tipos también dicen que tras `/clear` no hay `session.start`: «`clear` is how a hook sees a
  `/clear`… and no `session.start` fires for it».
- **Observado en terminal real de 160 columnas.** Los dos intentos devolvieron `{"isPlaced": true}` y
  se dibujaron:
  - `on('classic.SessionStart', { source: 'clear' })` + `$.ui.open` inmediato;
  - `on('session.end')` con `reason === 'clear'` + `$.clock.after(1500, …)` + `$.ui.open`.

  En pantalla, tras `/clear`, salen los títulos `baton via SessionStart  baton via session.end` y los
  contenidos `PANEL-DESDE-CLASSIC-SESSIONSTART` y `PANEL-DESDE-SESSION-END`.
- **A 120 columnas** los dos devuelven `isPlaced: false`, con este motivo:
  `"unasked below 144 columns (120 now): placed when the person opens it, or when the terminal is widened to 144 columns"`.
  Abrir el panel desde `/clear` cuenta como **no pedido**, así que el umbral es 144 columnas y no 110.
- **Recomendación:** usar `classic.SessionStart` con `source` `startup|clear`. No necesita
  temporizador y es el mismo evento que baton ya usa.
- **A verificar en la prueba manual de la Tarea 12**, con los mods reales de Miguel cargados
  (`agents-panel`, `clear-questions`).

## S5 — El resumidor entrega el bloque: **el formato pasa 3 de 3; el contenido no**

**Resultado:**

- **El formato pasa en las tres corridas:** bloque al final, modo válido, dentro de 60 líneas y
  aceptado por `baton.py write`.
- **El contenido falla en las corridas 1 y 2:** dan por pendiente algo que ya estaba hecho, y la 2
  eligió `continue` con ese paso. La causa es que el resumidor no ve los mensajes más recientes (ver
  «Hallazgos», punto 1).

**Decisión del controlador (Ruling 5):** los traspasos que salen del resumen se fuerzan a `memory`, y
la instrucción avisa de que los mensajes más recientes quedan fuera de su vista.

Instrucción provisional en `PreCompact`, en inglés, escrita a mano según la interfaz de la Tarea 4.
Pedía:

- terminar con `<baton-handoff mode="…">…</baton-handoff>`;
- las secciones en español;
- un presupuesto de 100 líneas y 5500 caracteres;
- el criterio de modo de la skill.

| Corrida | Sesión | Modo | Líneas del bloque (con etiquetas) | Caracteres del cuerpo | ¿Cierre es lo último? | `baton.py write` |
|---|---|---|---|---|---|---|
| 1 | fork de 114k, `-p` | memory | 28 | 2452 | sí | exit 0, 39/120 líneas |
| 2 | fork de 114k, `-p` | continue | 42 | 3587 | sí | exit 0, 53/120 líneas |
| 3 | interactiva de 52k | memory | 13 | 716 | sí | exit 0, 24/120 líneas |

- Las tres corridas abren con `<baton-handoff mode="…">` y nada más, y las tres caben en 60 líneas.
- Las tres pasan el escritor real: se probó en una copia del proyecto con `.baton/local/draft.md` y
  `baton.py write --mode <modo>`.
- Los resúmenes están en `.baton/local/auto/summary-*.md` del proyecto desechable.
- **Formato del `compact_summary` que recibe `PostCompact`.** Es la salida cruda del modelo:
  `<analysis>…</analysis>`, luego `<summary>…</summary>`, y el bloque **después** de `</summary>`.
- **En la sesión compactada** Claude Code quita `<analysis>` y conserva el bloque. Las tres filas
  `isCompactSummary` contienen `</baton-handoff>`. Es decir, el bloque sí engorda el resumen, como
  prevé el diseño.
- **Problema de calidad (ver «Hallazgos»).** Las corridas 1 y 2 dan por pendiente responder la pregunta
  del README, que en realidad ya estaba respondida. La 2 eligió `continue` con ese mismo paso como
  «Siguiente paso»: una sesión nueva repetiría trabajo hecho.

## S6 — Cómo se ve la salida de un `PostCompact`: **en crudo, dentro del bloque de `/compact`**

**En la transcripción** (fila `user` con `<local-command-stdout>`, sin `isMeta`) no hay una fila propia
para el `systemMessage` del `PostCompact`. El `SessionStart:compact` sí la tiene
(`attachment hook_system_message`). El texto del `PostCompact` va pegado a la salida del comando:

```
Compacted (ctrl+o to see full summary)
PreCompact [python3 ${CLAUDE_PLUGIN_ROOT}/hooks/spike_precompact.py pre-compact] completed successfully: BATON HANDOFF (required, … (la instrucción entera)
PostCompact [python3 ${CLAUDE_PLUGIN_ROOT}/hooks/baton_hook.py post-compact] completed successfully
PostCompact [python3 ${CLAUDE_PLUGIN_ROOT}/hooks/spike_postcompact_msg.py post-compact-msg] completed successfully: {"systemMessage": "baton: prueba"}
```

**En la terminal real** (`/compact` interactivo) se ve igual: la instrucción del `PreCompact` completa,
unas 20 líneas, y el JSON tal cual: `… completed successfully: {"systemMessage": "baton: prueba"}`.

**En el binario** (`J0r` y `nOe` de 2.1.307), la salida de `PostCompact` no se interpreta como JSON.
Cada hook añade una línea `PostCompact [<comando>] completed successfully[: <stdout recortado>]` al
`userDisplayMessage`. Con `PreCompact` pasa lo mismo, y además ese mismo stdout se convierte en
`newCustomInstructions`, y no hay forma de enviarlo al resumidor sin mostrarlo.

Consecuencias para las Tareas 4 y 5:

- **El aviso «traspaso listo» no debe ir como `{"systemMessage": …}`**, porque se vería el JSON. Si
  sale del hook, tiene que ir como texto plano, y aun así lleva delante
  `PostCompact [python3 ${CLAUDE_PLUGIN_ROOT}/hooks/baton_hook.py post-compact] completed successfully: `.
  Con el mod activo lo mejor es que lo diga la franja.
- **La instrucción al resumidor se le muestra a Miguel en cada `/compact`.** También queda en el
  contexto de la sesión compactada: la fila no es `isMeta` y la nota de Claude Code dice «recorded here
  as context for later messages». Conviene que sea corta.
- **Sin comprobar:** cómo se ve el `userDisplayMessage` en una compactación automática o en reposo,
  donde no hay comando `/compact`. Queda para la Tarea 12.

## S7 — Costo del precálculo: **no observado, con un riesgo residual**

**Resultado:** no se observó ningún resumen rehecho con la caché caducada. Queda un caso posible, sin
observar (ver «Riesgo residual» al final de esta sección).

**Decisión del controlador (Ruling 9):** se acepta el riesgo residual; no es parada.

**Lo medido** en `compact_boundary.compactMetadata`:

| Compactación | trigger | preTokens | durationMs | precomputed | uso del resumidor (debug) |
|---|---|---|---|---|---|
| spike 1 | manual | 114140 | 56981 | (ausente) | input 17081, cacheRead 97341, cacheCreate 132, output 6867 |
| spike 2 | manual | 114140 | 74605 | (ausente) | input 17081, cacheRead 97341, cacheCreate 132, output 8490 |
| spike 3 | manual | 52069 | 11702 | (ausente) | — |

El resumidor leyó de caché 97k de los 114k: la caché estaba caliente.

**`precomputed` y `miss_hook` no van donde decía el brief.**

- `compactMetadata` solo lleva `precomputed: true` cuando se reutiliza un precálculo
  (`if(e.precomputed)Se.compactMetadata.precomputed=!0`).
- El motivo (`reuse: "hit" | "miss_hook" | "miss_custom_instructions" | "miss_not_ready"`) solo va a
  telemetría (evento `compaction`, campo `precompute_reuse`). No queda en la transcripción ni en el
  log de depuración. Por eso `miss_hook` no se puede ver desde fuera.

**Compactaciones reales de Miguel** (solo lectura de `~/.claude/projects/*/*.jsonl`):

- 30 `compact_boundary`, y **ninguna** con `precomputed`;
- `durationMs` entre 21 709 y 291 306 ms. Todas calcularon el resumen en el momento, sin reutilizar
  nada;
- las `auto` recientes tienen `preTokens` entre 202k y 607k con ventana de 1M. Son de la compactación
  en reposo, no del umbral.

**Modo de la compactación en reposo de Miguel.** `~/.claude.json` →
`cachedGrowthBookFeatures.tengu_sunny_locket = {"mode": "compact"}`.

- En el binario (`t3o` y `e3o`), ese modo solo dispara si la caché sigue caliente: devuelve `lapsed`
  si no lo está o si llega más de 60 s tarde.
- Llama a `w.compact()` → `compactManually`. Ahí, si el `PreCompact` imprime algo, un precálculo listo
  se descarta (`miss_hook`) y se rehace el resumen, **con la caché caliente**. Según la regla del
  diseño, ese costo se acepta.
- Y, según los datos, Miguel nunca ha tenido un precálculo que reutilizar.

**Riesgo residual, sin observar.**

- **Camino.** `/compact` escrito a mano → `compactManually` → comprobación de reutilización (función
  `A` de 2.1.307).
- **Por qué rehace el resumen.** Si el `PreCompact` de baton imprimió instrucciones, devuelve
  `{hit: false, reuse: "miss_hook"}` antes de mirar el precálculo. Entonces se rehace el resumen en vez
  de reutilizar uno listo.
- **Cuándo pasaría en frío.** Solo si se juntan tres cosas:
  - (1) existe un precálculo listo, por ejemplo del modo `compact_on_return` mientras Miguel no
    estaba, o de otro disparador de precálculo;
  - (2) Miguel vuelve después de que caducó la caché (más de una hora);
  - (3) escribe `/compact` a mano en vez de seguir escribiendo.

  En ese caso el resumen se rehace en frío. Sin baton se habría reutilizado.
- **Lo que se sabe de Miguel:**
  - el modo `compact` no pasa por aquí con la caché fría: dispara solo en caliente;
  - Miguel no está en `compact_on_return`;
  - ninguna de sus 30 compactaciones reales tiene `precomputed`, así que nunca ha reutilizado un
    precálculo.
- **No se puede vigilar desde fuera:** `miss_hook` solo va a telemetría.

## Hallazgos que cambian el plan

1. **El resumidor no ve los últimos mensajes.** Esto contradice la premisa de la Parte 1 («el traspaso
   redactado con la conversación completa»).
   - Claude Code conserva tal cual la cola de la conversación (`preservedMessages`) y resume solo lo
     anterior. El propio binario se lo dice a la sesión compactada: «The messages after this summary
     are the most recent messages from before compaction, kept verbatim. The summary was written
     without seeing them, so something it says has not happened yet may already have happened in
     them.»
   - En las 18 compactaciones reales más recientes de Miguel (y en las del spike), la cola es
     **siempre el último mensaje de texto del asistente** (de 81 a 6342 caracteres). Suele ser la conclusión del turno.
   - En el spike, por eso los bloques 1 y 2 dieron por pendiente algo ya hecho, y el 2 eligió
     `continue`.
   - Tras `/clear`, ese traspaso llevaría a la sesión nueva a repetir trabajo.
   - **Hace falta una decisión de Miguel antes de las Tareas 4 y 5.** Opciones posibles, sin elegir:
     - (a) que `PostCompact` lea la cola desde `transcript_path`
       (`compact_boundary.compactMetadata.preservedMessages`) y la añada al traspaso;
     - (b) forzar `memory` en los traspasos que salen del resumen;
     - (c) avisar en la instrucción y aceptar el riesgo.
   - **Resuelto por el Ruling 5: opción (b).** Los traspasos que salen de una compactación se
     escriben siempre en modo `memory`, diga lo que diga el bloque, y la instrucción del `PreCompact`
     avisa al resumidor de que los mensajes más recientes quedan fuera de su vista.
2. **La salida de `PreCompact` y `PostCompact` se muestra en crudo** (ver S6). La Tarea 5 no debe
   emitir `systemMessage` en `PostCompact`, y la instrucción de la Tarea 4 debe ser breve.
3. **`precomputed` y `miss_hook` no se ven desde fuera** (ver S7). Una «compactación en reposo real»
   solo deja `trigger: auto` y `durationMs`.

## Observaciones al margen (fuera del alcance de esta tarea)

- **Un traspaso pendiente armado por una sesión lo consume otra.** En el spike, el `PostCompact` de una
  bifurcación armó `pending.json`. El primer `Stop` de una sesión **nueva** (`startup`) lo consumió y
  pidió el traspaso; el modelo contestó que no veía ningún resumen. Es el comportamiento de hoy. La
  Tarea 6 debería tenerlo en cuenta.
- **Campos nuevos en `SessionStart`.** Con `source: fork`/`resume`, 2.1.307 trae `context_tokens`,
  `prompt_cache_likely_expired`, `seconds_since_last_response` y `estimated_cache_write_usd`.
