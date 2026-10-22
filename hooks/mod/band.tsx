import type { ElementTable, RenderElement } from 'claude-code'
import type { PanelData, PanelStrings } from '../../types'

/**
 * The band: baton's section above the prompt, always drawn on the terminal,
 * saying where the handoff stands, with the action of the moment and a way into
 * the panel. Every word of the status comes from `data.strings` (the project's
 * language); this file only picks, fills and fits them.
 *
 * The section sits in a frame shared with agents-panel (the spec's «Adenda
 * (2026-10-22)»): each mod draws a Box keyed `<mod>:section`, and whichever hook
 * runs last rebuilds the one frame, keyed `band:frame`, from the sections
 * beneath plus its own, in a fixed order. agents-panel's `hooks/views/frame.tsx`
 * draws the same tree.
 */

/** The shared frame's key: what a hook looks for beneath to merge into. */
export const FRAME_KEY = 'band:frame'
/** baton's section in the frame. */
export const SECTION_KEY = 'baton:section'
/** agents-panel's, which goes first. */
const AGENTS_SECTION_KEY = 'agents-panel:section'
/** What the frame takes from the width: one border and one space of padding a side. */
export const FRAME = 4
/** The section's title: the product's name, the same in every language. */
const TITLE = 'baton'

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
export function width(text: string): number {
  return Array.from(text).length
}

/** One row: line breaks and runs of spaces become one space. */
export function oneLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** At most `max` cells, ending in `…` when cut. */
export function cut(text: string, max: number): string {
  const chars = Array.from(text)
  if (chars.length <= max) return text
  if (max <= 0) return ''
  return `${chars.slice(0, max - 1).join('').trimEnd()}…`
}

/** The template with its `{fields}` filled; one with no value stays as written. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => (name in values ? String(values[name]) : whole))
}

/** The items left in the handoff's urgent sections (the blockers): what the band counts as open. */
export function pending(data: PanelData): number {
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
 * baton's section: a borderless column keyed `baton:section`, its title first
 * (bold, `claude`), then the status row. The line is a Button that opens the
 * panel; the action's own Button follows it; the hint sits at the right.
 */
export function section(t: ElementTable<'terminal'>, m: BandModel, act: BandActions): RenderElement {
  const { Box, Button, Text } = t
  const action = m.action
  return (
    <Box key={SECTION_KEY} flexDirection="column">
      <Text wrap="truncate-end" bold color="claude">{TITLE}</Text>
      <Box flexDirection="row" justifyContent="space-between" gap={GAP}>
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
    </Box>
  )
}

/**
 * True when nothing beneath drew the band: nothing, or the engine's own node
 * (`{ type: 'engine', ref }`), which is what `next(e)` resolves to when no plugin drew.
 * Anything else is another plugin's tree. The same definition as agents-panel's.
 */
export function isEmptyBand(tree: unknown): boolean {
  return tree === null || tree === undefined || (typeof tree === 'object' && (tree as { type?: unknown }).type === 'engine')
}

/** The frame's width less its border and padding: what a section's rows have. Never below 0. */
export function innerWidth(bodyColumns: number): number {
  return Number.isFinite(bodyColumns) ? Math.max(0, Math.floor(bodyColumns) - FRAME) : 0
}

type Node = { type?: unknown; props?: { key?: unknown }; children?: unknown }

function keyOf(node: unknown): string | undefined {
  if (typeof node !== 'object' || node === null) return undefined
  const key = (node as Node).props?.key
  return typeof key === 'string' ? key : undefined
}

function isBox(node: unknown): boolean {
  return typeof node === 'object' && node !== null && (node as Node).type === 'Box'
}

/** A section: a Box keyed `<name>:section`, with a name before the suffix. */
function isSection(node: unknown): node is RenderElement {
  const key = keyOf(node)
  return isBox(node) && key !== undefined && key.length > ':section'.length && key.endsWith(':section')
}

/**
 * The sections of a shared frame, in the order they sit; its dividers and
 * anything else dropped. Null when the tree is no frame (nothing, the engine's
 * node, a card, a column).
 */
export function sectionsOf(tree: unknown): RenderElement[] | null {
  if (!isBox(tree) || keyOf(tree) !== FRAME_KEY) return null
  const children = (tree as Node).children
  return Array.isArray(children) ? children.filter(isSection) : []
}

/** The fixed places: agents-panel's section first, baton's second, any other after them. */
const RANK: Readonly<Record<string, number>> = { [AGENTS_SECTION_KEY]: 0, [SECTION_KEY]: 1 }

/**
 * `theirs` without any baton section (a stale one is replaced, never doubled),
 * plus `mine`, in the fixed order; others keep the order they came in (the sort
 * is stable).
 */
export function merged(theirs: readonly RenderElement[], mine: RenderElement): RenderElement[] {
  const all = [...theirs.filter(s => keyOf(s) !== SECTION_KEY), mine]
  return all.sort((a, b) => (RANK[keyOf(a) ?? ''] ?? 2) - (RANK[keyOf(b) ?? ''] ?? 2))
}

/**
 * The shared frame: a dim round border with one space of padding a side, the
 * sections in a column, a dim `─` row of the inner width between two of them.
 * The divider's props and text are agents-panel's, so both build one tree.
 */
export function frame(t: ElementTable<'terminal'>, sections: readonly RenderElement[], inner: number): RenderElement {
  const { Box, Text } = t
  const rule = '─'.repeat(Math.max(1, inner))
  return (
    <Box key={FRAME_KEY} borderStyle="round" borderColor="claude" borderDimColor flexDirection="column" paddingX={1}>
      {sections.flatMap((s, i) => (i === 0 ? [s] : [<Text wrap="truncate-end" dimColor>{rule}</Text>, s]))}
    </Box>
  )
}

/**
 * baton's section with what was drawn beneath it: over nothing, a frame with
 * baton's section alone; over a shared frame, that frame rebuilt with baton's
 * section in its place; under any other tree (a clear-questions card), a column
 * with theirs above and baton's own frame below. The column takes no key.
 */
export function compose(t: ElementTable<'terminal'>, below: RenderElement, mine: RenderElement, inner: number): RenderElement {
  if (isEmptyBand(below)) return frame(t, [mine], inner)
  const theirs = sectionsOf(below)
  if (theirs !== null) return frame(t, merged(theirs, mine), inner)
  return { type: 'Box', props: { flexDirection: 'column' }, children: [below, frame(t, [mine], inner)] }
}
