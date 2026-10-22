# Traspaso al compactar, y baton con franja y panel — diseño

Fecha: 2026-10-21. Claude Code de referencia: 2.1.307. baton de partida: 0.5.1 (`00c2221`).

## Intención

Claude Code añadió la **compactación en reposo**: si la sesión queda quieta cerca de una hora y la
conversación pasa de 200 000 tokens, compacta sola antes de que caduque la caché de prompts (hacia el
90 % del TTL de una hora), para que el regreso no relea todo sin caché. Existe para ahorrar tokens y
Miguel la quiere encendida.

El choque con baton: con ventanas de 1M (Opus 5.5) esa compactación llega al 20–30 % del contexto,
mucho antes del umbral de baton (65 %). Evidencia: en el log de `software-factory/.baton/local/` el
contexto nunca pasó del 48 %, hubo 5 compactaciones `auto`, y todos los traspasos salieron del resumen
de la compactación, pedidos al volver. El traspaso «bueno», escrito con la conversación completa
delante, nunca llegó a pedirse.

Miguel quiere dos cosas:

1. **Que baton guarde el traspaso en el momento de compactar**, con todo el contexto, para que al
   volver le baste con empezar una sesión nueva. Y que baton también sirva para ahorrar tokens.
2. **Que baton se use con clics, no con comandos**: una línea siempre visible encima del prompt y un
   panel que reemplace al recibo que hoy sale arriba tras un `/clear`, conviviendo con los demás mods
   que ya pintan ahí (sobre todo `agents-panel`).

## Metas

1. Toda compactación (en reposo, automática por umbral o `/compact`) deja escrito un traspaso de baton
   redactado con la conversación completa, sin una llamada de modelo aparte.
2. Al volver tras compactar, baton dice «traspaso listo» y ofrece empezar una sesión nueva; no
   interrumpe el primer turno pidiendo el traspaso.
3. Si Miguel no empieza sesión nueva y sigue escribiendo, baton calla: el traspaso ya está guardado
   (decisión de Miguel).
4. baton incluye un mod: una línea fija en la franja sobre el prompt y un panel con el traspaso,
   abiertos con clic. El comando `/baton:baton` sigue existiendo como respaldo (decisión de Miguel).
5. El recibo que hoy imprime el `SessionStart` pasa al panel cuando el mod está activo (decisión de
   Miguel).
6. La franja de baton convive con `agents-panel` y `clear-questions` sin taparlos ni ser tapada.

## No metas

- Tocar la compactación en reposo: ni `"idleCompaction": false` ni `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS`.
- Hacer `/clear` automático. El `/clear` siempre lo decide Miguel, con un clic o escribiéndolo.
- Editar el traspaso desde el panel. Editarlo a mano sigue siendo abrir el archivo.
- Cambiar cómo el hook de Python mide la ventana (`MODEL_WINDOWS`, `window.assess`). El mod puede
  mostrar `$.session.usage()` como cifra, pero los umbrales siguen saliendo de Python.
- Superficies distintas de la terminal en esta versión (desktop, vscode, mobile): el mod pasa
  (`next(e)`) fuera de `terminal`, como hace `agents-panel`.

## Anti-metas (fallaría aunque funcione)

- Que la franja de agentes desaparezca porque baton pinta su línea.
- Que una compactación deje a Miguel sin nada: si el traspaso no sale del resumen, se vuelve al
  comportamiento de hoy (guardar el resumen y pedir el traspaso al volver).
- Que la sesión compactada cargue dos veces el mismo traspaso (en el resumen y reinyectado por el
  `SessionStart` de `compact`).
- Que quien use baton en una versión de Claude Code sin mods pierda algo de lo que tiene hoy.
- Que un dígito tecleado en el prompt vacío pulse un botón de baton.

## Parte 1 — El traspaso se escribe al compactar

### Lo verificado en el código de 2.1.307

- La compactación en reposo, en su modo `compact`, llama a `compactConversation` → `compactManually`
  con `trigger: "auto"`. Corre el `PreCompact` (con `trigger: "auto"`), el resumen, el `PostCompact`
  (con `compact_summary`) y el `SessionStart` con `source: "compact"`: los mismos hooks que hoy.
- En el modo `compact_on_return` el resumen se precalcula mientras Miguel no está; el precálculo
  también corre el `PreCompact` (`trigger: "auto"`) y el `PostCompact` del canje lleva `summaryText`.
