import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On, RenderSurface } from 'claude-code'
import type { PanelData, PanelSection } from '../../types'
import { FALLBACK_STRINGS } from './data'
import { MAX_ITEMS } from './pane'
import { SAMPLE, SAMPLE_ES } from './testdata'

/** A fixture as the mod holds it once `loadPanel` took it (strings over the English fallback). */
function loaded(json: string): PanelData {
  const parsed = JSON.parse(json) as PanelData
  return { ...parsed, strings: { ...FALLBACK_STRINGS, ...parsed.strings } }
}

const ES = loaded(SAMPLE_ES)
const EN = loaded(SAMPLE)

/** The fixture moved to another face, the way baton.py would send it. */
const faces = {
  /** The spec's mockup: ready, written on compaction 3 min ago, 42 lines. */
  ready: (d: PanelData): PanelData => ({ ...d, state: 'ready', handoff: { ...d.handoff!, age: 'hace 3 min', lines: 42, written_by: 'compaction' } }),
  threshold: (d: PanelData): PanelData => ({ ...d, state: 'threshold', threshold: { percent: 70, tier: 65 } }),
  none: (d: PanelData): PanelData => ({ ...d, state: 'none', handoff: null }),
  noProject: (d: PanelData): PanelData => ({ ...d, state: 'none', project: null, handoff: null }),
  error: (d: PanelData): PanelData => ({
    ...d, state: 'error', handoff: null,
    error: 'No se pudo leer el traspaso en /Users/someone/Mis proyectos/proyecto uno/.baton/HANDOFF.md.',
  }),
  stale: (d: PanelData): PanelData => ({ ...d, handoff: { ...d.handoff!, stale: true } }),
  /** Normal, with nothing urgent left. */
  calm: (d: PanelData): PanelData => ({ ...d, handoff: { ...d.handoff!, sections: d.handoff!.sections.filter(s => !s.urgent) } }),
  /** A blockers section is there, but holds nothing. */
  hollow: (d: PanelData): PanelData => ({
    ...d, handoff: { ...d.handoff!, sections: d.handoff!.sections.map(s => (s.urgent ? { ...s, items: [] } : s)) },
  }),
  /** The section `slug` with `n` items. */
  long: (d: PanelData, slug: PanelSection['slug'], n: number): PanelData => ({
    ...d,
    handoff: {
      ...d.handoff!,
      sections: d.handoff!.sections.map(s => (s.slug === slug ? { ...s, items: Array.from({ length: n }, (_, i) => `• ${slug} ${i + 1}`) } : s)),
    },
  }),
}

/** What baton.py answers for `--project sub/radar`: the sub-project, in Spanish. */
const RADAR: PanelData = {
  ...ES,
  project: { name: 'radar', path: '/Users/someone/Mis proyectos/proyecto uno/sub/radar' },
  handoff: {
    ...ES.handoff!, mode: 'continue', age: 'hace 48 d',
    sections: [{ slug: 'next', label: 'Siguiente paso', items: ['• medir el radar'], urgent: false }],
  },
  others: [{ name: 'proyecto uno', rel: '.', where: '.', mode: 'memory', age: 'recién' }],
}

/** What `--project c/dolores` answers. */
const DOLORES: PanelData = { ...RADAR, project: { name: 'dolores', path: '/Users/someone/Mis proyectos/proyecto uno/c/dolores' } }

