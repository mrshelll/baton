import type { ElementTable, RenderElement } from 'claude-code'
import type { FoldedSlug, PanelData, PanelOther, PanelSection, PanelStrings, PaneView } from '../../types'
import { cut, fill, GAP, oneLine, width } from './band'

/**
 * The pane: the whole handoff, opened from the band (or on its own after a
 * startup or a /clear that left blockers). A header with the project, its
 * status in icon and word, how the handoff was written and the action of the
 * moment; then the body by importance: blockers, next step, state; decisions
 * and traps folded; the other projects as links. Every word comes from
 * `data.strings`; this file only picks, fills and fits them.
 */

/** The items a section shows before «see more». */
export const MAX_ITEMS = 6
/** What the terminal draws around a non-plain Button's label: `[ ` and ` ]`. */
const BUTTON_CHROME = 4
/** Items sit under their heading by this much. */
const INDENT = '  '

/** What the pane's Buttons run. Each one never throws. */
export type PaneActions = {
  newSession: () => void
  writeHandoff: () => void
  /** Folds or unfolds a secondary section. */
  toggle: (slug: FoldedSlug) => void
  /** Shows every item of a section. */
  more: (slug: string) => void
  /** Shows another project in the pane. */
  open: (other: PanelOther) => void
  /** Back to the session's own project. */
  back: () => void
}

/** What the header says the handoff stands at: the word with its icon, and its color. */
type Status = { text: string; tone: 'success' | 'warning' | undefined; ready: boolean }

/**
 * The status for the panel's state. A face missing what it names (ready with
 * no handoff, a threshold with no reading) draws what the rest supports, the
 * same rule as the band's.
 */
function status(data: PanelData): Status {
  const s = data.strings
  const handoff = data.handoff
  const percent = data.threshold?.percent ?? data.threshold?.tier
  if (data.state === 'ready' && handoff) return { text: s.status_ready, tone: 'success', ready: true }
  if (data.state === 'threshold' && typeof percent === 'number') {
    return { text: fill(s.status_threshold, { percent }), tone: 'warning', ready: false }
  }
  if (data.state === 'error') return { text: s.status_error, tone: 'warning', ready: false }
  if (handoff && data.state !== 'none') return { text: s.status_normal, tone: 'success', ready: false }
  return { text: s.status_none, tone: undefined, ready: false }
}

/** `memoria · escrito hace 3 min, al compactar · 42 líneas · contexto 8 %`: the parts there are. */
function meta(data: PanelData, context: number | null): string {
  const s = data.strings
  const handoff = data.handoff
  const parts: string[] = []
  if (handoff) {
    parts.push(handoff.mode === 'continue' ? s.mode_continue : s.mode_memory)
    parts.push(fill(s.written, { age: handoff.age, how: handoff.written_by === 'compaction' ? s.by_compaction : s.by_hand }))
    parts.push(fill(s.lines, { n: handoff.lines }))
  }
  if (context !== null) parts.push(fill(s.context, { percent: context }))
  return oneLine(parts.join(' · '))
}

/** One row of data, its indent kept, cut to the pane: never wrapped out of it. */
function Row(t: ElementTable<'terminal'>, text: string, columns: number, props: Record<string, unknown> = {}): RenderElement {
  const indent = /^ */.exec(text)?.[0] ?? ''
  return <t.Text wrap="truncate-end" {...props}>{cut(indent + oneLine(text), columns)}</t.Text>
}

/** The section's items: up to MAX_ITEMS, and «see more» for the rest unless pressed. */
function items(t: ElementTable<'terminal'>, section: PanelSection, v: PaneView, s: PanelStrings, act: PaneActions, columns: number): RenderElement[] {
  const all = v.open.more.includes(section.slug)
  const shown = all ? section.items : section.items.slice(0, MAX_ITEMS)
  const rows = shown.map(item => Row(t, `${INDENT}${item}`, columns))
  if (shown.length < section.items.length) {
    rows.push(
      <t.Box key={`baton:more-row:${section.slug}`} flexDirection="row">
        <t.Text>{INDENT}</t.Text>
        <t.Button key={`baton:more:${section.slug}`} label={s.see_more} plain dimColor onPress={() => act.more(section.slug)} />
      </t.Box>,
    )
  }
  return rows
}

function isFolded(slug: PanelSection['slug']): slug is FoldedSlug {
  return slug === 'decisions' || slug === 'traps'
}

/**
 * The body in the handoff's order: blockers (⚠ and the count), next step,
 * state, each open; decisions and traps folded and counted, those folded side
 * by side in one row when it fits. Two levels at most: a fold, then «see more».
 */
function body(t: ElementTable<'terminal'>, data: PanelData, v: PaneView, act: PaneActions, columns: number): RenderElement[] {
  const s = data.strings
  const out: RenderElement[] = []
  let folded: { slug: FoldedSlug; label: string }[] = []
  const flush = () => {
    if (folded.length === 0) return
    const row = folded
    folded = []
    const fits = row.reduce((n, f) => n + width(f.label), 0) + GAP * (row.length - 1) <= columns
    out.push(
      <t.Box key={`baton:folded:${row[0]!.slug}`} flexDirection={fits ? 'row' : 'column'} gap={fits ? GAP : 0}>
        {row.map(f => <t.Button key={`baton:fold:${f.slug}`} label={cut(f.label, columns)} plain onPress={() => act.toggle(f.slug)} />)}
      </t.Box>,
    )
  }
  for (const section of data.handoff?.sections ?? []) {
    const counted = fill(s.section_count, { label: oneLine(section.label), n: section.items.length })
    if (isFolded(section.slug)) {
      if (!v.open[section.slug]) {
        folded.push({ slug: section.slug, label: `▸ ${counted}` })
        continue
      }
      flush()
      const slug = section.slug
      out.push(
        <t.Box key={`baton:section:${slug}`} flexDirection="column">
          <t.Button key={`baton:fold:${slug}`} label={cut(counted, columns)} plain onPress={() => act.toggle(slug)} />
          {items(t, section, v, s, act, columns)}
        </t.Box>,
      )
      continue
    }
    flush()
    const heading = section.urgent
      ? Row(t, `⚠ ${counted}`, columns, { bold: true, color: 'warning' })
      : Row(t, section.label, columns, { bold: true })
    out.push(
      <t.Box key={`baton:section:${section.slug}`} flexDirection="column">
        {heading}
        {items(t, section, v, s, act, columns)}
      </t.Box>,
    )
  }
  flush()
  return out
}

