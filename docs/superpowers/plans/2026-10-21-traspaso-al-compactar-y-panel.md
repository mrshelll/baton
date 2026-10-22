# Traspaso al compactar y panel de baton — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que toda compactación deje escrito el traspaso de baton con la conversación completa, y que baton se use desde una franja fija sobre el prompt y un panel, conviviendo con `agents-panel`.

**Architecture:** Parte 1 son hooks clásicos en Python (`PreCompact` nuevo pide el bloque al resumidor; `PostCompact` lo extrae y lo escribe con el mismo camino que `baton.py write`). Parte 2 es un mod TypeScript dentro del mismo plugin que solo dibuja y lanza acciones; todo lo que dibuja lo pide a `baton.py panel --json`, así el parseo del traspaso vive en un solo sitio (Python). Un cambio pequeño en `agents-panel` hace que su franja se apile con la de baton en vez de ceder.

**Tech Stack:** Python 3 stdlib (`unittest`, `tests/run.sh`), API de mods de Claude Code 2.1.307 (`claude-code`, `claude-code/testing`, `claude plugin validate|test`, `tsc`).

**Spec:** `docs/superpowers/specs/2026-10-21-traspaso-al-compactar-y-panel-design.md` (leerla entera antes de cada tarea; este plan no repite su porqué).

## Global Constraints

- Todo hook de Python sale con código 0 por cualquier camino (`tests/test_hook_contract.py`); el `pre-compact` además **nunca imprime JSON ni texto de error**: su stdout se convierte en instrucciones del resumidor.
- Rutas de prueba con espacio y tilde (`tests/helpers.py: BaseCase`); un solo runtime en el repo para la lógica: Python. El mod es TypeScript solo para dibujar.
- No tocar `idleCompaction` ni `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS`. Nunca `/clear` automático.
- Umbrales de baton por defecto `[65, 85]`; `MAX_THRESHOLD = 95` (sin cambios).
- Textos para personas en `templates/es.json` y `templates/en.json` (las dos claves siempre); instrucciones para el modelo, en inglés.
- Mod: solo `e.surface === 'terminal'`; fuera de ahí `next(e)`. Ningún `Button` lleva `hotkey`. Glifos `✓ ⚠ ▸ ·`, nunca emojis. Clave raíz de la franja: `baton:band`. Id del panel: `baton`.
- Si la prueba de la Tarea 1 dice que un `hooks.json` no admite hooks clásicos y `modules` a la vez, o que algún modo rehace el resumen con la caché caducada: **parar y preguntar a Miguel**.
- Conventional Commits; versión final `0.6.0` en `.claude-plugin/plugin.json`; `agents-panel` pasa a `0.3.0`.
- No commitear nada ajeno al plugin (`.baton/HANDOFF.md`, `.baton/local/` quedan fuera).

## Review Focus

1. Un resumen que **cita** las marcas (una conversación sobre baton, como esta) → se toma solo el **último** bloque bien formado al final del resumen; uno mal formado o sin cerrar cae al fallback, nunca escribe basura.
2. Una anotación de `compact-request` de **otra sesión** (o de hace días) no debe hacer que el `SessionStart` de `compact` deje de inyectar ni que la franja diga «traspaso listo».
3. `python3` ausente, `baton.py` que falla, tarda más de 10 s o devuelve JSON inválido → la franja muestra el estado de error y el mod nunca lanza; el resto de la franja (agentes) se sigue dibujando.
4. Raíz con varios proyectos y ninguno activo → `PreCompact` calla, `PostCompact` sigue como hoy, y la franja/panel muestran «sin traspaso» con los otros proyectos como enlaces, sin elegir uno.
5. Terminal estrecha (`bodyColumns` < 60) → la franja recorta el texto (nunca los botones a medias: un `Button` que no cabe entero no se dibuja) y el panel no se abre solo.

---

### Task 1: Prueba previa (spike) — lo que el diseño deja por verificar

Sin código de producto. Resultado: `docs/superpowers/specs/2026-10-21-spike-resultados.md`, una sección por punto con lo observado y la evidencia (comando, línea de log o transcripción).

**Files:**
- Create: `docs/superpowers/specs/2026-10-21-spike-resultados.md`
- Scratch (no se commitea): una carpeta de mod de prueba en el scratchpad, cargada con `claude --plugin-dir`.