const PANE_PROPS = { title: 'baton', isFocused: true, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
const BAND_PROPS = { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 120, scroll: { offset: 0, bodyRows: 9 }, view: {} }

/** A promise and the function that settles it. */
function deferred<T>() {
  let settle!: (value: T) => void
  const promise = new Promise<T>(resolve => { settle = resolve })
  return { promise, settle }
}

type WorldOptions = {
  /** The context figure `$.session.usage()` answers; `null` leaves it out, `'deny'` refuses the call. */
  context?: number | null | 'deny'
  surfaces?: readonly RenderSurface[]
  /** `$.ui.open` is refused. */
  openDenied?: true
  /** A baton.py run waits on what this answers for its argv, if anything. */
  hold?: (argv: readonly string[]) => Promise<void> | null
  /** baton.py exits with this code, saying nothing. */
  exitCode?: number
  /** What `--project <rel>` answers. */
  other?: PanelData
  /** What baton.py answers for a session id other than `sesión 1` (`setSession`). */
  newSession?: PanelData
  /** While it holds a promise, the mod's write of this state key waits on it before it lands. */
  holdWrite?: { key: string; gate: Promise<void> | null; reached?: () => void }
}

/**
 * The engine beneath the mod. baton.py answers `data` for the session
 * `sesión 1`, `newSession` for any other (`setSession`, as after a /clear), or
 * `other` for a run with `--project`; every argv is kept. `$.ui.open` and the hooks' stdin are
 * recorded; `loads(n)` settles once the mod finished `n` loads of its own panel.
 */
function world(on: On, data: PanelData, opts: WorldOptions = {}) {
  const argvs: (readonly string[])[] = []
  const opens: { id: string; title?: string; focus?: boolean }[] = []
  const stdin: Record<string, unknown>[] = []
  const toasts: string[] = []
  const runs: string[] = []
  let done = 0
  const waiting: { n: number; settle: (v: void) => void }[] = []
  const opened = deferred<void>()
  mock.clock(on, { now: 5_000 })
  on('session.surfaces', () => ({ value: (opts.surfaces ?? ['terminal']) as RenderSurface[] }))
  let session = 'sesión 1'
  on('session.id', () => ({ value: session }))
  on('session.cwd', () => ({ value: '/Users/someone/Mis proyectos/proyecto uno' }))
  on('session.usage', () => {
    if (opts.context === 'deny') return { deny: 'no usage here' }
    const context = opts.context === null ? { window: 200_000 } : { window: 200_000, tokens: 16_000, percent: opts.context ?? 8 }
    return { value: { startedAt: 0, context, rateLimits: [] } }
  })
  on('process.run', async (_$, e) => {
    argvs.push(e.argv)
    const gate = opts.hold?.(e.argv)
    if (gate) await gate
    if (opts.exitCode !== undefined) {
      return { value: { exitCode: opts.exitCode, stdout: '', stderr: 'boom', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    const rel = e.argv.includes('--project') ? e.argv.at(-1) : undefined
    const own = e.argv.includes('sesión 1') ? data : (opts.newSession ?? data)
    const answer = rel === undefined ? own : rel === 'c/dolores' ? DOLORES : (opts.other ?? RADAR)
    return { value: { exitCode: 0, stdout: JSON.stringify(answer), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('state.set', async (_$, e, next) => {
    const held = opts.holdWrite
    if (held?.gate && e.plugin === 'baton' && e.key === held.key) {
      held.reached?.()
      await held.gate
    }
    const r = await next(e)
    if (e.plugin === 'baton' && e.key === 'loadedAt') {
      done += 1
      for (const w of waiting.filter(w => w.n <= done)) w.settle()
    }
    return r
  })
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('command.run', (_$, e) => { runs.push(e.command); return { text: '' } })
  on('ui.open', (_$, e) => {
    opens.push(e)
    opened.settle()
    if (opts.openDenied) return { deny: 'no panes here' }
    return { value: { isPlaced: true as const } }
  })
  on('ui.toast', (_$, e) => { toasts.push(e.text); return { value: undefined } })
  on('ui.render', { component: 'AbovePrompt' }, () => ({ type: 'engine', ref: 1 }) as never)
  on('ui.render', { component: 'Pane' }, () => ({ type: 'engine', ref: 2 }) as never)
  on('classic.SessionStart', (_$, e) => { stdin.push({ ...e }); return { additionalContext: ['from Python'] } })
  const loads = (n: number) => {
    const d = deferred<void>()
    if (done >= n) d.settle()
    else waiting.push({ n, settle: d.settle })
    return d.promise
  }
  /** The session id changes, as it does on a /clear. */
  const setSession = (id: string) => { session = id }
  return { argvs, opens, stdin, toasts, runs, loads, setSession, opened: opened.promise }
}

/** The panel loaded the way a session loads it: the end of a main-loop turn. */
async function load($: Engine, w: ReturnType<typeof world>) {
  await $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  await w.loads(1)
}

async function mount($: Engine, props: object = {}, surface: RenderSurface = 'terminal') {
  return $.ui.mount({ plugin: 'baton', surface, component: 'Pane', requestId: 'baton', props: { ...PANE_PROPS, ...props } as never })
}

/** The runtime's timer: the kit's types leave it out, the test runner has it. */
declare function setTimeout(run: () => void, ms: number): unknown

/** Lets every chain already started settle: the auto-open runs off the event. */
async function settle() {
  for (let i = 0; i < 5; i++) await new Promise<void>(resolve => setTimeout(() => resolve(), 5))
}

type Node = { type?: string; props?: Record<string, unknown>; children?: unknown[] }

/** Every Text's words and every Button's label, in the order drawn. */
function words(tree: unknown): string[] {
  const out: string[] = []
  const walk = (n: unknown): void => {
    if (n === null || n === undefined || typeof n !== 'object') return
    if (Array.isArray(n)) return n.forEach(walk)
    const node = n as Node
    if (node.type === 'Text') {
      out.push((node.children ?? []).filter(c => typeof c === 'string').join(''))
      return
    }
    if (node.type === 'Button' && typeof node.props?.label === 'string') {
      out.push(node.props.label)
      return
    }
    walk(node.children)
  }
  walk(tree)
  return out
}

/** Where each of `wanted` first appears among the words drawn; -1 if absent. */
function order(drawn: string[], wanted: string[]): number[] {
  return wanted.map(w => drawn.indexOf(w))
}

// -- the header ---------------------------------------------------------------

test('header (ready): project, status with icon and word, the spec\'s meta line, Sesión nueva first', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: 'baton · proyecto uno' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '✓ Traspaso listo' })).toMatchObject({ props: { color: 'success' } })
  expect(await ui.find({ type: 'Text', text: 'memoria · escrito hace 3 min, al compactar · 42 líneas · contexto 8 %' })).toBeDefined()
  expect(await ui.find({ key: 'baton:pane:new-session' })).toMatchObject({ type: 'Button', props: { label: 'Sesión nueva', variant: 'primary' } })
  expect(await ui.find({ key: 'baton:pane:write' })).toMatchObject({ type: 'Button', props: { label: 'Escribir traspaso', plain: true } })
  const drawn = words(await ui.drawn())
  expect(drawn.indexOf('Sesión nueva')).toBeLessThan(drawn.indexOf('Escribir traspaso'))
})

test('header: no context figure, or a usage call that fails, leaves that part out', async ($, on) => {
  const w = world(on, faces.ready(ES), { context: null })
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: 'memoria · escrito hace 3 min, al compactar · 42 líneas' })).toBeDefined()
  expect(await ui.find({ text: /contexto/ })).toBeUndefined()
})

test('header: a usage call that is refused leaves the context out and draws the rest', async ($, on) => {
  const w = world(on, faces.ready(ES), { context: 'deny' })
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: 'memoria · escrito hace 3 min, al compactar · 42 líneas' })).toBeDefined()
})