/** The other projects as links, each with its mode and age; a shared name says where each one is. */
function others(t: ElementTable<'terminal'>, data: PanelData, act: PaneActions, columns: number): RenderElement | null {
  const s = data.strings
  if (data.others.length === 0) return null
  const count = new Map<string, number>()
  for (const o of data.others) count.set(o.name, (count.get(o.name) ?? 0) + 1)
  return (
    <t.Box key="baton:others" flexDirection="column">
      {Row(t, s.others, columns, { bold: true })}
      {data.others.map((o, i) => {
        const name = (count.get(o.name) ?? 0) > 1 ? `${o.name} (${o.where})` : o.name
        const label = oneLine(fill(s.other_line, { name, mode: o.mode === 'continue' ? s.mode_continue : s.mode_memory, age: o.age }))
        return <t.Button key={`baton:project:${i}`} label={cut(label, columns)} plain onPress={() => act.open(o)} />
      })}
    </t.Box>
  )
}

/**
 * The pane for `data`, fitted to `columns`. With `view.project` set it is
 * another project's (`otherName`): `baton › name` and Volver, no action on
 * the session (writing or clearing would be this session's, not that
 * project's), so no hint that leads to one either; no context figure and no
 * further list of projects. Pure.
 */
export function pane(
  t: ElementTable<'terminal'>,
  data: PanelData,
  view: PaneView,
  act: PaneActions,
  columns: number,
  context: number | null = null,
  otherName: string | null = null,
): RenderElement {
  const { Box, Button, Text } = t
  const s = data.strings
  const room = Math.max(1, Math.floor(columns))
  const isOther = view.project !== null
  const st = status(data)
  const statusText = cut(oneLine(st.text), room)
  const titleRoom = Math.max(1, room - width(statusText) - 1)
  const title = isOther
    ? fill(s.breadcrumb, { project: oneLine(otherName ?? data.project?.name ?? '') })
    : data.project
      ? fill(s.title, { project: oneLine(data.project.name) })
      : 'baton'
  const line = meta(data, isOther ? null : context)
  const primary = st.ready ? 'newSession' : 'writeHandoff'
  const labels = { newSession: oneLine(s.action_new_session), writeHandoff: oneLine(s.action_write) }
  const buttonRoom = Math.max(1, room - BUTTON_CHROME)
  const press = { newSession: act.newSession, writeHandoff: act.writeHandoff }
  const keys = { newSession: 'baton:pane:new-session', writeHandoff: 'baton:pane:write' }
  const secondary = primary === 'newSession' ? 'writeHandoff' : 'newSession'
  // The two actions side by side when both fit whole; else one under the other.
  const actionsFit = BUTTON_CHROME + width(labels[primary]) + GAP + width(labels[secondary]) <= room
  const handoff = data.handoff
  const sections = body(t, data, view, act, room)
  const links = isOther ? null : others(t, data, act, room)
  return (
    <Box key="baton:pane" flexDirection="column">
      <Box flexDirection="row" justifyContent="space-between" gap={1}>
        {Row(t, title, titleRoom, { bold: true })}
        <Text wrap="truncate-end" color={st.tone}>{statusText}</Text>
      </Box>
      {line !== '' && Row(t, line, room, { dimColor: true })}
      <Box flexDirection={actionsFit ? 'row' : 'column'} gap={actionsFit ? GAP : 0}>
        {isOther
          ? <Button key="baton:back" label={cut(oneLine(s.back), buttonRoom)} onPress={act.back} />
          : [
              <Button key={keys[primary]} label={cut(labels[primary], buttonRoom)} variant="primary" onPress={press[primary]} />,
              <Button key={keys[secondary]} label={cut(labels[secondary], room)} plain onPress={press[secondary]} />,
            ]}
      </Box>
      {handoff?.stale === true && <Box marginTop={1}><Text wrap="wrap" color="warning">{s.stale}</Text></Box>}
      {data.error !== null && (
        <Box key="baton:error" flexDirection="column" marginTop={1}>
          <Text wrap="wrap">{data.error}</Text>
          {data.project !== null && <Text wrap="wrap" dimColor>{s.error_hint}</Text>}
        </Box>
      )}
      {!handoff && data.error === null && (
        <Box key="baton:empty" flexDirection="column" marginTop={1}>
          {Row(t, data.project ? s.empty_title : s.no_project_title, room, { bold: true })}
          {!isOther && <Text wrap="wrap" dimColor>{data.project ? s.empty_hint : s.no_project_hint}</Text>}
        </Box>
      )}
      {sections.length > 0 && <Box key="baton:body" flexDirection="column" marginTop={1}>{sections}</Box>}
      {links && <Box marginTop={1}>{links}</Box>}
    </Box>
  )
}
