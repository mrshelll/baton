import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On, RenderSurface } from 'claude-code'
import type { PanelData } from '../../types'
import { bandLine, innerWidth, isEmptyBand, sectionsOf } from './band'
import { FALLBACK_STRINGS } from './data'
import { SAMPLE, SAMPLE_ES } from './testdata'

/**
 * A fixture as the mod holds it once `loadPanel` took it: the real stdout of
 * `baton.py panel --json`, its strings laid over the English fallback.
 */
function loaded(json: string): PanelData {
  const parsed = JSON.parse(json) as PanelData
  return { ...parsed, strings: { ...FALLBACK_STRINGS, ...parsed.strings } }
}

const ES = loaded(SAMPLE_ES)
const EN = loaded(SAMPLE)

/** The fixture moved to another of the panel's faces, the way baton.py would send it. */
const faces = {
  ready: (d: PanelData): PanelData => ({ ...d, state: 'ready' }),
  threshold: (d: PanelData, percent: number | null = 70): PanelData => ({ ...d, state: 'threshold', threshold: { percent, tier: 65 } }),
  none: (d: PanelData): PanelData => ({ ...d, state: 'none', handoff: null }),
  noProject: (d: PanelData): PanelData => ({ ...d, state: 'none', project: null, handoff: null }),
  error: (d: PanelData): PanelData => ({ ...d, state: 'error', handoff: null, error: 'x' }),
  /** Normal, with nothing urgent left in the handoff. */
  calm: (d: PanelData): PanelData => ({ ...d, state: 'normal', handoff: { ...d.handoff!, sections: d.handoff!.sections.filter(s => !s.urgent) } }),
  aged: (d: PanelData, age: string): PanelData => ({ ...d, handoff: { ...d.handoff!, age } }),
}

const WIDE = 120

/** The band's buttons, as `bandLine` lists them: the moment's own first and `primary`. */
const NEW_ES = { kind: 'newSession', label: 'Sesión nueva' } as const
const WRITE_ES = { kind: 'writeHandoff', label: 'Escribir traspaso' } as const
const primary = <A extends object>(a: A) => ({ ...a, primary: true })
const plain = <A extends object>(a: A) => ({ ...a, primary: false })

// -- bandLine: what each face says, in each language -------------------------

test('bandLine es: each face its line, its buttons and the hint, from the real templates', () => {
  expect(bandLine(faces.ready(ES), WIDE)).toEqual({
    text: '✓ traspaso listo · recién', tone: 'success',
    actions: [primary(NEW_ES), plain(WRITE_ES)], hint: 'clic → panel',
  })
  expect(bandLine(faces.threshold(ES), WIDE)).toEqual({
    text: '⚠ contexto al 70 %', tone: 'warning',
    actions: [primary(WRITE_ES), plain(NEW_ES)], hint: 'clic → panel',
  })
  expect(bandLine(faces.none(ES), WIDE)).toEqual({
    text: 'sin traspaso en este proyecto', tone: undefined,
    actions: [primary(WRITE_ES)], hint: null,
  })
  expect(bandLine(faces.error(ES), WIDE)).toEqual({
    text: '⚠ no se pudo leer el traspaso', tone: 'warning', actions: [], hint: 'clic → panel',
  })
  // With a handoff and nothing of the moment, both buttons, neither primary.
  expect(bandLine(faces.calm(faces.aged(ES, 'hace 2 h')), WIDE)).toEqual({
    text: 'traspaso hace 2 h · memoria', tone: undefined,
    actions: [plain(WRITE_ES), plain(NEW_ES)], hint: 'clic → panel',
  })
  // The fixture as captured: two blockers left, so the band counts them.
  expect(bandLine(faces.aged(ES, 'hace 2 h'), WIDE)).toEqual({
    text: '⚠ 2 pendientes · hace 2 h', tone: 'warning',
    actions: [plain(WRITE_ES), plain(NEW_ES)], hint: 'clic → panel',
  })
})

test('bandLine: the state decides, not the threshold baton.py still reports', () => {
  // A handoff written after the warning comes back `normal` (or `ready`) with
  // the crossing still in `threshold`: the band stops asking.
  const crossed = { tier: 65, percent: 70 }
  expect(bandLine({ ...faces.calm(faces.aged(ES, 'hace 2 h')), threshold: crossed }, WIDE)).toEqual({
    text: 'traspaso hace 2 h · memoria', tone: undefined,
    actions: [plain(WRITE_ES), plain(NEW_ES)], hint: 'clic → panel',
  })
  expect(bandLine({ ...faces.ready(ES), threshold: crossed }, WIDE)).toMatchObject({
    text: '✓ traspaso listo · recién', actions: [primary(NEW_ES), plain(WRITE_ES)],
  })
})