- [ ] **S1 — Hooks clásicos y `modules` en un mismo `hooks/hooks.json`.** Copiar el plugin a una carpeta temporal, añadir `"modules": ["./mod/register.tsx"]` junto a `"hooks"` con un mod mínimo que haga `$.ui.toast('baton mod ok')` en `session.start`. Correr `claude plugin validate <carpeta>` y abrir una sesión con `--plugin-dir`. Pasa si se ve el toast **y** el log de baton registra `session-start`. Si no pasa: parar y preguntar a Miguel.
- [ ] **S2 — Cómo encuentra el mod su carpeta.** Probar en el mod mínimo `import.meta.url`, y si no existe, buscar en los tipos (`grep -n "import.meta\|pluginRoot\|root" claude-code.d.ts`). Anotar la expresión que da la ruta absoluta del plugin (la usa la Tarea 7).
- [ ] **S3 — Señal «mod activo» hacia Python.** En el mod mínimo: `on('classic.SessionStart', ($, e, next) => next({ ...e, baton_mod: true }))` (y lo mismo en `classic.Stop` y `classic.PostCompact`). Con un hook de Python que vuelque su stdin a un archivo, comprobar si `baton_mod` llega. Anotar sí/no.
- [ ] **S4 — Abrir el panel tras `/clear`.** Probar `on('session.end', ...)` con `reason === 'clear'` seguido de `$.ui.open({ id: 'baton', title: 'baton' })` (diferido con `$.clock.after` si hace falta) y, alternativamente, `on('classic.SessionStart', { source: 'clear' }, ...)`. Anotar cuál abre el panel en la sesión nueva, o «ninguno».
- [ ] **S5 — El resumidor entrega el bloque.** Con baton actual instalado y un hook `PreCompact` provisional que imprima la instrucción de la Tarea 4 (texto a mano), hacer `/compact` en una sesión real con al menos 100k tokens. Mirar `.baton/local/auto/summary-*.md`: ¿termina en `<baton-handoff mode="…">…</baton-handoff>`, completo y dentro de 60 líneas? Repetir 2 veces.
- [ ] **S6 — Cómo se ve la salida de un `PostCompact`.** Con un `PostCompact` provisional que emita `{"systemMessage": "baton: prueba"}`, anotar si se ve y cómo (línea propia, prefijo `PostCompact [...] completed successfully`, nada).
- [ ] **S7 — Costo del precálculo.** En la transcripción (`compact_boundary.compactMetadata`) de S5 y de una compactación en reposo real si ocurre durante el trabajo, anotar `precomputed`, `durationMs` y si hubo `miss_hook`. Si algún modo rehace el resumen con la caché ya caducada: parar y preguntar a Miguel.
- [ ] **Commit**

```bash
git add docs/superpowers/specs/2026-10-21-spike-resultados.md
git commit -m "docs: resultados de la prueba previa del traspaso al compactar y del mod"
```

---

### Task 2: Destino de escritura sin preguntar, compartido por CLI y hooks

**Files:**
- Modify: `lib/projects.py` (función nueva), `scripts/baton.py:65-127` (`_resolve` la usa)
- Test: `tests/test_multi_project.py`

**Interfaces:**
- Produces: `projects.writable_target(root: Path, found: Discovery, here: Path, root_enabled: bool) -> tuple[Target | None, str]` — devuelve `(target, why)` con `why` en `{"active", "root", "ask_where", "ambiguous"}`; `target` es `None` en los dos últimos. Es exactamente la rama `name is None` de `_resolve`, sin imprimir nada.

- [ ] **Step 1: Tests que fallan** — en `tests/test_multi_project.py`, `TestWritableTarget`:
  - raíz sin proyectos → `(Target(root), "root")`;
  - raíz con dos proyectos, ninguno activo → `(None, "ambiguous")`;
  - raíz **con traspaso propio** y un proyecto, ninguno activo → `(None, "ambiguous")` (el caso que `_hook_target` resolvería mal);
  - proyecto activo → `(Target(root, active), "active")`;
  - `here` debajo de una raíz sin traspaso → `(None, "ask_where")`.