- **La salida estándar de un hook `PreCompact` se añade a las instrucciones del resumen**
  (`newCustomInstructions`, unida a lo que haya tras `/compact`). Esta es la palanca.
- Un hook no distingue la compactación en reposo de la automática por umbral: las dos llegan como `auto`.
- Rutas con `compact_summary` vacío: cuando un hook reemplaza la compactación (`hvo`). Ahí no hay
  traspaso que extraer.

### Cómo funciona

1. **`PreCompact` (hook clásico nuevo en `hooks/hooks.json`, sin matcher: vale para `auto` y
   `manual`).** Imprime en inglés una instrucción para el resumidor: al final del resumen, escribe
   además el traspaso de baton entre marcas (por ejemplo
   `<baton-handoff mode="memory|continue">…</baton-handoff>`), con las secciones, el presupuesto y las
   reglas de la skill `baton` (el texto sale de la misma fuente que la skill, no copiado a mano). El
   resto del resumen de Claude Code queda intacto, por si Miguel sigue en la sesión compactada. Si el
   proyecto no tiene un destino que **`baton.py write` aceptaría sin preguntar** (la misma regla de
   `_resolve` en `scripts/baton.py`, que desde 0.4.0 no elige entre varios proyectos de una raíz),
   no imprime nada y esa compactación sigue el camino de hoy. No se usa `_hook_target` para esto: en
   una raíz con traspaso propio y varios proyectos elegiría la raíz y podría reintroducir el fallo
   que corrigió 0.4.0 (decisión del diseñador).
2. **`PostCompact`.** Además de guardar el resumen como hoy, busca el bloque entre marcas. Si lo
   encuentra y es válido, lo escribe por el mismo camino que `baton.py write --mode <modo>`
   (presupuesto, historial, entregas: nada de un escritor paralelo) y **no arma** el pendiente de
   «pedir traspaso tras compactar». Si falta, está cortado o el escritor lo rechaza, arma el
   pendiente como hoy (fallback). El log dice cuál de los dos pasó.
3. **`SessionStart` con `source: "compact"`.** Corre **antes o a la vez** que el `PostCompact` (el log
   de `software-factory` lo muestra en las 5 compactaciones `auto`, en el mismo segundo), así que no
   puede saber si el traspaso salió. Decide por lo que sí sabe: si el `PreCompact` de esta sesión pidió
   el bloque (lo deja anotado en `.baton/local/`, por sesión), **no reinyecta** el traspaso anterior,
   que ya está viejo y el resumen trae uno más nuevo. Si el resumidor no lo entregó, la sesión
   compactada conserva el resumen normal de Claude Code y el fallback pide el traspaso al volver, así
   que nadie se queda sin nada (decisión del diseñador: resuelve el choque entre las dos anti-metas).
   Si el `PreCompact` no pidió nada (sin destino resoluble), se comporta como hoy.
4. **El aviso «traspaso listo»** lo da quien sabe si salió: el `PostCompact`, solo para Miguel
   («baton: traspaso listo. Escribe `/clear` para seguir en una sesión nueva.»). El constructor
   comprueba cómo se ve la salida de un `PostCompact` en 2.1.307 (el código la muestra como
   `userDisplayMessage`) y, si se ve mal, deja el aviso en el estado que lee la franja. Con el mod
   activo lo da la franja (Parte 2) y el hook no imprime nada.
5. **`Stop`.** Sin pendiente armado, calla tras la compactación (meta 3). El umbral del 65 % sigue
   como hoy cuando el mod no está activo (ver Parte 2 con el mod).

### Por qué ahorra tokens

- No hay llamada extra: el traspaso sale en la misma petición del resumen, con la caché caliente.
  Solo se suman sus tokens de salida.
- Desaparece el turno que hoy baton fuerza al volver para redactar desde el resumen.
- Tras `/clear` la sesión nueva arranca con el traspaso (pocos tokens), no con la sesión compactada.

### Riesgos a medir en el spike

- **Reutilización del precálculo.** En `compactManually` (el camino de `/compact` y del modo en reposo
  `compact`), unas instrucciones de hook hacen que no se reutilice un resumen precalculado
  (`reuse: "miss_hook"`) y se calcule uno nuevo. El modo `compact_on_return` va por otro camino
  (`CWn` con el precálculo, que ya corrió el `PreCompact` con las instrucciones) y no lo comprueba.
  Regla (decisión del diseñador): si el recálculo ocurre con la caché todavía caliente (el modo
  `compact` dispara antes de que caduque), se acepta el costo. Si el spike muestra que en algún modo
  el resumen se rehace **con la caché ya caducada**, el constructor se detiene y le pregunta a Miguel
  antes de seguir, porque eso va contra la razón de ser de la compactación en reposo.