test('header (normal, by hand): Escribir traspaso is the main action, Sesión nueva the other', async ($, on) => {
  const w = world(on, ES, { context: 42 })
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: '✓ Traspaso guardado' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'memoria · escrito recién, a mano · 28 líneas · contexto 42 %' })).toBeDefined()
  expect(await ui.find({ key: 'baton:pane:write' })).toMatchObject({ props: { label: 'Escribir traspaso', variant: 'primary' } })
  expect(await ui.find({ key: 'baton:pane:new-session' })).toMatchObject({ props: { label: 'Sesión nueva', plain: true } })
  const drawn = words(await ui.drawn())
  expect(drawn.indexOf('Escribir traspaso')).toBeLessThan(drawn.indexOf('Sesión nueva'))
})

test('header (threshold): the warning with its percent; writing is the main action', async ($, on) => {
  const w = world(on, faces.threshold(ES))
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: '⚠ Contexto al 70 %' })).toMatchObject({ props: { color: 'warning' } })
  expect(await ui.find({ key: 'baton:pane:write' })).toMatchObject({ props: { variant: 'primary' } })
})

test('header: a threshold still reported under `normal` draws the normal header', async ($, on) => {
  // baton.py keeps the crossing in `threshold` once a newer handoff answers it.
  const w = world(on, { ...ES, state: 'normal', threshold: { percent: 70, tier: 65 } })
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: '✓ Traspaso guardado' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '⚠ Contexto al 70 %' })).toBeUndefined()
})