test('bandLine en: the same faces in English', () => {
  const NEW_EN = { kind: 'newSession', label: 'New session' } as const
  const WRITE_EN = { kind: 'writeHandoff', label: 'Write handoff' } as const
  expect(bandLine(faces.ready(EN), WIDE)).toMatchObject({ text: '✓ handoff ready · just now', actions: [primary(NEW_EN), plain(WRITE_EN)], hint: 'click → panel' })
  expect(bandLine(faces.threshold(EN), WIDE)).toMatchObject({ text: '⚠ context at 70 %', actions: [primary(WRITE_EN), plain(NEW_EN)] })
  expect(bandLine(faces.none(EN), WIDE)).toMatchObject({ text: 'no handoff in this project', actions: [primary(WRITE_EN)], hint: null })
  expect(bandLine(faces.error(EN), WIDE)).toMatchObject({ text: '⚠ could not read the handoff', actions: [] })
  expect(bandLine(faces.calm(EN), WIDE)).toMatchObject({ text: 'handoff just now · memory', actions: [plain(WRITE_EN), plain(NEW_EN)], hint: 'click → panel' })
  // SAMPLE has one blocker: both buttons beside it.
  expect(bandLine(EN, WIDE)).toMatchObject({ text: '⚠ 1 open item · just now', tone: 'warning', actions: [plain(WRITE_EN), plain(NEW_EN)] })
})

/** The fixture with exactly `n` blockers left. */
function blockers(d: PanelData, n: number): PanelData {
  const sections = d.handoff!.sections.map(s => (s.urgent ? { ...s, items: Array.from({ length: n }, (_, i) => `${i + 1}. b${i}`) } : s))
  return { ...d, state: 'normal', handoff: { ...d.handoff!, sections } }
}

test('bandLine: one item left reads in the singular, two or more in the plural, in both languages', () => {
  expect(bandLine(blockers(ES, 1), WIDE)).toMatchObject({ text: '⚠ 1 pendiente · recién', tone: 'warning', hint: 'clic → panel' })
  expect(bandLine(blockers(ES, 2), WIDE).text).toBe('⚠ 2 pendientes · recién')
  expect(bandLine(blockers(ES, 3), WIDE).text).toBe('⚠ 3 pendientes · recién')
  expect(bandLine(blockers(EN, 1), WIDE)).toMatchObject({ text: '⚠ 1 open item · just now', tone: 'warning', hint: 'click → panel' })
  expect(bandLine(blockers(EN, 2), WIDE).text).toBe('⚠ 2 open items · just now')
})

test('bandLine: the mode in the project language, continue as well as memory', () => {
  const going = { ...faces.calm(ES), handoff: { ...faces.calm(ES).handoff!, mode: 'continue' as const } }
  expect(bandLine(going, WIDE).text).toBe('traspaso recién · continuar')
})

test('bandLine: no project loaded says so, and offers to write (baton then asks where)', () => {
  expect(bandLine(faces.noProject(ES), WIDE)).toEqual({
    text: 'ningún proyecto cargado', tone: undefined,
    actions: [primary(WRITE_ES)], hint: null,
  })
})

test('bandLine: a threshold whose reading has no percent names the threshold crossed', () => {
  expect(bandLine(faces.threshold(ES, null), WIDE).text).toBe('⚠ contexto al 65 %')
})

test('bandLine: a ready or normal face with no handoff draws as having none, never a hole', () => {
  const hollow = (state: 'ready' | 'normal') => ({ ...ES, state, handoff: null })
  expect(bandLine(hollow('ready'), WIDE).text).toBe('sin traspaso en este proyecto')
  expect(bandLine(hollow('normal'), WIDE).text).toBe('sin traspaso en este proyecto')
  expect(bandLine({ ...ES, state: 'threshold', threshold: null }, WIDE).text).toBe('⚠ 2 pendientes · recién')
})

test('bandLine: the fallback after a failed load is the English error face', () => {
  const failed: PanelData = {
    version: 1, language: 'en', state: 'error', project: null, handoff: null, threshold: null,
    others: [], strings: { ...FALLBACK_STRINGS }, error: FALLBACK_STRINGS.loadFailed,
  }
  expect(bandLine(failed, WIDE)).toEqual({ text: '⚠ could not read the handoff', tone: 'warning', actions: [], hint: 'click → panel' })
})