- **Que el resumidor cumpla.** Probar con una sesión real grande que el bloque sale completo, dentro del
  presupuesto y con el modo correcto. Si falla seguido, el fallback lo cubre, pero hay que saberlo.
- **Tamaño.** El bloque engorda el resumen que queda en la sesión compactada (del orden del presupuesto
  del traspaso). Aceptado: lo normal es hacer `/clear` después.

## Parte 2 — El mod de baton: franja y panel

### Lo verificado en la API de mods de 2.1.307

- `$.command.run({ command: "clear" })` ejecuta `/clear` como si Miguel lo escribiera, en cola hasta
  que la sesión quede libre. Igual con `baton:baton`.
- La franja sobre el prompt (`AbovePrompt`) es **una sola, compartida**: cada mod recibe con
  `next(e)` lo que pintaron los de abajo. Un hook que falla se salta y el resto se dibuja.
- Los paneles (`Pane`) son independientes por `id`; en terminal se acoplan al lado desde ~110–144
  columnas y van en línea si no.
- Botones: `[ etiqueta ]` en terminal; `hotkey` de un dígito o letra; dos iguales, gana el último.
- No hay zona clicable fuera de la franja y el panel (la línea de estado y los toasts no tienen botones).
- Un mod no puede ocultar ni rediseñar el recibo del `SessionStart` (sesión del 2026-10-06/07).
- `agents-panel` 0.2.0 **cede la franja entera si algo debajo ya pintó** (`isEmptyBand`), para no tapar
  las tarjetas de `clear-questions`. Con baton pintando siempre, según el orden de carga la franja de
  agentes desaparecería.

### Empaquetado

- El mod va **dentro del plugin baton**, en este repositorio (decisión de Miguel). Primera tarea del
  spike: comprobar si un mismo `hooks/hooks.json` puede declarar los hooks clásicos y `modules` a la
  vez. **Si no se puede, el constructor se detiene y le pregunta a Miguel** antes de elegir otra forma
  (por ejemplo un segundo plugin en el mismo marketplace).
- Los textos salen de `templates/es.json` / `en.json` según `language` de la configuración de baton.
- La lógica de leer y entender el traspaso sigue en Python: un subcomando nuevo de `scripts/baton.py`
  (por ejemplo `panel --json`) entrega al mod todo lo que dibuja — modo, fecha, líneas, secciones
  ordenadas, «lo que quedó» (la misma elección que `_what_was_left`), otros proyectos (`cards`),
  estado (traspaso listo tras compactar, umbral cruzado, sin traspaso, error). El mod solo dibuja y
  lanza acciones. (Decisión del diseñador: una sola fuente de verdad para el parseo.)

### Cómo sabe el hook de Python que el mod está activo

Hace falta para tres cosas: no imprimir el recibo, no imprimir el aviso tras compactar, y no bloquear
el `Stop` por umbral. El mecanismo queda al constructor, con estas condiciones: tiene que ser fiable
también tras un `/clear` (en ese caso no se dispara `session.start` del mod; sí `session.end` con
`reason: 'clear'`), y ante la duda el hook se comporta como hoy (mejor un recibo de más que ninguno).
Si no hay forma fiable, una opción de configuración de baton (`display: "panel" | "receipt"`) es un
respaldo aceptable.

### La franja: una línea, siempre

Siempre visible en terminal (decisión de Miguel). Una sola fila, que cambia según el momento:

| Momento | Línea |
|---|---|
| Normal | `baton · traspaso de hace 2 h · memoria   clic → panel` |
| Traspaso listo tras compactar | `baton · ✓ traspaso listo · hace 3 min   [ Sesión nueva ]   clic → panel` |
| Umbral cruzado | `baton · ⚠ contexto al 65 %   [ Escribir traspaso ]   clic → panel` |
| Sin traspaso | `baton · sin traspaso en este proyecto   [ Escribir traspaso ]` |
| No se pudo leer | `baton · ⚠ no se pudo leer el traspaso   clic → panel` |

- La línea es un `Button` (sin `hotkey`) dentro de una caja con `key` y `hover`; clic → abre el panel.
  Los botones de acción van aparte, también sin `hotkey`. `[ Sesión nueva ]` → `$.command.run({ command:
  "clear" })`; `[ Escribir traspaso ]` → `$.command.run({ command: "baton:baton" })`.