test('the pane\'s actions are the band\'s: /clear and /baton:baton, then a reload', async ($, on) => {
  const w = world(on, faces.ready(ES))
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:pane:new-session' })
  await w.loads(2)
  await ui.press({ key: 'baton:pane:write' })
  await w.loads(3)
  expect(w.runs).toEqual(['clear', 'baton:baton'])
})

// -- the body -----------------------------------------------------------------

test('body: Bloqueos with ⚠ and its count, then Siguiente paso, then Estado; decisions and traps folded', async ($, on) => {
  const w = world(on, ES)
  await load($, w)
  const ui = await mount($)
  const drawn = words(await ui.drawn())
  const [blockers, next, state, decisions, traps] = order(drawn, [
    '⚠ Bloqueos (2)', 'Siguiente paso', 'Estado', '▸ Decisiones y su porqué (1)', '▸ Trampas (1)',
  ])
  expect(blockers).toBeGreaterThan(-1)
  expect(next).toBeGreaterThan(blockers!)
  expect(state).toBeGreaterThan(next!)
  expect(decisions).toBeGreaterThan(state!)
  expect(traps).toBeGreaterThan(decisions!)
  expect(await ui.find({ type: 'Text', text: '⚠ Bloqueos (2)' })).toMatchObject({ props: { color: 'warning' } })
  expect(drawn).toContain('  1. ¿seguimos con A o con B?')
  expect(drawn).toContain('  2. falta la clave de staging')
  expect(drawn).toContain('  • terminar pay.ts:40')
  expect(drawn).toContain('  • Migración a medias.')
  // Folded: named and counted, their items not drawn.
  expect(drawn).not.toContain('  - usar X -- porque Y')
  expect(drawn).not.toContain('  - no tocar el seed')
})

test('a folded section opens on a press and folds again on the next; one level only', async ($, on) => {
  const w = world(on, ES)
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:fold:decisions' })
  let drawn = words(await ui.drawn())
  expect(drawn).toContain('  - usar X -- porque Y')
  expect(drawn).toContain('Decisiones y su porqué (1)')
  expect(drawn).not.toContain('  - no tocar el seed')
  await ui.press({ key: 'baton:fold:traps' })
  drawn = words(await ui.drawn())
  expect(drawn).toContain('  - no tocar el seed')
  await ui.press({ key: 'baton:fold:decisions' })
  drawn = words(await ui.drawn())
  expect(drawn).not.toContain('  - usar X -- porque Y')
  expect(drawn).toContain('▸ Decisiones y su porqué (1)')
})

test(`a section of more than ${6} items shows ${6} and «ver más»; the press shows the rest`, async ($, on) => {
  expect(MAX_ITEMS).toBe(6)
  const w = world(on, faces.long(ES, 'state', 9))
  await load($, w)
  const ui = await mount($)
  let drawn = words(await ui.drawn())
  expect(drawn.filter(t => t.startsWith('  • state '))).toHaveLength(6)
  expect(drawn).not.toContain('  • state 7')
  expect(await ui.find({ key: 'baton:more:state' })).toMatchObject({ type: 'Button', props: { label: 'ver más' } })
  // Exactly six: no «ver más».
  expect(await ui.find({ key: 'baton:more:next' })).toBeUndefined()
  await ui.press({ key: 'baton:more:state' })
  drawn = words(await ui.drawn())
  expect(drawn.filter(t => t.startsWith('  • state '))).toHaveLength(9)
  expect(await ui.find({ key: 'baton:more:state' })).toBeUndefined()
})