- [ ] **Step 2:** `./tests/run.sh -k TestWritableTarget` → FAIL (`AttributeError: writable_target`).
- [ ] **Step 3:** Implementar en `lib/projects.py` y hacer que `_resolve` llame a `writable_target` para la rama sin nombre, conservando sus mensajes de stderr.
- [ ] **Step 4:** `./tests/run.sh` → todo en verde (incluidos `test_cli.py` y `test_multi_project.py` existentes).
- [ ] **Step 5: Commit** — `refactor: el destino de escritura sin preguntar sale de una sola función`

---

### Task 3: Componer y medir el traspaso fuera de `cmd_write`

**Files:**
- Create: `lib/handoff.py`
- Modify: `scripts/baton.py:240-297` (`cmd_write` usa `handoff.build`)
- Test: `tests/test_handoff.py`

**Interfaces:**
- Produces: `handoff.build(body: str, mode: str, root: Path, cfg: dict, strings: dict) -> Built`, con `Built = (final: str, parsed: document.ParsedDraft, verdict: budget.Verdict)` (dataclass congelada). `build` valida con `document.validate_draft`, toma `gitinfo.snapshot(root)` y compone con `document.compose`; no escribe.
- Produces: `handoff.write_if_fits(paths: storage.Paths, built: Built, cfg: dict) -> str` → `"written"`, `"invalid"`, `"over_budget"` o `"busy"`; solo escribe (con `storage.write_document`) cuando el borrador es válido y cabe. Sin reintentos ni `_minimal_escape`: eso es del CLI.

- [ ] **Step 1: Tests que fallan** — `tests/test_handoff.py`: cuerpo válido en modo `memory` → `write_if_fits` devuelve `"written"` y el documento existe con `mode: memory`; cuerpo sin la sección obligatoria → `"invalid"` y no hay documento; cuerpo de 200 líneas → `"over_budget"` y el documento anterior queda intacto.
- [ ] **Step 2:** `./tests/run.sh -k test_handoff` → FAIL.
- [ ] **Step 3:** Implementar; `cmd_write` pasa a usar `build` y conserva su lógica de intentos y escape.
- [ ] **Step 4:** `./tests/run.sh` → verde (`test_cli.py` cubre que `write` no cambió).
- [ ] **Step 5: Commit** — `refactor: componer y medir el traspaso en lib/handoff para usarlo también desde los hooks`

---

### Task 4: `PreCompact` pide el bloque al resumidor

**Files:**
- Modify: `hooks/hooks.json` (evento `PreCompact`, sin matcher, `args: [..., "pre-compact"]`, `timeout: 10`, sin `statusMessage`), `hooks/baton_hook.py` (handler y salida de texto plano), `lib/storage.py` (`Paths.compact_request` → `.baton/local/compact-request.json`; `note_compact_request`, `read_compact_request`), `lib/output.py` (`compaction_instruction`)
- Test: `tests/test_auto_cycle.py`, `tests/test_hook_contract.py`

**Interfaces:**
- Produces: `output.compaction_instruction(cfg: dict, strings: dict) -> str` — en inglés: al **final** del resumen, escribe `<baton-handoff mode="memory|continue">` + cuerpo + `</baton-handoff>`; secciones válidas `strings["sections"].values()`, obligatoria `strings["sections"][strings["required_section"]]`; presupuesto `cfg["limits"]` del documento completo; cómo elegir el modo (el mismo criterio del paso 2 de `skills/baton/SKILL.md`, resumido en 3 líneas); idioma `cfg["language"]`; «distill, do not copy the summary».
- Produces: `storage.note_compact_request(paths, session_id: str) -> None` escribe `{"session", "requested_at", "written": false}`; `storage.read_compact_request(paths, session_id: str, max_age_hours: int = 12) -> dict | None` devuelve el registro solo si es de esa sesión y reciente.
- Produces: el evento `pre-compact` en `HANDLERS`; su handler devuelve `(text: str, result)` y `main()` lo escribe tal cual (no JSON). Ante excepción: no escribe nada en stdout, solo log.