// -- bandLine: the width -----------------------------------------------------

test('bandLine at 36 columns (a 40-column band\'s inside): a button that does not fit whole is not drawn, nor the hint', () => {
  // 25 + 3 + `[ Sesión nueva ]` (16) = 44 > 36; 25 + 3 + 12 = 40 > 36.
  expect(bandLine(faces.ready(ES), 36)).toEqual({
    text: '✓ traspaso listo · recién', tone: 'success', actions: [], hint: null,
  })
  // At 40 the button still does not fit, and the hint then does (25 + 3 + 12).
  expect(bandLine(faces.ready(ES), 40)).toMatchObject({ actions: [], hint: 'clic → panel' })
  // 27 + 3 + 12 = 42 > 36: the line alone.
  expect(bandLine(faces.calm(faces.aged(ES, 'hace 2 h')), 36)).toMatchObject({ text: 'traspaso hace 2 h · memoria', hint: null })
})

test('bandLine: a line wider than the band is cut with …, and nothing goes beside it', () => {
  expect(bandLine(faces.ready(ES), 12)).toEqual({ text: '✓ traspaso…', tone: 'success', actions: [], hint: null })
  expect(bandLine(faces.ready(ES), 25).text).toBe('✓ traspaso listo · recién')
  expect(bandLine(faces.ready(ES), 24).text).toBe('✓ traspaso listo · reci…')
  expect(bandLine(faces.ready(ES), 1).text).toBe('…')
})

test('bandLine: each button at the exact width it needs, the moment\'s first, the hint only with room left', () => {
  const needs = 25 + 3 + 16
  expect(bandLine(faces.ready(ES), needs).actions).toEqual([primary(NEW_ES)])
  expect(bandLine(faces.ready(ES), needs).hint).toBeNull()
  expect(bandLine(faces.ready(ES), needs - 1).actions).toEqual([])
  // The second after the first: 44 + 3 + `[ Escribir traspaso ]` (21).
  const both = needs + 3 + 21
  expect(bandLine(faces.ready(ES), both).actions).toEqual([primary(NEW_ES), plain(WRITE_ES)])
  expect(bandLine(faces.ready(ES), both - 1).actions).toEqual([primary(NEW_ES)])
  // The hint goes after the buttons that fit: here after the first (44 + 3 + 12).
  expect(bandLine(faces.ready(ES), both - 1).hint).toBe('clic → panel')
  expect(bandLine(faces.ready(ES), both + 15).hint).toBe('clic → panel')
  expect(bandLine(faces.ready(ES), both + 14).hint).toBeNull()
  // No button: the hint right after the line.
  expect(bandLine(faces.error(ES), 29 + 3 + 12).hint).toBe('clic → panel')
  expect(bandLine(faces.error(ES), 29 + 3 + 11).hint).toBeNull()
})

test('bandLine: no face carries the old `baton · ` prefix, in either language: the title says it', () => {
  for (const d of [ES, EN]) {
    for (const f of [faces.ready(d), faces.threshold(d), faces.none(d), faces.noProject(d), faces.error(d), faces.calm(d), d]) {
      expect(bandLine(f, WIDE).text.startsWith('baton')).toBe(false)
    }
  }
})

test('bandLine: a line break in a field never opens a second row', () => {
  expect(bandLine(faces.calm(faces.aged(ES, 'hace\n2 h')), WIDE).text).toBe('traspaso hace 2 h · memoria')
})

// -- isEmptyBand and stack ---------------------------------------------------

test('isEmptyBand: nothing or the engine node is empty; a tree is not (as agents-panel has it)', () => {
  expect(isEmptyBand(null)).toBe(true)
  expect(isEmptyBand(undefined)).toBe(true)
  expect(isEmptyBand({ type: 'engine', ref: 1 })).toBe(true)
  expect(isEmptyBand({ type: 'Box', props: {}, children: [] })).toBe(false)
})

test('innerWidth: the frame takes 4 cells (a border and a space a side), never below 0', () => {
  expect(innerWidth(120)).toBe(116)
  expect(innerWidth(40)).toBe(36)
  expect(innerWidth(4)).toBe(0)
  expect(innerWidth(2)).toBe(0)
  expect(innerWidth(Number.NaN)).toBe(0)
})

