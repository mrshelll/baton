/**
 * Test data only; nothing the mod loads imports it.
 *
 * `SAMPLE` is the stdout of the real `baton.py panel --json --session s1 --cwd <project>`
 * at b985869, re-indented, with the project's path replaced: a git project
 * with a space in its path, a handoff written with `baton.py write`, and a
 * sub-project `sub/radar`. Python writes it with ASCII escapes; `String.raw`
 * keeps them, so this text is what `JSON.parse` meets in a session.
 */
export const SAMPLE = String.raw`
{
  "version": 1,
  "language": "en",
  "state": "normal",
  "project": {
    "name": "proyecto uno",
    "path": "/Users/someone/Mis proyectos/proyecto uno"
  },
  "handoff": {
    "mode": "memory",
    "date": "2026-10-22T07:12:09-05:00",
    "age": "just now",
    "lines": 27,
    "written_by": "manual",
    "stale": false,
    "sections": [
      {
        "slug": "blockers",
        "label": "Blockers",
        "items": [
          "1. refund or webhook first?"
        ],
        "urgent": true
      },
      {
        "slug": "next",
        "label": "Next step",
        "items": [
          "\u2022 finish src/pay.ts:40"
        ],
        "urgent": false
      },
      {
        "slug": "state",
        "label": "State",
        "items": [
          "\u2022 Payment migration half done."
        ],
        "urgent": false
      },
      {
        "slug": "decisions",
        "label": "Decisions and why",
        "items": [
          "- PaymentIntents -- Charges is deprecated"
        ],
        "urgent": false
      },
      {
        "slug": "traps",
        "label": "Traps",
        "items": [
          "- do not touch the seed"
        ],
        "urgent": false
      }
    ]
  },
  "threshold": null,
  "others": [
    {
      "name": "radar",
      "rel": "sub/radar",
      "where": "sub/radar",
      "mode": "continue",
      "age": "48 d ago"
    }
  ],
  "strings": {
    "band_normal": "baton \u00b7 handoff {age} \u00b7 {mode}",
    "band_ready": "baton \u00b7 \u2713 handoff ready \u00b7 {age}",
    "band_threshold": "baton \u00b7 \u26a0 context at {percent} %",
    "band_none": "baton \u00b7 no handoff in this project",
    "band_error": "baton \u00b7 \u26a0 could not read the handoff",
    "band_pending": "baton \u00b7 \u26a0 {n} open items \u00b7 {age}",
    "band_no_project": "baton \u00b7 no project loaded",
    "hint_open": "click \u2192 panel",
    "action_new_session": "New session",
    "action_write": "Write handoff",
    "title": "baton \u00b7 {project}",
    "breadcrumb": "baton \u203a {project}",
    "back": "Back",
    "status_ready": "\u2713 Handoff ready",
    "status_threshold": "\u26a0 Context at {percent} %",
    "status_normal": "\u2713 Handoff saved",
    "status_none": "No handoff",
    "status_error": "\u26a0 Could not read",
    "stale": "\u26a0 Old handoff: the code moved since it was written. Check the state before trusting it.",
    "mode_memory": "memory",
    "mode_continue": "continue",
    "written": "written {age}, {how}",
    "by_compaction": "on compaction",
    "by_hand": "by hand",
    "by_threshold": "after a threshold",
    "lines": "{n} lines",
    "context": "context {percent} %",
    "section_count": "{label} ({n})",
    "see_more": "see more",
    "others": "Other projects",
    "other_line": "{name} \u00b7 {mode} \u00b7 {age}",
    "empty_title": "No handoff in this project yet",
    "empty_hint": "Write one before closing the session or when the context nears its limit: the next session will start from it.",
    "no_project_title": "No project loaded in this session",
    "no_project_hint": "baton does not know which project this session is about. Open one from the list, or write the handoff and it will ask where it goes.",
    "error_read": "Could not read the handoff at {path}.",
    "error_hint": "Open it in your editor to see what it holds; baton leaves it alone until the next handoff.",
    "error_unexpected": "baton could not prepare the panel ({detail})."
  },
  "error": null
}
`

/**
 * `SAMPLE_ES` is the same command in Spanish (`.claude/baton.json` `{"language": "es"}`),
 * run at 7e9705d with `band_pending_one` added to the templates: the root handoff
 * written with `baton.py write --mode memory --project .` (two blockers), a
 * sub-project `sub/radar`, and the project path replaced as above.
 */