test('a long folded section, opened, still keeps to six until «ver más»: two levels at most', async ($, on) => {
  const w = world(on, faces.long(ES, 'traps', 8))
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ key: 'baton:fold:traps' })).toMatchObject({ props: { label: '▸ Trampas (8)' } })
  await ui.press({ key: 'baton:fold:traps' })
  expect(words(await ui.drawn()).filter(t => t.startsWith('  • traps '))).toHaveLength(6)
  await ui.press({ key: 'baton:more:traps' })
  expect(words(await ui.drawn()).filter(t => t.startsWith('  • traps '))).toHaveLength(8)
})

test('stale: «⚠ Traspaso viejo…» in the warning color, with its icon and its words', async ($, on) => {
  const w = world(on, faces.stale(ES))
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: /^⚠ Traspaso viejo: el código cambió desde que se escribió/ })).toMatchObject({ props: { color: 'warning' } })
})

test('not stale: no freshness warning', async ($, on) => {
  const w = world(on, ES)
  await load($, w)
  expect(await (await mount($)).find({ text: /Traspaso viejo/ })).toBeUndefined()
})

// -- empty and error ----------------------------------------------------------

test('none: «Aún no hay traspaso en este proyecto», a hint of when, and Escribir traspaso', async ($, on) => {
  const w = world(on, faces.none(ES))
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: 'Sin traspaso' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Aún no hay traspaso en este proyecto' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^Escribe uno antes de cerrar la sesión/ })).toBeDefined()
  expect(await ui.find({ key: 'baton:pane:write' })).toMatchObject({ props: { label: 'Escribir traspaso', variant: 'primary' } })
  expect(await ui.find({ text: /Bloqueos/ })).toBeUndefined()
})

test('none with no project: says baton knows no project, and still offers to write', async ($, on) => {
  const w = world(on, faces.noProject(ES))
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: 'Ningún proyecto cargado en esta sesión' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^baton no sabe de qué proyecto/ })).toBeDefined()
  expect(await ui.find({ key: 'baton:pane:write' })).toBeDefined()
  // The hint names the list: it is there.
  expect(await ui.find({ key: 'baton:project:0' })).toBeDefined()
})

test('error: what could not be read, and what to do about it', async ($, on) => {
  const w = world(on, faces.error(ES))
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: '⚠ No se pudo leer' })).toMatchObject({ props: { color: 'warning' } })
  expect(await ui.find({ type: 'Text', text: /^No se pudo leer el traspaso en .*HANDOFF\.md\.$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^Ábrelo con tu editor/ })).toBeDefined()
})

test('error when baton.py was not heard: says so, and no file to open is suggested', async ($, on) => {
  const w = world(on, ES, { exitCode: 1 })
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: FALLBACK_STRINGS.loadFailed })).toBeDefined()
  expect(await ui.find({ text: /Open it in your editor/ })).toBeUndefined()
})

// -- other projects -----------------------------------------------------------

test('others: links with their mode and age; never their rel', async ($, on) => {
  const w = world(on, ES)
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ type: 'Text', text: 'Otros proyectos' })).toBeDefined()
  expect(await ui.find({ key: 'baton:project:0' })).toMatchObject({ type: 'Button', props: { label: 'radar · continuar · hace 48 d' } })
})

test('two others of one name are told apart by where they are', async ($, on) => {
  const twins: PanelData = {
    ...ES,
    others: [
      { name: 'radar', rel: 'a/radar', where: 'a/radar', mode: 'memory', age: 'hace 1 d' },
      { name: 'radar', rel: 'b/radar', where: 'b/radar', mode: 'continue', age: 'hace 2 d' },
      { name: 'dolores', rel: 'c/dolores', where: 'c/dolores', mode: 'memory', age: 'hace 3 d' },
    ],
  }
  const w = world(on, twins)
  await load($, w)
  const ui = await mount($)
  expect(await ui.find({ key: 'baton:project:0' })).toMatchObject({ props: { label: 'radar (a/radar) · memoria · hace 1 d' } })
  expect(await ui.find({ key: 'baton:project:1' })).toMatchObject({ props: { label: 'radar (b/radar) · continuar · hace 2 d' } })
  expect(await ui.find({ key: 'baton:project:2' })).toMatchObject({ props: { label: 'dolores · memoria · hace 3 d' } })
})