test('sectionsOf: a band:frame gives its *:section children, dividers and the rest dropped; anything else is no frame', () => {
  const agents = { type: 'Box' as const, props: { key: 'agents-panel:section' }, children: [] }
  const rule = { type: 'Text' as const, props: { dimColor: true }, children: ['──'] }
  const loose = { type: 'Box' as const, props: { key: 'loose' }, children: [] }
  const named = { type: 'Text' as const, props: { key: 'x:section' }, children: [] }
  expect(sectionsOf({ type: 'Box', props: { key: 'band:frame' }, children: [agents, rule, loose, named] })).toEqual([agents])
  expect(sectionsOf({ type: 'Box', props: { key: 'band:frame' }, children: [] })).toEqual([])
  expect(sectionsOf({ type: 'Box', props: { key: 'other' }, children: [agents] })).toBeNull()
  expect(sectionsOf({ type: 'Box', props: { flexDirection: 'column' }, children: [agents] })).toBeNull()
  expect(sectionsOf({ type: 'engine', ref: 1 })).toBeNull()
  expect(sectionsOf(null)).toBeNull()
})

// -- the band, drawn through the engine --------------------------------------

const BAND_PROPS = { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: WIDE, scroll: { offset: 0, bodyRows: 9 }, view: {} }

/** A promise and the function that settles it. */
function deferred<T>() {
  let settle!: (value: T) => void
  const promise = new Promise<T>(resolve => { settle = resolve })
  return { promise, settle }
}

/**
 * The engine beneath the mod. baton.py answers `data` (as JSON, the way the
 * mod reads it); beneath the band another plugin draws `OTHER CARD` when
 * `other`, else nothing (the engine's node). `$.command.run` and `$.ui.open`
 * are recorded, refused when asked; toasts are kept. `loads(n)` settles once
 * the mod has loaded `n` times.
 */
/** What another mod drew beneath baton, in the shared frame's contract or not. */
type Below = 'card' | 'agents' | 'agents+stale' | 'baton-first' | 'agents+other' | 'agents+junk'

/** A tree's node, as `ui.drawn()` gives it. */
type Node = { type?: string; props?: Record<string, unknown>; children?: unknown[] }

const AGENTS_ROW = 'AGENTS ROW'

/**
 * The frame another mod following the contract draws (agents-panel 0.3.0 shape): a
 * `band:frame` holding `agents-panel:section`, here with whatever else `kind` adds.
 */
function contractFrame($: { ui: { resolve: (e: { surface: 'terminal'; component: 'AbovePrompt' }) => unknown } }, kind: Exclude<Below, 'card'>) {
  const { Box, Text } = $.ui.resolve({ surface: 'terminal', component: 'AbovePrompt' }) as {
    Box: (p: object) => unknown
    Text: (p: object) => unknown
  }
  const section = (key: string, title: string, row: string) =>
    Box({ key, flexDirection: 'column', children: [Text({ bold: true, color: 'claude', children: title }), Text({ children: row })] })
  const agents = section('agents-panel:section', 'agentes', AGENTS_ROW)
  const rule = Text({ wrap: 'truncate-end', dimColor: true, children: '─'.repeat(10) })
  const children = {
    agents: [agents],
    'agents+stale': [agents, rule, section('baton:section', 'baton', 'STALE BATON')],
    'baton-first': [section('baton:section', 'baton', 'STALE BATON'), rule, agents],
    'agents+other': [section('other:section', 'otro', 'OTHER ROW'), rule, agents],
    'agents+junk': [Text({ children: 'JUNK' }), agents, rule, rule],
  }[kind]
  return Box({ key: 'band:frame', borderStyle: 'round', borderColor: 'claude', borderDimColor: true, flexDirection: 'column', paddingX: 1, children })
}

/** The frame's children by key, dividers as `rule:<cells>`. */
function layout(tree: unknown): string[] {
  return ((tree as Node).children ?? []).map(child => {
    const n = child as Node
    const key = n.props?.key
    return typeof key === 'string' ? key : `rule:${Array.from((n.children ?? []).join('')).length}`
  })
}

/** Every text under `tree`, in order: what a person reads. */
function texts(tree: unknown): string[] {
  if (typeof tree === 'string') return [tree]
  const n = tree as Node
  return (n.children ?? []).flatMap(texts)
}