- [ ] **Step 1: Tests que fallan:**
  - proyecto simple con traspaso → stdout contiene `<baton-handoff mode=` y `</baton-handoff>`, y existe `compact-request.json` con la sesión del payload;
  - raíz con dos proyectos sin activo → stdout vacío, sin `compact-request.json`, log `silent: ambiguous target`;
  - proyecto no habilitado → stdout vacío;
  - `test_hook_contract`: añadir `pre-compact` a `EVENTS`; con stdin no JSON → código 0 y stdout vacío;
  - `language: es` → la instrucción nombra `Estado` como sección obligatoria.
- [ ] **Step 2:** `./tests/run.sh -k test_auto_cycle -k test_hook_contract` → FAIL.
- [ ] **Step 3:** Implementar. El destino sale de `projects.writable_target` (Tarea 2), con `here = entry["cwd"]`. Strings nuevos en las dos plantillas solo si el texto es para personas (la instrucción no lo es).
- [ ] **Step 4:** `./tests/run.sh` → verde.
- [ ] **Step 5: Commit** — `feat: antes de compactar, baton pide al resumidor el traspaso con la conversación completa`

---

### Task 5: `PostCompact` extrae y escribe el bloque, o cae al camino de hoy

**Files:**
- Modify: `lib/document.py` (`extract_compaction_block`), `hooks/baton_hook.py:130-155` (`_post_compact`), `lib/storage.py` (`mark_compact_written`), `templates/es.json`, `templates/en.json` (`auto_handoff.ready`)
- Test: `tests/test_document.py`, `tests/test_auto_cycle.py`

**Interfaces:**
- Consumes: `handoff.build`, `handoff.write_if_fits` (Tarea 3); `read_compact_request` (Tarea 4).
- Produces: `document.extract_compaction_block(summary: str) -> tuple[str, str] | None` → `(mode, body)` del **último** bloque, solo si su cierre `</baton-handoff>` es lo último no vacío del resumen y `mode` ∈ `document.MODES`.
- Produces: `storage.mark_compact_written(paths, session_id: str, fingerprint: str) -> None` (pone `written: true`, `written_at`, `fingerprint`).
- Produces: strings `auto_handoff.ready` = es «baton: traspaso listo. Escribe /clear para seguir en una sesión nueva.» / en «baton: handoff ready. Type /clear to continue in a fresh session.»

- [ ] **Step 1: Tests que fallan:**
  - `extract_compaction_block`: bloque al final → `("memory", cuerpo)`; dos bloques (el primero citado en medio) → el último; bloque sin cerrar → `None`; texto después del cierre → `None`; `mode="otro"` → `None`;
  - `post-compact` con `compact-request` de la sesión y bloque válido → documento escrito, `pending.json` **sin** `armed` nuevo, `compact-request.written == true`, salida `{"systemMessage": <ready>}`, log `handoff written from compaction`;
  - mismo caso con bloque fuera de presupuesto → documento anterior intacto, `armed`, log `compaction block rejected: over_budget`;
  - sin `compact-request` para la sesión → comportamiento de hoy (guardar resumen y armar), aunque el resumen traiga un bloque;
  - con `baton_mod: true` en el payload (o la señal elegida en S3) → mismo resultado sin `systemMessage`.
- [ ] **Step 2:** `./tests/run.sh -k test_document -k test_auto_cycle` → FAIL.
- [ ] **Step 3:** Implementar. El resumen se guarda siempre (`save_summary`), escriba o no. El destino de escritura es el `writable_target` de la Tarea 2, el mismo que usó el `PreCompact`. Si S6 dijo que el `systemMessage` de `PostCompact` no se ve, igual se emite (inofensivo) y el aviso lo da la franja.
- [ ] **Step 4:** `./tests/run.sh` → verde.
- [ ] **Step 5: Commit** — `feat: tras compactar, baton guarda el traspaso que escribió el resumidor`

---

### Task 6: `SessionStart` y `Stop` con la compactación y con el mod activo

**Files:**
- Modify: `hooks/baton_hook.py` (`_session_start`, `_stop`, `_window_request`; función `_mod_active`)
- Test: `tests/test_hook_session_start.py`, `tests/test_auto_window.py`, `tests/test_auto_cycle.py`