test('opening another project: baton › name and Volver; its handoff, loaded with --project <rel>; no write or clear', async ($, on) => {
  const w = world(on, ES)
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:project:0' })
  await w.loads(1)
  await settle()
  expect(w.argvs.at(-1)?.slice(-2)).toEqual(['--project', 'sub/radar'])
  expect(await ui.find({ type: 'Text', text: 'baton › radar' })).toBeDefined()
  expect(await ui.find({ key: 'baton:back' })).toMatchObject({ type: 'Button', props: { label: 'Volver' } })
  expect(await ui.find({ text: /• medir el radar/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^continuar · escrito hace 48 d, a mano · 28 líneas$/ })).toBeDefined()
  expect(await ui.find({ key: 'baton:pane:write' })).toBeUndefined()
  expect(await ui.find({ key: 'baton:pane:new-session' })).toBeUndefined()
  expect(await ui.find({ text: /Bloqueos/ })).toBeUndefined()
  // One level: no further list of projects from there.
  expect(await ui.find({ key: 'baton:project:0' })).toBeUndefined()
  // The band keeps to the session's own project.
  const band = await $.ui.mount({ plugin: 'baton', surface: 'terminal', component: 'AbovePrompt', requestId: 'above-prompt', props: BAND_PROPS as never })
  expect(await band.find({ key: 'baton:open' })).toMatchObject({ text: 'baton · ⚠ 2 pendientes · recién' })
})

test('Volver reloads the session\'s own panel and draws it again', async ($, on) => {
  const w = world(on, ES)
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:project:0' })
  await settle()
  expect(await ui.find({ type: 'Text', text: 'baton › radar' })).toBeDefined()
  await ui.press({ key: 'baton:back' })
  await w.loads(2)
  expect(w.argvs.at(-1)).not.toContain('--project')
  expect(await ui.find({ type: 'Text', text: 'baton · proyecto uno' })).toBeDefined()
  expect(await ui.find({ key: 'baton:back' })).toBeUndefined()
  expect(await ui.find({ key: 'baton:pane:write' })).toBeDefined()
})

test('a project that ends loading after another was opened does not take the pane back', async ($, on) => {
  const slow = deferred<void>()
  const two: PanelData = {
    ...ES,
    others: [
      { name: 'radar', rel: 'sub/radar', where: 'sub/radar', mode: 'continue', age: 'hace 48 d' },
      { name: 'dolores', rel: 'c/dolores', where: 'c/dolores', mode: 'memory', age: 'hace 2 d' },
    ],
  }
  const w = world(on, two, { hold: argv => (argv.at(-1) === 'sub/radar' ? slow.promise : null) })
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:project:0' })
  await ui.press({ key: 'baton:project:1' })
  await settle()
  expect(await ui.find({ type: 'Text', text: 'baton › dolores' })).toBeDefined()
  slow.settle()
  await settle()
  expect(await ui.find({ type: 'Text', text: 'baton › dolores' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'baton › radar' })).toBeUndefined()
})

test('a project still loading when the pane opens on its own does not take it over', async ($, on) => {
  const slow = deferred<void>()
  const w = world(on, ES, { hold: argv => (argv.includes('--project') ? slow.promise : null) })
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:project:0' })
  await $.classic.SessionStart({ source: 'clear' })
  await w.opened
  slow.settle()
  await settle()
  expect(await ui.find({ type: 'Text', text: 'baton · proyecto uno' })).toBeDefined()
  expect(await ui.find({ key: 'baton:back' })).toBeUndefined()
})

test('a return to the own project that lands between the two writes of another one is not undone', async ($, on) => {
  const write = deferred<void>()
  const reached = deferred<void>()
  const holdWrite: NonNullable<WorldOptions['holdWrite']> = { key: 'viewed', gate: write.promise, reached: () => reached.settle() }
  const w = world(on, ES, { holdWrite })
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:project:0' })
  // The other project is loaded and its `viewed` write is on its way: the pane opens on its own now.
  await reached.promise
  holdWrite.gate = null
  await $.classic.SessionStart({ source: 'clear' })
  await w.opened
  await settle()
  write.settle()
  await settle()
  expect(await ui.find({ type: 'Text', text: 'baton · proyecto uno' })).toBeDefined()
  expect(await ui.find({ key: 'baton:back' })).toBeUndefined()
})