function world(on: On, data: PanelData, opts: { other?: true; below?: Exclude<Below, 'card'>; runFails?: true; openDenied?: true; unplaced?: true } = {}) {
  const runs: { command: string; args: string }[] = []
  const opens: object[] = []
  const toasts: string[] = []
  let done = 0
  const waiting: { n: number; settle: (v: void) => void }[] = []
  mock.clock(on, { now: 5_000 })
  on('session.surfaces', () => ({ value: ['terminal'] as RenderSurface[] }))
  on('session.id', () => ({ value: 'sesión 1' }))
  on('session.cwd', () => ({ value: '/Users/someone/Mis proyectos/proyecto uno' }))
  const sets: { name: string; value?: string }[] = []
  on('env.set', (_$, e) => { sets.push({ name: e.name, value: e.value }); return { value: {} } })
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify(data), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('state.set', async (_$, e, next) => {
    const r = await next(e)
    if (e.plugin === 'baton' && e.key === 'loadedAt') {
      done += 1
      for (const w of waiting.filter(w => w.n <= done)) w.settle()
    }
    return r
  })
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('command.run', (_$, e) => {
    runs.push({ command: e.command, args: e.args })
    if (opts.runFails) throw new Error('the session is gone')
    return { text: '' }
  })
  on('ui.open', (_$, e) => {
    opens.push(e)
    if (opts.openDenied) return { deny: 'no panes here' }
    return { value: opts.unplaced ? { isPlaced: false as const, reason: 'narrow' } : { isPlaced: true as const } }
  })
  on('ui.toast', (_$, e) => { toasts.push(e.text); return { value: undefined } })
  on('ui.render', { component: 'AbovePrompt' }, $ => {
    if (opts.below) return contractFrame($, opts.below) as never
    if (!opts.other) return { type: 'engine', ref: 1 } as never
    const { Text } = $.ui.resolve({ surface: 'terminal' as const, component: 'AbovePrompt' as const })
    return Text({ children: 'OTHER CARD' }) as never
  })
  const loads = (n: number) => {
    const d = deferred<void>()
    if (done >= n) d.settle()
    else waiting.push({ n, settle: d.settle })
    return d.promise
  }
  return { runs, opens, toasts, loads, sets }
}

/** The panel loaded the way a session loads it: the end of a main-loop turn. */
async function load($: Engine, w: ReturnType<typeof world>) {
  await $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  await w.loads(1)
}

async function mount($: Engine, props: object = {}, surface: RenderSurface = 'terminal') {
  return $.ui.mount({ plugin: 'baton', surface, component: 'AbovePrompt', requestId: 'above-prompt', props: { ...BAND_PROPS, ...props } as never })
}

const FRAME_PROPS = { borderStyle: 'round', borderColor: 'claude', borderDimColor: true, flexDirection: 'column', paddingX: 1 }

test('over an empty band: the shared frame, keyed band:frame, with baton\'s section alone', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const ui = await mount($)
  const drawn = await ui.drawn() as Node
  expect(drawn).toMatchObject({ type: 'Box', props: { key: 'band:frame', ...FRAME_PROPS } })
  expect(layout(drawn)).toEqual(['baton:section'])
  // The section: a column with no border, its title first, then the status row.
  const section = drawn.children?.[0] as Node
  expect(section).toMatchObject({ type: 'Box', props: { key: 'baton:section', flexDirection: 'column' } })
  expect(section.props?.borderStyle).toBeUndefined()
  expect(section.children?.[0]).toMatchObject({ type: 'Text', props: { bold: true, color: 'claude', wrap: 'truncate-end' }, children: ['baton'] })
  expect(texts(section.children?.[1])).toEqual(['✓ traspaso listo · recién', 'clic → panel'])
  expect(await ui.find({ key: 'baton:open' })).toMatchObject({ type: 'Button', text: '✓ traspaso listo · recién' })
  expect(await ui.find({ type: 'Text', text: '✓ traspaso listo · recién' })).toMatchObject({ props: { color: 'success', wrap: 'truncate-end' } })
  expect(await ui.find({ key: 'baton:new-session' })).toMatchObject({ type: 'Button', props: { label: 'Sesión nueva', variant: 'primary' } })
  expect(await ui.find({ key: 'baton:write' })).toMatchObject({ type: 'Button', props: { label: 'Escribir traspaso' } })
  expect((await ui.find({ key: 'baton:write' }))?.props.variant).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /^clic → panel$/ })).toMatchObject({ props: { dimColor: true } })
  expect(await ui.find({ key: 'baton:band' })).toBeUndefined()
})