**Interfaces:**
- Produces: `_mod_active(entry: dict, cfg: dict) -> bool` — `True` si el payload trae `baton_mod: true` (si S3 lo confirmó) o si `cfg["display"] == "panel"`. Añadir `display` a `config.DEFAULTS` con valor `"receipt"` y validación `{"panel", "receipt"}` en `lib/config.py`; si S3 confirmó la señal, el valor por defecto sigue siendo `"receipt"` y la señal manda.
- Consumes: `read_compact_request` (Tarea 4).

- [ ] **Step 1: Tests que fallan:**
  - `session-start` `source: compact` con `compact-request` de esa sesión → **sin** `additionalContext` del traspaso, log `silent: handoff travels in the compaction summary`;
  - mismo con `compact-request` de **otra** sesión → inyecta como hoy;
  - `session-start` `source: clear` con mod activo → `additionalContext` presente y **sin** `systemMessage`;
  - `stop` con mod activo al 70 % de 1000k → sin `decision: block`, `window.json` con `fired: [65]`, log `threshold 65 announced by the panel`;
  - `stop` sin mod al 70 % → `decision: block` como hoy;
  - `stop` tras compactación con el traspaso escrito (sin `armed`) → silencio.
- [ ] **Step 2:** `./tests/run.sh -k test_hook_session_start -k test_auto_window -k test_auto_cycle` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `./tests/run.sh` → verde.
- [ ] **Step 5: Commit** — `feat: con el panel activo, baton no imprime el recibo ni interrumpe por umbral`

---

### Task 7: `baton.py panel --json`

**Files:**
- Modify: `scripts/baton.py` (subcomando `panel`), `templates/es.json`, `templates/en.json` (bloque `panel` con los textos de franja y panel)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `projects.writable_target`, `output._what_was_left`, `document.read_sections`, `storage.read_window`, `read_compact_request`.
- Produces: `baton.py panel --json --session <id> [--cwd <dir>] [--project <name>]`, código 0 siempre que pueda escribir JSON, con esta forma (versión `1`):

```json
{"version": 1, "language": "es",
 "state": "ready | threshold | normal | none | error",
 "project": {"name": "software-factory", "path": "/abs"} ,
 "handoff": {"mode": "memory", "date": "2026-10-21T08:20:51-05:00", "age": "hace 3 min",
             "lines": 42, "written_by": "compaction | manual", "stale": false,
             "sections": [{"slug": "blockers", "label": "Bloqueos", "items": ["…"], "urgent": true}]},
 "threshold": {"percent": 70, "tier": 65},
 "others": [{"name": "dolores", "mode": "memory", "age": "hace 2 d"}],
 "strings": {"…": "…"},
 "error": null}
```

  - `state`: `ready` si `read_compact_request(session).written` y el `fingerprint` coincide con el documento actual; `threshold` si `read_window(session).fired` no está vacío; `none` si no hay documento; `error` si leerlo falla (con `error` en palabras para personas); si no, `normal`.
  - `sections` en el orden del panel: bloqueos, siguiente paso, estado, decisiones, trampas; `urgent: true` solo en bloqueos. Ítems por línea con viñeta, sin recortar (el mod recorta).
  - `project: null` y `state: "none"` cuando `writable_target` es ambiguo; `others` lista los proyectos encontrados.

- [ ] **Step 1: Tests que fallan:** un caso por `state`, más raíz ambigua (`project: null`, `others` con 2), más `--session` distinto al del `compact-request` (`state != "ready"`), más documento ilegible (`state: "error"`, código 0).
- [ ] **Step 2:** `./tests/run.sh -k test_cli` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `./tests/run.sh` → verde.
- [ ] **Step 5: Commit** — `feat: baton.py panel entrega en JSON todo lo que dibuja el mod`

---

### Task 8: El mod — esqueleto, datos y señal

**Files:**
- Modify: `hooks/hooks.json` (`"modules": ["./mod/register.tsx"]`, según S1), `.claude-plugin/plugin.json` (`"types": "./types/index.d.ts"`)
- Create: `hooks/mod/register.tsx`, `hooks/mod/data.ts`, `types/index.d.ts`, `tsconfig.json` (como el de `agents-panel`)
- Test: `hooks/mod/data.test.ts`

