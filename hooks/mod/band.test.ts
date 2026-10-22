import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On, RenderSurface } from 'claude-code'
import type { PanelData } from '../../types'
import { bandLine, isEmptyBand, stack } from './band'
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

// -- bandLine: what each face says, in each language -------------------------

test('bandLine es: each face its line, its action and the hint, from the real templates', () => {
  expect(bandLine(faces.ready(ES), WIDE)).toEqual({
    text: 'baton · ✓ traspaso listo · recién', tone: 'success',
    action: { kind: 'newSession', label: 'Sesión nueva' }, hint: 'clic → panel',
  })
  expect(bandLine(faces.threshold(ES), WIDE)).toEqual({
    text: 'baton · ⚠ contexto al 70 %', tone: 'warning',
    action: { kind: 'writeHandoff', label: 'Escribir traspaso' }, hint: 'clic → panel',
  })
  expect(bandLine(faces.none(ES), WIDE)).toEqual({
    text: 'baton · sin traspaso en este proyecto', tone: undefined,
    action: { kind: 'writeHandoff', label: 'Escribir traspaso' }, hint: null,
  })
  expect(bandLine(faces.error(ES), WIDE)).toEqual({
    text: 'baton · ⚠ no se pudo leer el traspaso', tone: 'warning', action: null, hint: 'clic → panel',
  })
  expect(bandLine(faces.calm(faces.aged(ES, 'hace 2 h')), WIDE)).toEqual({
    text: 'baton · traspaso hace 2 h · memoria', tone: undefined, action: null, hint: 'clic → panel',
  })
  // The fixture as captured: two blockers left, so the band counts them.
  expect(bandLine(faces.aged(ES, 'hace 2 h'), WIDE)).toEqual({
    text: 'baton · ⚠ 2 pendientes · hace 2 h', tone: 'warning', action: null, hint: 'clic → panel',
  })
})

test('bandLine: the state decides, not the threshold baton.py still reports', () => {
  // A handoff written after the warning comes back `normal` (or `ready`) with
  // the crossing still in `threshold`: the band stops asking.
  const crossed = { tier: 65, percent: 70 }
  expect(bandLine({ ...faces.calm(faces.aged(ES, 'hace 2 h')), threshold: crossed }, WIDE)).toEqual({
    text: 'baton · traspaso hace 2 h · memoria', tone: undefined, action: null, hint: 'clic → panel',
  })
  expect(bandLine({ ...faces.ready(ES), threshold: crossed }, WIDE)).toMatchObject({
    text: 'baton · ✓ traspaso listo · recién', action: { kind: 'newSession' },
  })
})

test('bandLine en: the same faces in English', () => {
  expect(bandLine(faces.ready(EN), WIDE)).toMatchObject({ text: 'baton · ✓ handoff ready · just now', action: { kind: 'newSession', label: 'New session' }, hint: 'click → panel' })
  expect(bandLine(faces.threshold(EN), WIDE)).toMatchObject({ text: 'baton · ⚠ context at 70 %', action: { kind: 'writeHandoff', label: 'Write handoff' } })
  expect(bandLine(faces.none(EN), WIDE)).toMatchObject({ text: 'baton · no handoff in this project', action: { label: 'Write handoff' }, hint: null })
  expect(bandLine(faces.error(EN), WIDE)).toMatchObject({ text: 'baton · ⚠ could not read the handoff', action: null })
  expect(bandLine(faces.calm(EN), WIDE)).toMatchObject({ text: 'baton · handoff just now · memory', action: null, hint: 'click → panel' })
  // SAMPLE has one blocker.
  expect(bandLine(EN, WIDE)).toMatchObject({ text: 'baton · ⚠ 1 open item · just now', tone: 'warning' })
})

/** The fixture with exactly `n` blockers left. */
function blockers(d: PanelData, n: number): PanelData {
  const sections = d.handoff!.sections.map(s => (s.urgent ? { ...s, items: Array.from({ length: n }, (_, i) => `${i + 1}. b${i}`) } : s))
  return { ...d, state: 'normal', handoff: { ...d.handoff!, sections } }
}

test('bandLine: one item left reads in the singular, two or more in the plural, in both languages', () => {
  expect(bandLine(blockers(ES, 1), WIDE)).toMatchObject({ text: 'baton · ⚠ 1 pendiente · recién', tone: 'warning', hint: 'clic → panel' })
  expect(bandLine(blockers(ES, 2), WIDE).text).toBe('baton · ⚠ 2 pendientes · recién')
  expect(bandLine(blockers(ES, 3), WIDE).text).toBe('baton · ⚠ 3 pendientes · recién')
  expect(bandLine(blockers(EN, 1), WIDE)).toMatchObject({ text: 'baton · ⚠ 1 open item · just now', tone: 'warning', hint: 'click → panel' })
  expect(bandLine(blockers(EN, 2), WIDE).text).toBe('baton · ⚠ 2 open items · just now')
})

