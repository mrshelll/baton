/**
 * baton's contract with its own mod: what `scripts/baton.py panel --json`
 * prints (version 1), and the state the mod keeps it in for the band and the
 * pane to draw from. baton.py reads and understands the handoff; the mod only
 * draws it. Self-contained on purpose: a contract file imports nothing.
 */

/** Which of the panel's faces to draw, as baton.py decided it. */
export type PanelState = 'ready' | 'threshold' | 'error' | 'normal' | 'none'

/** One section of the handoff, in the panel's order. */
export type PanelSection = {
  slug: 'blockers' | 'next' | 'state' | 'decisions' | 'traps'
  /** The section's label in the project's language. */
  label: string
  /** One per line of the document, its own marker kept (`1.`, `-`), else `• `. Sanitized. */
  items: string[]
  /** True for blockers alone. */
  urgent: boolean
}

/** The handoff on disk, as the project's document holds it. */
export type PanelHandoff = {
  mode: 'memory' | 'continue'
  /** The document's date, sanitized; null when it names none. */
  date: string | null
  /** How long ago, already in words (`just now`, `hace 2 d`). */
  age: string
  lines: number
  written_by: 'compaction' | 'manual'
  /** Git moved since it was written. */
  stale: boolean
  sections: PanelSection[]
}

/** Another project baton found under the session's root. */
export type PanelOther = {
  /** Sanitized and capped: the one to draw. */
  name: string
  /** Raw, relative to the root: the handle `baton.py --project` takes. Never drawn. */
  rel: string
  /** `rel` sanitized: what the mod draws for where it is. */
  where: string
  mode: 'memory' | 'continue'
  age: string
}

/**
 * Every person-facing text of the band and the pane, in the project's
 * language, `{fields}` left for the mod to fill. `loadFailed` is the mod's own
 * and comes from its English fallback, never from baton.py.
 */
export type PanelStrings = {
  band_normal: string
  band_ready: string
  band_threshold: string
  band_none: string
  band_error: string
  band_pending: string
  band_no_project: string
  hint_open: string
  action_new_session: string
  action_write: string
  title: string
  breadcrumb: string
  back: string
  status_ready: string
  status_threshold: string
  status_normal: string
  status_none: string
  status_error: string
  stale: string
  mode_memory: string
  mode_continue: string
  written: string
  by_compaction: string
  by_hand: string
  by_threshold: string
  lines: string
  context: string
  section_count: string
  see_more: string
  others: string
  other_line: string
  empty_title: string
  empty_hint: string
  no_project_title: string
  no_project_hint: string
  error_read: string
  error_hint: string
  error_unexpected: string
  loadFailed: string
}

/** The JSON of `baton.py panel --json`, version 1. */
export type PanelData = {
  version: 1
  /** The language `strings` are in. */
  language: string
  state: PanelState
  /** The project shown; null when no project is loaded in this session. */
  project: { name: string; path: string } | null
  handoff: PanelHandoff | null
  /** Set once THIS session crossed a context threshold. */
  threshold: { percent: number | null; tier: number } | null
  others: PanelOther[]
  strings: PanelStrings
  /** What went wrong, ready to draw; null when nothing did. */
  error: string | null
}

declare module 'claude-code' {
  interface PluginState {
    baton: {
      /** The last panel loaded; null (or never written) before the first load ends. */
      panel: PanelData | null
      /** When that load ended, in ms since the epoch (`$.clock.now()`). */
      loadedAt: number
    }
  }
}