**Interfaces:**
- Produces: `types/index.d.ts` → `interface PluginState { baton: { panel: PanelData | null; loadedAt: number } }` con `PanelData` igual al JSON de la Tarea 7.
- Produces: `loadPanel($, sessionId: string, cwd: string): Promise<PanelData>` en `data.ts` — `$.process.run(['python3', <raíz del plugin según S2> + '/scripts/baton.py', 'panel', '--json', '--session', sessionId, '--cwd', cwd], { timeoutMs: 10_000 })`; cualquier fallo (código ≠ 0, JSON inválido, `version` ≠ 1, rechazo) devuelve `{ state: 'error', … }` con el texto `strings.loadFailed` de un respaldo interno en inglés; nunca lanza.
- Produces: `refresh($)` recarga en `session.start`, al terminar cada turno (`turn.complete`), tras `session.compact` y cuando un botón actúa.
- Produces: la señal «mod activo» elegida en S3 (hooks `classic.SessionStart`, `classic.Stop`, `classic.PostCompact` que añaden `baton_mod: true`), o nada si S3 dijo que no llega.

- [ ] **Step 1: Tests que fallan** (`claude-code/testing`, sobre `terminal`): `loadPanel` con un `$.process.run` simulado que devuelve el JSON de ejemplo → `state: 'normal'`; con código 1 → `state: 'error'`; con `stdout` no JSON → `'error'`; con rechazo por timeout → `'error'`.
- [ ] **Step 2:** `claude plugin test .` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `claude plugin validate .` sin errores, `tsc -p .` sin errores, `claude plugin test .` verde, `./tests/run.sh` verde.
- [ ] **Step 5: Commit** — `feat: el mod de baton carga su estado desde baton.py`

---

### Task 9: La franja

**Files:**
- Create: `hooks/mod/band.tsx`
- Modify: `hooks/mod/register.tsx`
- Test: `hooks/mod/band.test.ts`

**Interfaces:**
- Consumes: `PanelData` (Tarea 8).
- Produces: `bandLine(data: PanelData, columns: number): BandModel` (puro) y `band(t, model, actions)`; `isEmptyBand(tree)` con la misma definición que `agents-panel`; `stack(below, mine)` = `Box` en columna con `key: 'baton:band'` solo en la caja de baton.
- Acciones: `newSession` → `$.command.run({ command: 'clear' })`; `writeHandoff` → `$.command.run({ command: 'baton:baton' })`; `openPanel` → `$.ui.open({ id: 'baton', title: 'baton', focus: true })`; errores → `$.ui.toast(strings.actionFailed)`.

- [ ] **Step 1: Tests que fallan:**
  - `bandLine` por estado, con los textos de la tabla de la spec (es y en): `ready` → «✓ traspaso listo · hace 3 min» + botón `Sesión nueva`; `threshold` → «⚠ contexto al 70 %» + `Escribir traspaso`; `none` → «sin traspaso en este proyecto» + `Escribir traspaso`; `error` → «⚠ no se pudo leer el traspaso»; `normal` sin pendientes → «traspaso de hace 2 h · memoria» + pista `clic → panel`; `normal` con pendientes → «⚠ 2 pendientes · hace 2 h»;
  - `columns = 40` → el texto se recorta con `…`, la pista `clic → panel` desaparece, y un botón que no cabe entero no se dibuja;
  - render con `hasSurvey: true` → devuelve exactamente lo de abajo;
  - abajo vacío → solo la línea de baton; abajo un árbol de otro plugin → columna [árbol de abajo, línea de baton];
  - ningún `Button` del árbol tiene `hotkey`; `surface: 'desktop'` → `next(e)` sin cambios.
- [ ] **Step 2:** `claude plugin test .` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `claude plugin validate .`, `tsc -p .`, `claude plugin test .` → verdes.
- [ ] **Step 5: Commit** — `feat: la franja de baton, una línea siempre visible que se apila con los demás mods`

---

### Task 10: El panel

**Files:**
- Create: `hooks/mod/pane.tsx`
- Modify: `hooks/mod/register.tsx`
- Test: `hooks/mod/pane.test.ts`

**Interfaces:**
- Consumes: `PanelData`, acciones de la Tarea 9.
- Produces: `pane(t, data, view, actions, columns)` con `view` en `$.state` (`{ project: string | null, open: { decisions: boolean, traps: boolean, more: string[] } }`), y la apertura automática.

