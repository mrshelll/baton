import type { ElementTable, RenderElement } from 'claude-code'
import type { PanelData, PanelStrings } from '../../types'

/**
 * The band: one row above the prompt that baton always draws on the terminal,
 * saying where the handoff stands, with the action of the moment and a way into
 * the panel. Every word comes from `data.strings` (the project's language);
 * this file only picks, fills and fits them.
 */

/** Between the line, its button and the hint, as the spec's table spaces them. */
export const GAP = 3
/** What the terminal draws around a Button's label: `[ ` and ` ]`. */
const BUTTON_CHROME = 4

/** The two actions the band offers, by what they do. */
export type BandAction = 'newSession' | 'writeHandoff'

/** What the band draws, fitted to its width: the pure half of the band. */
export type BandModel = {
  /** The line, one row, cut with `…` when wider than the band. */
  text: string
  /** Its color; the glyph in the text says the same (never color alone). */
  tone: 'success' | 'warning' | undefined
  /** The button of the moment, drawn only when it fits whole. */
  action: { kind: BandAction; label: string } | null
  /** `clic → panel`, dim, only when it fits after the rest. */
  hint: string | null
}

/** What the band's Buttons run. Each one never throws. */
export type BandActions = {
  newSession: () => void
  writeHandoff: () => void
  openPanel: () => void
}

/** A face before fitting: the words and what goes with them. */
type Face = { text: string; tone: BandModel['tone']; action: BandAction | null; hint: boolean }

/** Cells a text takes, counted by code point: every glyph the strings use is one cell. */
function width(text: string): number {
  return Array.from(text).length
}

/** One row: line breaks and runs of spaces become one space. */
function oneLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** At most `max` cells, ending in `…` when cut. */
function cut(text: string, max: number): string {
  const chars = Array.from(text)
  if (chars.length <= max) return text
  if (max <= 0) return ''
  return `${chars.slice(0, max - 1).join('').trimEnd()}…`
}

/** The template with its `{fields}` filled; one with no value stays as written. */
function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => (name in values ? String(values[name]) : whole))
}

/** The items left in the handoff's urgent sections (the blockers): what the band counts as open. */
function pending(data: PanelData): number {
  return (data.handoff?.sections ?? []).filter(s => s.urgent).reduce((n, s) => n + s.items.length, 0)
}

/**
 * Which line the panel's state calls for. A face missing what it names (a
 * ready one with no handoff, a threshold with no reading) draws the face the
 * rest of the data supports, never a hole in the template.
 */
function face(data: PanelData): Face {
  const s: PanelStrings = data.strings
  const h = data.handoff
  // A reading with no percent still crossed its threshold, which is a percent too.
  const percent = data.threshold?.percent ?? data.threshold?.tier
  if (data.state === 'ready' && h) {
    return { text: fill(s.band_ready, { age: h.age }), tone: 'success', action: 'newSession', hint: true }
  }
  if (data.state === 'threshold' && typeof percent === 'number') {
    return { text: fill(s.band_threshold, { percent }), tone: 'warning', action: 'writeHandoff', hint: true }
  }
  if (data.state === 'error') {
    return { text: s.band_error, tone: 'warning', action: null, hint: true }
  }
  if (h && data.state !== 'none') {
    const open = pending(data)
    if (open > 0) {
      const template = open === 1 ? s.band_pending_one : s.band_pending
      return { text: fill(template, { n: open, age: h.age }), tone: 'warning', action: null, hint: true }
    }
    const mode = h.mode === 'continue' ? s.mode_continue : s.mode_memory
    return { text: fill(s.band_normal, { age: h.age, mode }), tone: undefined, action: null, hint: true }
  }
  // Nothing written yet: writing is the thing to do (with no project, baton asks where).
  return { text: data.project ? s.band_none : s.band_no_project, tone: undefined, action: 'writeHandoff', hint: false }
}

/**
 * The band's line for `data`, fitted to `columns`: the line first, whole when
 * it fits and cut with `…` when not; then the action's button if it fits whole
 * beside it; then the hint if there is still room. Pure.
 */
export function bandLine(data: PanelData, columns: number): BandModel {
  const f = face(data)
  const text = oneLine(f.text)
  const room = Math.floor(columns)
  if (width(text) > room) return { text: cut(text, room), tone: f.tone, action: null, hint: null }
  let used = width(text)
  let action: BandModel['action'] = null
  if (f.action !== null) {
    const label = oneLine(f.action === 'newSession' ? data.strings.action_new_session : data.strings.action_write)
    const needs = GAP + BUTTON_CHROME + width(label)
    if (used + needs <= room) {
      action = { kind: f.action, label }
      used += needs
    }
  }
  const hint = oneLine(data.strings.hint_open)
  return { text, tone: f.tone, action, hint: f.hint && used + GAP + width(hint) <= room ? hint : null }
}

/** The Button keys, by action: what `ui.press` names. */
const ACTION_KEYS: Record<BandAction, string> = { newSession: 'baton:new-session', writeHandoff: 'baton:write' }

/**
 * The band drawn: a row whose root is the Box keyed `baton:band`, the mark
 * other mods read as "a line that stacks", not a card to yield to. The line
 * is a Button that opens the panel; the action's own Button follows it.
 */
export function band(t: ElementTable<'terminal'>, m: BandModel, act: BandActions): RenderElement {
  const { Box, Button, Text } = t
  const action = m.action
  return (
    <Box key="baton:band" flexDirection="row" justifyContent="space-between" gap={GAP}>
      <Box flexDirection="row" gap={GAP}>
        <Button key="baton:open" label={m.text} plain onPress={() => act.openPanel()}>
          <Text wrap="truncate-end" color={m.tone} hover={{ scope: 'baton:open', underline: true }}>{m.text}</Text>
        </Button>
        {action && (
          <Button
            key={ACTION_KEYS[action.kind]}
            label={action.label}
            variant="primary"
            onPress={() => (action.kind === 'newSession' ? act.newSession() : act.writeHandoff())}
          />
        )}
      </Box>
      {m.hint !== null && <Text wrap="truncate-end" dimColor>{m.hint}</Text>}
    </Box>
  )
}

/**
 * True when nothing beneath drew the band: nothing, or the engine's own node
 * (`{ type: 'engine', ref }`), which is what `next(e)` resolves to when no plugin drew.
 * Anything else is another plugin's tree. The same definition as agents-panel 0.2.0's.
 */
export function isEmptyBand(tree: unknown): boolean {
  return tree === null || tree === undefined || (typeof tree === 'object' && (tree as { type?: unknown }).type === 'engine')
}

/**
 * baton's line with what was drawn beneath it: alone over an empty band, else
 * a column with theirs above and baton's below. The column takes no key: only
 * baton's own Box carries `baton:band`.
 */
export function stack(below: RenderElement, mine: RenderElement): RenderElement {
  return isEmptyBand(below) ? mine : { type: 'Box', props: { flexDirection: 'column' }, children: [below, mine] }
}