test('bandLine: the mode in the project language, continue as well as memory', () => {
  const going = { ...faces.calm(ES), handoff: { ...faces.calm(ES).handoff!, mode: 'continue' as const } }
  expect(bandLine(going, WIDE).text).toBe('baton · traspaso recién · continuar')
})

test('bandLine: no project loaded says so, and offers to write (baton then asks where)', () => {
  expect(bandLine(faces.noProject(ES), WIDE)).toEqual({
    text: 'baton · ningún proyecto cargado', tone: undefined,
    action: { kind: 'writeHandoff', label: 'Escribir traspaso' }, hint: null,
  })
})

test('bandLine: a threshold whose reading has no percent names the threshold crossed', () => {
  expect(bandLine(faces.threshold(ES, null), WIDE).text).toBe('baton · ⚠ contexto al 65 %')
})

test('bandLine: a ready or normal face with no handoff draws as having none, never a hole', () => {
  const hollow = (state: 'ready' | 'normal') => ({ ...ES, state, handoff: null })
  expect(bandLine(hollow('ready'), WIDE).text).toBe('baton · sin traspaso en este proyecto')
  expect(bandLine(hollow('normal'), WIDE).text).toBe('baton · sin traspaso en este proyecto')
  expect(bandLine({ ...ES, state: 'threshold', threshold: null }, WIDE).text).toBe('baton · ⚠ 2 pendientes · recién')
})

test('bandLine: the fallback after a failed load is the English error face', () => {
  const failed: PanelData = {
    version: 1, language: 'en', state: 'error', project: null, handoff: null, threshold: null,
    others: [], strings: { ...FALLBACK_STRINGS }, error: FALLBACK_STRINGS.loadFailed,
  }
  expect(bandLine(failed, WIDE)).toEqual({ text: 'baton · ⚠ could not read the handoff', tone: 'warning', action: null, hint: 'click → panel' })
})

// -- bandLine: the width -----------------------------------------------------

test('bandLine at 40 columns: the hint goes and a button that does not fit whole is not drawn', () => {
  // 33 + 3 + `[ Sesión nueva ]` (16) = 52 > 40.
  expect(bandLine(faces.ready(ES), 40)).toEqual({
    text: 'baton · ✓ traspaso listo · recién', tone: 'success', action: null, hint: null,
  })
  // 35 + 3 + 12 = 50 > 40: the line alone.
  expect(bandLine(faces.calm(faces.aged(ES, 'hace 2 h')), 40)).toMatchObject({ text: 'baton · traspaso hace 2 h · memoria', hint: null })
})

test('bandLine: a line wider than the band is cut with …, and nothing goes beside it', () => {
  expect(bandLine(faces.ready(ES), 20)).toEqual({ text: 'baton · ✓ traspaso…', tone: 'success', action: null, hint: null })
  expect(bandLine(faces.ready(ES), 33).text).toBe('baton · ✓ traspaso listo · recién')
  expect(bandLine(faces.ready(ES), 32).text).toBe('baton · ✓ traspaso listo · reci…')
  expect(bandLine(faces.ready(ES), 1).text).toBe('…')
})

test('bandLine: the button at the exact width it needs, the hint only with room left', () => {
  const needs = 33 + 3 + 16
  expect(bandLine(faces.ready(ES), needs).action).toEqual({ kind: 'newSession', label: 'Sesión nueva' })
  expect(bandLine(faces.ready(ES), needs).hint).toBeNull()
  expect(bandLine(faces.ready(ES), needs - 1).action).toBeNull()
  // The hint after the button: 52 + 3 + `clic → panel` (12).
  expect(bandLine(faces.ready(ES), needs + 15).hint).toBe('clic → panel')
  expect(bandLine(faces.ready(ES), needs + 14).hint).toBeNull()
  // No button: the hint right after the line.
  expect(bandLine(faces.error(ES), 37 + 3 + 12).hint).toBe('clic → panel')
  expect(bandLine(faces.error(ES), 37 + 3 + 11).hint).toBeNull()
})

test('bandLine: a line break in a field never opens a second row', () => {
  expect(bandLine(faces.calm(faces.aged(ES, 'hace\n2 h')), WIDE).text).toBe('baton · traspaso hace 2 h · memoria')
})

// -- isEmptyBand and stack ---------------------------------------------------