- [ ] **Step 1: Tests que fallan** (contenido según la sección «El panel» de la spec):
  - cabecera: proyecto, estado con icono y palabra, «memoria · escrito hace 3 min, al compactar · 42 líneas · contexto 8 %» (el porcentaje de `$.session.usage()`; sin cifra, se omite ese tramo); acción principal `Sesión nueva` en `ready`, `Escribir traspaso` en los demás;
  - orden del cuerpo: Bloqueos (con ⚠ y cuenta) → Siguiente paso → Estado; Decisiones y Trampas plegadas con su cuenta; al pulsar se despliegan; una sección de más de 6 ítems muestra 6 y «ver más»;
  - `others` como botones; al pulsar uno, cabecera `baton › dolores` y botón `Volver`;
  - `none` → «Aún no hay traspaso en este proyecto», pista y `Escribir traspaso`; `error` → qué pasó y «Abre .baton/HANDOFF.md para revisarlo»;
  - `stale: true` → «⚠ El código cambió desde que se escribió»;
  - apertura automática: tras `startup`/`clear` (evento según S4) abre el panel solo si `sections` tiene ítems con `urgent: true`; con `bodyColumns` < 110 o sin evento fiable no lo abre (la franja ya muestra «⚠ N pendientes»).
- [ ] **Step 2:** `claude plugin test .` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `claude plugin validate .`, `tsc -p .`, `claude plugin test .` → verdes.
- [ ] **Step 5: Commit** — `feat: el panel de baton muestra el traspaso completo y se abre solo si quedan pendientes`

---

### Task 11: `agents-panel` se apila con la franja de baton

Repositorio aparte: `mrshelll/agents-panel` (usar la copia de trabajo de Miguel si existe; si no, clonarlo; no editar `~/.claude/plugins/cache` ni `~/.claude/plugins/marketplaces`).

**Files:**
- Modify: `hooks/register.tsx` (hook `ui.render` de `AbovePrompt`), `.claude-plugin/plugin.json` (`0.3.0`)
- Test: `hooks/band.test.ts`

**Interfaces:**
- Produces: `isBatonBand(tree: unknown): boolean` — `true` si la raíz es un `Box` con `props.key === 'baton:band'`, o una columna cuyo último hijo lo es.

- [ ] **Step 1: Tests que fallan:** abajo la línea de baton y agentes vivos → columna [recuadro de agentes, línea de baton]; abajo una tarjeta de `clear-questions` → devuelve la tarjeta (como hoy); abajo vacío → recuadro solo (como hoy).
- [ ] **Step 2:** `claude plugin test .` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `claude plugin validate .`, `tsc -p .`, `claude plugin test .` → verdes.
- [ ] **Step 5: Commit** — `feat: el recuadro de agentes se apila con la franja de baton en vez de ceder`

---

### Task 12: Documentación, versión y prueba de punta a punta

**Files:**
- Modify: `README.md`, `README.es.md` (compactación en reposo; corregir «`PreCompact` no sirve para esto»; franja y panel; `display`), `CHANGELOG.md` (`0.6.0`), `.claude-plugin/plugin.json` (`0.6.0`)
- Test: `tests/test_readme.py`, `tests/test_manifest.py`

- [ ] **Step 1:** `./tests/run.sh -k test_readme -k test_manifest` → verde tras los cambios.
- [ ] **Step 2: Prueba manual con Miguel** (anotar resultado en el CHANGELOG solo si algo cambia): sesión real con los dos mods cargados → franja de agentes arriba y baton debajo; `/compact` → aviso «traspaso listo» y `[ Sesión nueva ]`; clic → sesión nueva con el panel abierto si hay pendientes.
- [ ] **Step 3: Commit** — `docs: baton 0.6.0, traspaso al compactar y panel`

## Execution notes

- Tareas 2–7 son Python y dependen en cadena; 8–10 dependen de 7 y de los resultados de S1–S4; 11 solo depende de la clave `baton:band` y puede ir en paralelo con 9–10.
- Rol por tarea (CLAUDE.md de Miguel): 1 `implementador-fino` con Miguel a mano para S5/S7; 2–7 `implementador-fino`; 8–11 `implementador-fino`; 12 `implementador`; revisión por tarea `revisor`; cierre `revisor-final`.