- Pista `clic → panel` tenue, a la derecha, solo si cabe en `e.props.bodyColumns`.
- **Con el mod activo, el umbral ya no bloquea el `Stop`**: lo anuncia la franja (aprobado por Miguel
  dentro de la propuesta). El traspaso al compactar (Parte 1) cubre el caso en que nadie pulse.
- El aviso temprano de `PostToolBatch` (el que le dice al modelo que vaya cerrando) no cambia.

**Convivencia:**

- baton llama a `next(e)` primero. Si `e.props.hasSurvey`, devuelve lo de abajo sin añadir nada.
  Si abajo no hay nada (`isEmptyBand`), dibuja su línea sola. Si abajo hay algo, devuelve una
  columna: **lo de los otros arriba, la línea de baton debajo**.
- El árbol de baton lleva una marca reconocible en su caja raíz (por ejemplo `key: "baton:band"`) para
  que otros mods sepan que es una línea que se apila, no una tarjeta ante la que ceder.
- **Cambio en `agents-panel`** (repositorio `mrshelll/agents-panel`, parte de este proyecto): si lo de
  abajo es la línea de baton, la apila debajo de su recuadro en vez de ceder; ante cualquier otra cosa
  (una tarjeta de `clear-questions`) sigue cediendo como hoy. Así, con cualquier orden de carga queda:
  agentes arriba, baton debajo; y una tarjeta de pregunta sigue mandando.
- Tests de los dos lados con `claude plugin test`: los órdenes posibles (baton arriba o abajo de
  agentes), con y sin tarjeta de `clear-questions`, y con encuesta.

### El panel

Se abre con clic en la franja (y con `/baton:baton panel` o equivalente como respaldo: el constructor
elige el nombre del subcomando).

**Apertura sola (decisión de Miguel):** tras un `/clear` o al arrancar la sesión, el panel se abre
solo **si el traspaso tiene pendientes o bloqueos**; si no, solo está la franja. Abierto sin pedirlo,
el panel solo se acomoda al lado en terminal ancha (lo que diga `$.ui.open`: ~110–144 columnas); en
una estrecha espera al clic. Tras `/clear` el mod no recibe `session.start` (sí `session.end` con
`reason: 'clear'`): el constructor verifica en el spike desde qué evento se puede abrir. Si no hay
ninguno fiable, la franja lo anuncia (`baton · ⚠ 2 pendientes · hace 3 min`) y el panel espera al
clic. Contenido, según el manual visual de la fábrica
(`software-factory/factory-orchestrator/references/manual-visual/`, patrón de detalle y reglas base):

```
baton · software-factory                                      ✓ Traspaso listo
memoria · escrito hace 3 min, al compactar · 42 líneas · contexto 8 %
[ Sesión nueva ]   Escribir traspaso

⚠ Pendiente (2)
  1. …
  2. …
Siguiente paso
  …
Estado
  …                                                              ver más
▸ Decisiones (5)   ▸ Trampas (4)

Otros proyectos   dolores · memoria · hace 2 d    factory-portal · continuar · hace 5 d
```

- **Cabecera (DET-01, DET-02):** proyecto, estado con icono y palabra (DEV-05, FUN-27: nunca solo
  color), modo, antigüedad, cómo se escribió («al compactar», «a mano», «tras umbral»; EST-08), líneas
  y contexto actual (`$.session.usage()`).
- **Una acción principal (FUN-08)**, la del momento: «Sesión nueva» tras compactar; «Escribir
  traspaso» en los demás casos. La otra va como secundaria.
- **Cuerpo en orden de importancia (FUN-01, DET-03):** pendientes y bloqueos primero (con ⚠), luego
  siguiente paso, luego estado. Es lo mismo que hoy muestra el recibo, completo.
- **Lo secundario plegado y con nombre (DET-06):** decisiones y trampas. Dos niveles de revelado como
  máximo (DET-07); «ver más» en secciones largas (DET-10).
- **Otros proyectos como enlaces (DET-11)** con su dato decisivo (modo y antigüedad). Al abrir uno:
  `baton › proyecto` y una forma clara de volver (NAV-02, NAV-03).
- **Vacío (EST-01, EST-03, VAC-01 a 03):** «Aún no hay traspaso en este proyecto», una pista concreta
  de cuándo conviene escribir uno, y `[ Escribir traspaso ]`.
