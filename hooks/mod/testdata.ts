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
    "band_pending": "baton \u00b7 \u26a0 {n} open \u00b7 {age}",
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