test('under a card that is no frame (clear-questions): a column, the card above and baton\'s frame below', async ($, on) => {
  const w = world(on, faces.threshold(ES), { other: true })
  await load($, w)
  const ui = await mount($)
  const drawn = await ui.drawn() as Node
  expect(drawn.type).toBe('Box')
  expect(drawn.props?.flexDirection).toBe('column')
  expect(drawn.props?.key).toBeUndefined()
  expect(drawn.children).toHaveLength(2)
  expect(drawn.children?.[0]).toMatchObject({ type: 'Text', children: ['OTHER CARD'] })
  expect(drawn.children?.[1]).toMatchObject({ type: 'Box', props: { key: 'band:frame', ...FRAME_PROPS } })
  expect(layout(drawn.children?.[1])).toEqual(['baton:section'])
  expect(await ui.find({ key: 'baton:write' })).toMatchObject({ props: { label: 'Escribir traspaso' } })
})

test('over agents-panel\'s frame: one frame, agents first, a dim divider of the inner width, baton second', async ($, on) => {
  const w = world(on, faces.ready(ES), { below: 'agents' })
  await load($, w)
  const ui = await mount($)
  const drawn = await ui.drawn() as Node
  expect(drawn).toMatchObject({ type: 'Box', props: { key: 'band:frame', ...FRAME_PROPS } })
  expect(layout(drawn)).toEqual(['agents-panel:section', `rule:${WIDE - 4}`, 'baton:section'])
  // The divider as agents-panel draws it: no key, dim, one row.
  expect(drawn.children?.[1]).toMatchObject({ type: 'Text', props: { wrap: 'truncate-end', dimColor: true }, children: ['─'.repeat(WIDE - 4)] })
  expect((drawn.children?.[1] as Node).props?.key).toBeUndefined()
  // Theirs untouched.
  expect(texts(drawn.children?.[0])).toEqual(['agentes', AGENTS_ROW])
  expect(await ui.find({ key: 'baton:new-session' })).toBeDefined()
})

test('a frame that already holds a baton section: it is replaced, never doubled', async ($, on) => {
  const w = world(on, faces.ready(ES), { below: 'agents+stale' })
  await load($, w)
  const drawn = await (await mount($)).drawn()
  expect(layout(drawn)).toEqual(['agents-panel:section', `rule:${WIDE - 4}`, 'baton:section'])
  expect(texts(drawn)).not.toContain('STALE BATON')
})

test('the order is fixed whatever order the frame came in: agents first, baton second', async ($, on) => {
  const w = world(on, faces.ready(ES), { below: 'baton-first' })
  await load($, w)
  expect(layout(await (await mount($)).drawn())).toEqual(['agents-panel:section', `rule:${WIDE - 4}`, 'baton:section'])
})

test('another known section goes after agents and baton, in the order it came', async ($, on) => {
  const w = world(on, faces.ready(ES), { below: 'agents+other' })
  await load($, w)
  expect(layout(await (await mount($)).drawn())).toEqual([
    'agents-panel:section', `rule:${WIDE - 4}`, 'baton:section', `rule:${WIDE - 4}`, 'other:section',
  ])
})

test('what is in the frame and is no section (old dividers, loose rows) is dropped; the dividers are drawn anew', async ($, on) => {
  const w = world(on, faces.ready(ES), { below: 'agents+junk' })
  await load($, w)
  const drawn = await (await mount($)).drawn()
  expect(layout(drawn)).toEqual(['agents-panel:section', `rule:${WIDE - 4}`, 'baton:section'])
  expect(texts(drawn)).not.toContain('JUNK')
})

/**
 * agents-panel's hook as the contract has it, run ABOVE baton's: it takes baton's
 * tree from `next` and merges its own section in. Written here from the spec,
 * not from baton's code, so the two sides check each other.
 */
function agentsAbove(below: unknown, inner: number): unknown {
  const n = below as Node
  if (n?.type !== 'Box' || n.props?.key !== 'band:frame') return below
  const isSection = (c: unknown) => (c as Node)?.type === 'Box' && String((c as Node).props?.key ?? '').endsWith(':section')
  const rank = (c: unknown) => ({ 'agents-panel:section': 0, 'baton:section': 1 } as Record<string, number>)[String((c as Node).props?.key)] ?? 2
  const text = (props: object, children: string) => ({ type: 'Text', props, children: [children] })
  const mine = { type: 'Box', props: { key: 'agents-panel:section', flexDirection: 'column' }, children: [text({}, 'agentes'), text({}, AGENTS_ROW)] }
  const sections = [...(n.children ?? []).filter(isSection).filter(c => (c as Node).props?.key !== 'agents-panel:section'), mine].sort((a, b) => rank(a) - rank(b))
  const children = sections.flatMap((s, i) => (i === 0 ? [s] : [text({ wrap: 'truncate-end', dimColor: true }, '─'.repeat(Math.max(1, inner))), s]))
  return { type: 'Box', props: { key: 'band:frame', borderStyle: 'round', borderColor: 'claude', borderDimColor: true, flexDirection: 'column', paddingX: 1 }, children }
}