- **Error (EST-04):** qué no se pudo leer y qué hacer (por ejemplo, abrir el archivo).
- **Traspaso viejo:** el aviso de frescura que hoy va al modelo se muestra también aquí, con icono y
  palabra.
- **Texto e iconos:** glifos `✓ ⚠ ▸ ·`, nunca emojis (COM-19); textos breves (FUN-44) en el idioma
  configurado; columnas fijas para cifras que cambian (DEV-04); sin `hotkey` de dígito.
- El panel solo muestra y lanza acciones; no edita.

### Adenda (2026-10-22, tras la prueba manual): un recuadro, dos secciones

En la prueba real, la línea suelta de baton bajo el recuadro de agentes se veía desalineada (MAR:
dos barras apiladas con bordes que no coinciden se leen como dos productos o un descuido). Miguel
decidió **un solo recuadro con dos secciones, las dos siempre visibles** (no pestañas: COM-05, y
la franja de baton se ve siempre). Encima del prompt el motor no tiene pestañas ni marcos
compartidos, así que baton y `agents-panel` cooperan con este contrato, idéntico en los dos repos:

- **Sección:** cada mod dibuja su parte como un `Box` en columna, sin borde, con clave
  `baton:section` o `agents-panel:section`. Su primera fila es el título (`baton` / `agentes`), en
  negrita y `color="claude"`, como hoy el título de agentes; debajo, sus filas. La de baton es la
  línea de estado de hoy sin el prefijo `baton · ` (el título ya lo dice): texto, botón de acción y
  `clic → panel`.
- **Recuadro:** un `Box` con clave `band:frame`, `borderStyle="round"`, `borderColor="claude"`,
  `borderDimColor`, `flexDirection="column"`, `paddingX={1}` (el estilo del recuadro de agentes de
  hoy). Sus hijos son secciones, en orden fijo: `agents-panel:section` primero, `baton:section`
  después, cualquier otra sección conocida al final en el orden en que llegó; entre dos secciones,
  una fila divisoria `─` atenuada del ancho interior.
- **Componer:** el hook de cada mod mira lo de abajo (`next(e)`):
  - vacío → `band:frame` con su sección sola;
  - un `band:frame` → extrae sus secciones, añade la propia (reemplazando una con su misma clave),
    ordena y reconstruye el recuadro con divisorias; da igual qué mod quede arriba en la cadena;
  - cualquier otro árbol no vacío (una tarjeta de `clear-questions`): como hoy. baton se apila
    debajo con su propio recuadro (columna `[lo de abajo, band:frame]`); `agents-panel` cede la
    franja entera.
  - `hasSurvey`: como hoy (nadie añade nada).
- **Ancho:** el recuadro ocupa `bodyColumns`; el ancho interior es `bodyColumns - 4`. Las reglas de
  ancho de cada sección (Ruling 14 en baton) se aplican sobre el ancho interior.
- **Sin el otro mod:** cada uno dibuja su recuadro con su sección sola; se ve igual que hoy el de
  agentes. `agents-panel` < 0.3.0 no conoce el contrato y cede ante el recuadro de baton.

## Lo que no cambia

- Sin el mod (Claude Code sin mods u otra superficie): recibo, `Stop` por umbral y comando, como hoy;
  más la Parte 1, que solo usa hooks clásicos.
- El formato del traspaso, la skill `baton`, el presupuesto y el historial.

## Entregables

- baton 0.6.0: hooks clásicos (`PreCompact` nuevo; `PostCompact`, `SessionStart` y `Stop` ajustados),
  subcomando para el panel, el mod (franja y panel) con sus tests, `templates/es.json` y `en.json`,
  `README.md`, `README.es.md` y `CHANGELOG.md` (incluida la explicación de la compactación en reposo,
  y que la tesis de README «`PreCompact` no sirve para esto» se corrige: sí sirve, a través del
  resumidor).
- `agents-panel`: el cambio de convivencia y su test, con su propia versión.
- Tests de Python existentes en verde y nuevos para: extracción del bloque, fallback, no reinyectar en
  `compact`, silencio del `Stop`.

## Queda al constructor

- Las marcas exactas del bloque y el texto de la instrucción al resumidor.
- El mecanismo para saber si el mod está activo (con las condiciones de arriba).
- El nombre del subcomando del panel y la forma del JSON.
- La disposición fina de la franja y el panel dentro de las reglas citadas.