test('another project with no handoff says so, with no hint to write that Volver could not keep', async ($, on) => {
  const w = world(on, ES, { other: { ...RADAR, state: 'none', handoff: null } })
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:project:0' })
  await settle()
  expect(await ui.find({ type: 'Text', text: 'baton › radar' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Aún no hay traspaso en este proyecto' })).toBeDefined()
  expect(await ui.find({ text: /^Escribe uno/ })).toBeUndefined()
  expect(await ui.find({ key: 'baton:back' })).toBeDefined()
})

test('a folded section opened in one project is folded again in the next', async ($, on) => {
  const w = world(on, ES, { other: { ...RADAR, handoff: { ...RADAR.handoff!, sections: ES.handoff!.sections } } })
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:fold:decisions' })
  await ui.press({ key: 'baton:project:0' })
  await settle()
  expect(await ui.find({ key: 'baton:fold:decisions' })).toMatchObject({ props: { label: '▸ Decisiones y su porqué (1)' } })
})

// -- drawing rules ------------------------------------------------------------

for (const [name, face] of Object.entries({
  ready: faces.ready(ES), threshold: faces.threshold(ES), none: faces.none(ES), error: faces.error(ES), normal: ES, stale: faces.stale(ES), en: EN,
})) {
  test(`${name}: no Button has a hotkey; every row of the handoff and the header keeps to one line`, async ($, on) => {
    const w = world(on, face)
    await load($, w)
    const ui = await mount($)
    const buttons = await ui.findAll({ type: 'Button' })
    expect(buttons.length).toBeGreaterThan(0)
    for (const button of buttons) expect(button.props.hotkey).toBeUndefined()
    // Only the mod's own prose (a hint, an error, the stale warning) may wrap, inside the pane.
    for (const text of await ui.findAll({ type: 'Text' })) expect(['truncate-end', 'wrap']).toContain(text.props.wrap)
    for (const text of words(await ui.drawn())) expect(text).not.toMatch(/\p{Extended_Pictographic}(?<![✓⚠▸·])/u)
  })
}

test('a narrow pane cuts long rows with … and keeps the status whole', async ($, on) => {
  const long = { ...ES, handoff: { ...ES.handoff!, sections: [{ slug: 'next' as const, label: 'Siguiente paso', items: [`• ${'x'.repeat(80)}`], urgent: false }] } }
  const w = world(on, faces.ready(long))
  await load($, w)
  const ui = await mount($, { bodyColumns: 30 })
  for (const text of words(await ui.drawn())) expect(Array.from(text).length).toBeLessThanOrEqual(30)
  // Too narrow for both side by side: the actions go one under the other, neither cut.
  expect(await ui.find({ key: 'baton:pane:new-session' })).toMatchObject({ props: { label: 'Sesión nueva' } })
  expect(await ui.find({ key: 'baton:pane:write' })).toMatchObject({ props: { label: 'Escribir traspaso' } })
  expect(await ui.find({ type: 'Text', text: '✓ Traspaso listo' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^  • x+…$/ })).toMatchObject({ props: { wrap: 'truncate-end' } })
})

test('on desktop the pane is left to the engine', async ($, on) => {
  const w = world(on, ES)
  await load($, w)
  expect(await (await mount($, {}, 'desktop')).drawn()).toMatchObject({ type: 'engine' })
})

test('before the first load, the pane is left to the engine', async ($, on) => {
  world(on, ES)
  expect(await (await mount($)).drawn()).toMatchObject({ type: 'engine' })
})

// -- opening on its own -------------------------------------------------------

for (const source of ['startup', 'clear'] as const) {
  test(`after ${source}, with blockers left, the pane opens on its own (unfocused), once the new session loaded`, async ($, on) => {
    // The session before had nothing urgent: only the new session's data can open the pane.
    const w = world(on, faces.calm(ES), { newSession: ES })
    if (source === 'clear') await load($, w)
    w.setSession('sesión 2')
    expect(await $.classic.SessionStart({ source })).toEqual({ additionalContext: ['from Python'] })
    await w.opened
    expect(w.opens).toEqual([{ id: 'baton', title: 'baton' }])
    expect(w.argvs.at(-1)).toContain('sesión 2')
    expect(w.stdin[0]).toMatchObject({ source, baton_mod: true })
  })
}

// «Sesión nueva» runs /clear: the engine raises SessionStart(clear) inside it,
// and the band's own reload starts right after, taking the newest ticket. The
// auto-open's load ends first and writes nothing; it must still decide on the
// new session's data it loaded, never on what the state held before.

test('after /clear with a reload behind it: blockers before, none now, so the pane does not open', async ($, on) => {
  const behind = deferred<void>()
  let runs = 0
  const w = world(on, ES, { newSession: faces.calm(ES), hold: argv => (argv.includes('sesión 2') && ++runs === 2 ? behind.promise : null) })
  await load($, w)
  w.setSession('sesión 2')
  await $.classic.SessionStart({ source: 'clear' })
  void $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer' })
  await settle()
  expect(w.opens).toEqual([])
  behind.settle()
  await w.loads(2)
  await settle()
  expect(w.opens).toEqual([])
})

test('after /clear with a reload behind it: none before, blockers now, so the pane opens', async ($, on) => {
  const behind = deferred<void>()
  let runs = 0
  const w = world(on, faces.calm(ES), { newSession: ES, hold: argv => (argv.includes('sesión 2') && ++runs === 2 ? behind.promise : null) })
  await load($, w)
  w.setSession('sesión 2')
  await $.classic.SessionStart({ source: 'clear' })
  void $.turn.complete({ answer: 'x', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer' })
  await w.opened
  expect(w.opens).toEqual([{ id: 'baton', title: 'baton' }])
  behind.settle()
  await w.loads(2)
})

for (const [why, data] of Object.entries({ 'nothing urgent': faces.calm(ES), 'an empty blockers section': faces.hollow(ES), 'no handoff': faces.none(ES), 'an error': faces.error(ES) })) {
  test(`after startup with ${why}, the pane waits for the click`, async ($, on) => {
    const w = world(on, data)
    await $.classic.SessionStart({ source: 'startup' })
    await w.loads(1)
    await settle()
    expect(w.opens).toEqual([])
  })
}

for (const source of ['resume', 'compact', 'fork'] as const) {
  test(`after ${source}, never on its own, even with blockers`, async ($, on) => {
    const w = world(on, ES)
    await $.classic.SessionStart({ source })
    await w.loads(1)
    await settle()
    expect(w.opens).toEqual([])
  })
}

test('where no terminal draws the mod, the pane does not open on its own', async ($, on) => {
  const w = world(on, ES, { surfaces: ['desktop'] })
  await $.classic.SessionStart({ source: 'startup' })
  await w.loads(1)
  await settle()
  expect(w.opens).toEqual([])
})

test('the auto-open never holds the event: SessionStart answers while baton.py still runs', async ($, on) => {
  const gate = deferred<void>()
  const w = world(on, ES, { hold: () => gate.promise })
  expect(await $.classic.SessionStart({ source: 'startup' })).toEqual({ additionalContext: ['from Python'] })
  expect(w.opens).toEqual([])
  gate.settle()
  await w.opened
  expect(w.opens).toHaveLength(1)
})

test('a pane that cannot open on its own throws nothing and says nothing', async ($, on) => {
  const w = world(on, ES, { openDenied: true })
  expect(await $.classic.SessionStart({ source: 'clear' })).toEqual({ additionalContext: ['from Python'] })
  await w.opened
  await settle()
  expect(w.toasts).toEqual([])
})

test('opening on its own shows the session\'s own project, even if another was in view', async ($, on) => {
  const w = world(on, ES)
  await load($, w)
  const ui = await mount($)
  await ui.press({ key: 'baton:project:0' })
  await settle()
  expect(await ui.find({ type: 'Text', text: 'baton › radar' })).toBeDefined()
  await $.classic.SessionStart({ source: 'clear' })
  await w.opened
  await settle()
  expect(await ui.find({ type: 'Text', text: 'baton · proyecto uno' })).toBeDefined()
})