test('with agents-panel ABOVE baton the frame comes out the same: agents first, baton second', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const merged = agentsAbove(await (await mount($)).drawn(), WIDE - 4)
  expect(merged).toMatchObject({ props: { key: 'band:frame', ...FRAME_PROPS } })
  expect(layout(merged)).toEqual(['agents-panel:section', `rule:${WIDE - 4}`, 'baton:section'])
  expect(texts(merged)).toEqual(['agentes', AGENTS_ROW, '─'.repeat(WIDE - 4), 'baton', '✓ traspaso listo · recién', 'clic → panel'])
})

test('with agents-panel BELOW baton: the same rows in the same order', async ($, on) => {
  const w = world(on, faces.ready(ES), { below: 'agents' })
  await load($, w)
  const drawn = await (await mount($)).drawn()
  expect(texts(drawn)).toEqual(['agentes', AGENTS_ROW, '─'.repeat(WIDE - 4), 'baton', '✓ traspaso listo · recién', 'clic → panel'])
})

test('with a survey up over a frame, the band is exactly what is beneath', async ($, on) => {
  const w = world(on, faces.ready(ES), { below: 'agents' })
  await load($, w)
  const ui = await mount($, { hasSurvey: true })
  expect(layout(await ui.drawn())).toEqual(['agents-panel:section'])
  expect(await ui.find({ key: 'baton:section' })).toBeUndefined()
})

test('narrow (40 columns): the section fits the inner 36 cells, no button, no hint; the divider is 36 wide', async ($, on) => {
  const w = world(on, faces.ready(ES), { below: 'agents' })
  await load($, w)
  const ui = await mount($, { bodyColumns: 40 })
  const drawn = await ui.drawn()
  expect(layout(drawn)).toEqual(['agents-panel:section', 'rule:36', 'baton:section'])
  expect(await ui.find({ key: 'baton:open' })).toMatchObject({ text: '✓ traspaso listo · recién' })
  expect(await ui.find({ key: 'baton:new-session' })).toBeUndefined()
  expect(await ui.find({ text: /clic → panel/ })).toBeUndefined()
})

test('the button and hint go by the inner width, not the band\'s: 48 columns hold the button, 47 do not', async ($, on) => {
  // Inner 44 = 25 + 3 + 16, exactly the line and its button.
  const w = world(on, faces.ready(ES))
  await load($, w)
  const fits = await mount($, { bodyColumns: 48 })
  expect(await fits.find({ key: 'baton:new-session' })).toBeDefined()
  await fits.unmount()
  const short = await mount($, { bodyColumns: 47 })
  expect(await short.find({ key: 'baton:new-session' })).toBeUndefined()
  expect(await short.find({ key: 'baton:open' })).toBeDefined()
})

test('no inner width at all (4 columns or fewer): baton draws nothing, what is beneath stays', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  expect(await (await mount($, { bodyColumns: 4 })).drawn()).toMatchObject({ type: 'engine' })
})

test('with a survey up, the band is exactly what is beneath', async ($, on) => {
  const w = world(on, faces.ready(ES), { other: true })
  await load($, w)
  const ui = await mount($, { hasSurvey: true })
  // Untouched: even the stamp says it is the other plugin's.
  expect(await ui.drawn()).toEqual({ type: 'Text', children: ['OTHER CARD'], part: { plugin: 'test' } })
  expect(await ui.find({ key: 'baton:section' })).toBeUndefined()
})

test('with a survey up and nothing beneath, the engine\'s own node', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const ui = await mount($, { hasSurvey: true })
  expect(await ui.drawn()).toMatchObject({ type: 'engine' })
})

for (const [name, face] of Object.entries({
  ready: faces.ready(ES), threshold: faces.threshold(ES), none: faces.none(ES), error: faces.error(ES), normal: ES,
})) {
  test(`${name}: no Button in the band has a hotkey, and every Text keeps to one row`, async ($, on) => {
    const w = world(on, face)
    await load($, w)
    const ui = await mount($)
    const buttons = await ui.findAll({ type: 'Button' })
    expect(buttons.length).toBeGreaterThan(0)
    for (const button of buttons) expect(button.props.hotkey).toBeUndefined()
    for (const text of await ui.findAll({ type: 'Text' })) expect(text.props.wrap).toBe('truncate-end')
  })
}