test('isEmptyBand: nothing or the engine node is empty; a tree is not (as agents-panel has it)', () => {
  expect(isEmptyBand(null)).toBe(true)
  expect(isEmptyBand(undefined)).toBe(true)
  expect(isEmptyBand({ type: 'engine', ref: 1 })).toBe(true)
  expect(isEmptyBand({ type: 'Box', props: {}, children: [] })).toBe(false)
})

test('stack: alone over an empty band; under another tree in a column with no key of its own', () => {
  const mine = { type: 'Box' as const, props: { key: 'baton:band' }, children: [] }
  const other = { type: 'Text' as const, props: {}, children: ['OTHER CARD'] }
  expect(stack({ type: 'engine', ref: 1 } as never, mine)).toBe(mine)
  expect(stack(other, mine)).toEqual({ type: 'Box', props: { flexDirection: 'column' }, children: [other, mine] })
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
function world(on: On, data: PanelData, opts: { other?: true; runFails?: true; openDenied?: true; unplaced?: true } = {}) {
  const runs: { command: string; args: string }[] = []
  const opens: object[] = []
  const toasts: string[] = []
  let done = 0
  const waiting: { n: number; settle: (v: void) => void }[] = []
  mock.clock(on, { now: 5_000 })
  on('session.surfaces', () => ({ value: ['terminal'] as RenderSurface[] }))
  on('session.id', () => ({ value: 'sesión 1' }))
  on('session.cwd', () => ({ value: '/Users/someone/Mis proyectos/proyecto uno' }))
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
  return { runs, opens, toasts, loads }
}

/** The panel loaded the way a session loads it: the end of a main-loop turn. */
async function load($: Engine, w: ReturnType<typeof world>) {
  await $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  await w.loads(1)
}

async function mount($: Engine, props: object = {}, surface: RenderSurface = 'terminal') {
  return $.ui.mount({ plugin: 'baton', surface, component: 'AbovePrompt', requestId: 'above-prompt', props: { ...BAND_PROPS, ...props } as never })
}

test('over an empty band, the band is baton\'s line alone: its root the Box keyed baton:band', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const ui = await mount($)
  expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'baton:band' } })
  expect(await ui.find({ key: 'baton:open' })).toMatchObject({ type: 'Button', text: 'baton · ✓ traspaso listo · recién' })
  expect(await ui.find({ type: 'Text', text: 'baton · ✓ traspaso listo · recién' })).toMatchObject({ props: { color: 'success', wrap: 'truncate-end' } })
  expect(await ui.find({ key: 'baton:new-session' })).toMatchObject({ type: 'Button', props: { label: 'Sesión nueva' } })
  expect(await ui.find({ type: 'Text', text: /^clic → panel$/ })).toMatchObject({ props: { dimColor: true } })
})

test('under another plugin\'s tree: a column, theirs above and baton\'s line below', async ($, on) => {
  const w = world(on, faces.threshold(ES), { other: true })
  await load($, w)
  const ui = await mount($)
  const drawn = await ui.drawn() as { type: string; props?: Record<string, unknown>; children?: unknown[] }
  expect(drawn.type).toBe('Box')
  expect(drawn.props?.flexDirection).toBe('column')
  expect(drawn.props?.key).toBeUndefined()
  expect(drawn.children).toHaveLength(2)
  expect(drawn.children?.[0]).toMatchObject({ type: 'Text', children: ['OTHER CARD'] })
  expect(drawn.children?.[1]).toMatchObject({ type: 'Box', props: { key: 'baton:band' } })
  expect(await ui.find({ key: 'baton:write' })).toMatchObject({ props: { label: 'Escribir traspaso' } })
})

test('with a survey up, the band is exactly what is beneath', async ($, on) => {
  const w = world(on, faces.ready(ES), { other: true })
  await load($, w)
  const ui = await mount($, { hasSurvey: true })
  // Untouched: even the stamp says it is the other plugin's.
  expect(await ui.drawn()).toEqual({ type: 'Text', children: ['OTHER CARD'], part: { plugin: 'test' } })
  expect(await ui.find({ key: 'baton:band' })).toBeUndefined()
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
  expect(await ui.find({ key: 'baton:band' })).toBeUndefined()
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
  expect(await ui.drawn()).toMatchObject({ type: 'Box', props: { key: 'baton:band' } })
  expect(await ui.find({ key: 'baton:open' })).toMatchObject({ text: 'baton · ✓ traspaso listo · recién' })
})

test('with no row to draw in, or no column, the band is what is beneath', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const rowless = await mount($, { maxRows: 0 })
  expect(await rowless.drawn()).toMatchObject({ type: 'engine' })
  await rowless.unmount()
  expect(await (await mount($, { bodyColumns: 0 })).drawn()).toMatchObject({ type: 'engine' })
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