export const SAMPLE_ES = String.raw`
{
  "version": 1,
  "language": "es",
  "state": "normal",
  "project": {
    "name": "proyecto uno",
    "path": "/Users/someone/Mis proyectos/proyecto uno"
  },
  "handoff": {
    "mode": "memory",
    "date": "2026-10-22T08:27:51-05:00",
    "age": "reci\u00e9n",
    "lines": 28,
    "written_by": "manual",
    "stale": false,
    "sections": [
      {
        "slug": "blockers",
        "label": "Bloqueos",
        "items": [
          "1. \u00bfseguimos con A o con B?",
          "2. falta la clave de staging"
        ],
        "urgent": true
      },
      {
        "slug": "next",
        "label": "Siguiente paso",
        "items": [
          "\u2022 terminar pay.ts:40"
        ],
        "urgent": false
      },
      {
        "slug": "state",
        "label": "Estado",
        "items": [
          "\u2022 Migraci\u00f3n a medias."
        ],
        "urgent": false
      },
      {
        "slug": "decisions",
        "label": "Decisiones y su porqu\u00e9",
        "items": [
          "- usar X -- porque Y"
        ],
        "urgent": false
      },
      {
        "slug": "traps",
        "label": "Trampas",
        "items": [
          "- no tocar el seed"
        ],
        "urgent": false
      }
    ]
  },
  "threshold": null,
  "others": [
    {
      "name": "radar",
      "rel": "sub/radar",
      "where": "sub/radar",
      "mode": "continue",
      "age": "hace 48 d"
    }
  ],
  "strings": {
    "band_normal": "baton \u00b7 traspaso {age} \u00b7 {mode}",
    "band_ready": "baton \u00b7 \u2713 traspaso listo \u00b7 {age}",
    "band_threshold": "baton \u00b7 \u26a0 contexto al {percent} %",
    "band_none": "baton \u00b7 sin traspaso en este proyecto",
    "band_error": "baton \u00b7 \u26a0 no se pudo leer el traspaso",
    "band_pending": "baton \u00b7 \u26a0 {n} pendientes \u00b7 {age}",
    "band_pending_one": "baton \u00b7 \u26a0 1 pendiente \u00b7 {age}",
    "band_no_project": "baton \u00b7 ning\u00fan proyecto cargado",
    "hint_open": "clic \u2192 panel",
    "action_new_session": "Sesi\u00f3n nueva",
    "action_write": "Escribir traspaso",
    "actionFailed": "baton no pudo hacerlo; int\u00e9ntalo de nuevo.",
    "title": "baton \u00b7 {project}",
    "breadcrumb": "baton \u203a {project}",
    "back": "Volver",
    "status_ready": "\u2713 Traspaso listo",
    "status_threshold": "\u26a0 Contexto al {percent} %",
    "status_normal": "\u2713 Traspaso guardado",
    "status_none": "Sin traspaso",
    "status_error": "\u26a0 No se pudo leer",
    "stale": "\u26a0 Traspaso viejo: el c\u00f3digo cambi\u00f3 desde que se escribi\u00f3. Comprueba el estado antes de fiarte de \u00e9l.",
    "mode_memory": "memoria",
    "mode_continue": "continuar",
    "written": "escrito {age}, {how}",
    "by_compaction": "al compactar",
    "by_hand": "a mano",
    "by_threshold": "tras umbral",
    "lines": "{n} l\u00edneas",
    "context": "contexto {percent} %",
    "section_count": "{label} ({n})",
    "see_more": "ver m\u00e1s",
    "others": "Otros proyectos",
    "other_line": "{name} \u00b7 {mode} \u00b7 {age}",
    "empty_title": "A\u00fan no hay traspaso en este proyecto",
    "empty_hint": "Escribe uno antes de cerrar la sesi\u00f3n o cuando el contexto se acerque al l\u00edmite: la pr\u00f3xima sesi\u00f3n arrancar\u00e1 con \u00e9l.",
    "no_project_title": "Ning\u00fan proyecto cargado en esta sesi\u00f3n",
    "no_project_hint": "baton no sabe de qu\u00e9 proyecto es esta sesi\u00f3n. Abre uno de la lista, o escribe el traspaso y te preguntar\u00e1 d\u00f3nde va.",
    "error_read": "No se pudo leer el traspaso en {path}.",
    "error_hint": "\u00c1brelo con tu editor para ver qu\u00e9 tiene; baton no lo toca hasta el pr\u00f3ximo traspaso.",
    "error_unexpected": "baton no pudo preparar el panel ({detail})."
  },
  "error": null
}
`