test('on desktop the band is left to what is beneath, untouched', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const ui = await mount($, {}, 'desktop')
  expect(await ui.drawn()).toMatchObject({ type: 'engine' })
  expect(await ui.find({ key: 'baton:section' })).toBeUndefined()
})

test('before the first load, the band is what is beneath', async ($, on) => {
  world(on, faces.ready(ES))
  expect(await (await mount($)).drawn()).toMatchObject({ type: 'engine' })
})

test('a band mounted before the first load ends shows baton\'s line once the panel loads', async ($, on) => {
  const w = world(on, faces.ready(ES))
  const ui = await mount($)
  expect(await ui.drawn()).toMatchObject({ type: 'engine' })
  await load($, w)
  expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'band:frame' } })
  expect(await ui.find({ key: 'baton:open' })).toMatchObject({ text: '✓ traspaso listo · recién' })
})

test('with no row to draw in, or no column, the band is what is beneath', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const rowless = await mount($, { maxRows: 0 })
  expect(await rowless.drawn()).toMatchObject({ type: 'engine' })
  await rowless.unmount()
  expect(await (await mount($, { bodyColumns: 0 })).drawn()).toMatchObject({ type: 'engine' })
})

test('the band drawn on the terminal tells the process once (BATON_MOD=terminal); on desktop it does not', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  await (await mount($, {}, 'desktop')).unmount()
  expect(w.sets).toEqual([])
  await (await mount($)).unmount()
  await mount($, { bodyColumns: 80 })
  expect(w.sets).toEqual([{ name: 'BATON_MOD', value: 'terminal' }])
})

test('a narrow band (40 columns) keeps one row: no hint, no button that does not fit', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const ui = await mount($, { bodyColumns: 40 })
  expect(await ui.find({ key: 'baton:open' })).toBeDefined()
  expect(await ui.find({ key: 'baton:new-session' })).toBeUndefined()
  expect(await ui.find({ text: /clic → panel/ })).toBeUndefined()
})

// -- the actions -------------------------------------------------------------

test('the line opens baton\'s panel, focused, and the panel is loaded again', async ($, on) => {
  const w = world(on, ES)
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:open' })
  expect(w.opens).toEqual([expect.objectContaining({ id: 'baton', title: 'baton', focus: true })])
  await w.loads(2)
  expect(w.toasts).toEqual([])
})

test('[ Sesión nueva ] runs /clear, then the panel is loaded again', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:new-session' })
  await w.loads(2)
  expect(w.runs).toEqual([{ command: 'clear', args: '' }])
  expect(w.toasts).toEqual([])
})

test('[ Escribir traspaso ] runs /baton:baton, then the panel is loaded again', async ($, on) => {
  const w = world(on, faces.none(ES))
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:write' })
  await w.loads(2)
  expect(w.runs).toEqual([{ command: 'baton:baton', args: '' }])
})

test('with open items left, both buttons are in the band and each runs its command', async ($, on) => {
  // The band of a handoff with blockers (`⚠ 2 pendientes`): nothing of the
  // moment, so neither is primary, and neither needs the panel opened first.
  const w = world(on, ES)
  await load($, w)
  const ui = await mount($)
  expect((await ui.find({ key: 'baton:write' }))?.props.variant).toBeUndefined()
  expect((await ui.find({ key: 'baton:new-session' }))?.props.variant).toBeUndefined()
  await ui.press({ key: 'baton:write' })
  await w.loads(2)
  await ui.press({ key: 'baton:new-session' })
  await w.loads(3)
  expect(w.runs).toEqual([{ command: 'baton:baton', args: '' }, { command: 'clear', args: '' }])
  expect(w.opens).toEqual([])
})

test('an action that fails says so in a toast, in the project language, and throws nothing', async ($, on) => {
  const w = world(on, faces.ready(ES), { runFails: true })
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:new-session' })
  await w.loads(2)
  expect(w.toasts).toEqual(['baton no pudo hacerlo; inténtalo de nuevo.'])
})

test('a panel that cannot open says so in a toast', async ($, on) => {
  const denied = world(on, ES, { openDenied: true })
  await load($, denied)
  const ui = await mount($)
  await ui.press({ key: 'baton:open' })
  await denied.loads(2)
  expect(denied.toasts).toEqual(['baton no pudo hacerlo; inténtalo de nuevo.'])
})

test('a panel opened where it waits for room is no failure', async ($, on) => {
  const w = world(on, ES, { unplaced: true })
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:open' })
  await w.loads(2)
  expect(w.opens).toHaveLength(1)
  expect(w.toasts).toEqual([])
})
