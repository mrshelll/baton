import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On, RenderSurface, SessionMessage } from 'claude-code'
import { STARTUP_WAIT_MS } from './data'
import { SAMPLE } from './testdata'

const SESSION = 'sesión 1'
const CWD = '/Users/someone/Mis proyectos/proyecto uno'

/** A promise and the function that settles it. */
function deferred<T>() {
  let settle!: (value: T) => void
  const promise = new Promise<T>(resolve => { settle = resolve })
  return { promise, settle }
}

/**
 * The engine beneath the mod: the session draws on `surfaces` (or refuses to
 * say which), `$.process.run` answers what `stdout` gives for its nth run
 * (`SAMPLE` by default), and what the mod writes to its state is kept, by key.
 * `loads(n)` settles once the mod has finished `n` loads (`loadedAt` is
 * written last), whether or not it awaited them.
 */
function world(
  on: On,
  surfaces: readonly RenderSurface[] | 'unreadable' | (() => readonly RenderSurface[]) = ['terminal'],
  stdout: (run: number) => Promise<string> = async () => SAMPLE,
) {
  const runs: { argv: readonly string[] }[] = []
  const state = new Map<string, unknown>()
  /** The `state` of every panel written, in order. */
  const panels: string[] = []
  let done = 0
  const waiting: { n: number; settle: (v: void) => void }[] = []
  const clock = mock.clock(on, { now: 5_000 })
  on('session.surfaces', () => (surfaces === 'unreadable' ? { deny: 'no surfaces here' } : { value: typeof surfaces === 'function' ? surfaces() : surfaces }))
  on('session.id', () => ({ value: SESSION }))
  on('session.cwd', () => ({ value: CWD }))
  on('process.run', async (_$, e) => {
    runs.push({ argv: e.argv })
    const out = await stdout(runs.length)
    return { value: { exitCode: 0, stdout: out, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('state.set', async (_$, e, next) => {
    const r = await next(e)
    if (e.plugin === 'baton') state.set(e.key, e.value)
    if (e.plugin === 'baton' && e.key === 'panel') panels.push((e.value as { state: string }).state)
    if (e.plugin === 'baton' && e.key === 'loadedAt') {
      done += 1
      for (const w of waiting.filter(w => w.n <= done)) w.settle()
    }
    return r
  })
  const loads = (n: number) => {
    const d = deferred<void>()
    if (done >= n) d.settle()
    else waiting.push({ n, settle: d.settle })
    return d.promise
  }
  return { runs, state, panels, loads, clock }
}

/** The classic events the mod marks, each raised as the engine raises it. */
const RAISE = {
  SessionStart: ($: Engine) => $.classic.SessionStart({ source: 'startup' }),
  Stop: ($: Engine) => $.classic.Stop({ stop_hook_active: false }),
  PreCompact: ($: Engine) => $.classic.PreCompact({ trigger: 'manual', custom_instructions: null }),
  PostCompact: ($: Engine) => $.classic.PostCompact({ trigger: 'manual', compact_summary: 'summary' }),
} as const

/** What the settings hooks beneath (baton's Python hooks) receive on stdin, by event. */
function stdinOf(on: On) {
  const seen: Record<string, Record<string, unknown>> = {}
  on('classic.SessionStart', (_$, e) => { seen.SessionStart = { ...e }; return {} })
  on('classic.Stop', (_$, e) => { seen.Stop = { ...e }; return {} })
  on('classic.PreCompact', (_$, e) => { seen.PreCompact = { ...e }; return {} })
  on('classic.PostCompact', (_$, e) => { seen.PostCompact = { ...e }; return {} })
  return seen
}

for (const surfaces of [['terminal'], ['terminal', 'mobile']] as const) {
  test(`drawn on ${surfaces.join(' + ')}, the four classic events reach Python marked baton_mod`, async ($, on) => {
    world(on, surfaces)
    const seen = stdinOf(on)
    for (const raise of Object.values(RAISE)) await raise($)
    for (const name of Object.keys(RAISE)) {
      expect(seen[name]?.baton_mod).toBe(true)
      expect(seen[name]?.hook_event_name).toBe(name)
    }
  })
}

for (const surfaces of [['desktop'], ['vscode'], ['mobile'], []] as const) {
  test(`drawn on ${surfaces.join(' + ') || 'nothing (-p)'}, the mark is left off: nothing would replace the receipt`, async ($, on) => {
    world(on, surfaces)
    // A -p run says so in the environment the engine sets for it (seen on 2.1.308).
    mock.env(on, { CLAUDE_CODE_ENTRYPOINT: 'sdk-cli' })
    const seen = stdinOf(on)
    for (const raise of Object.values(RAISE)) await raise($)
    for (const name of Object.keys(RAISE)) {
      expect(seen[name]?.hook_event_name).toBe(name)
      expect('baton_mod' in (seen[name] ?? {})).toBe(false)
    }
  })
}

// -- the startup: SessionStart comes before the terminal ----------------------
//
// Seen on Claude Code 2.1.308 in a real terminal (task-13-report.md): at
// startup `classic.SessionStart` comes first, with `surfaces()` still empty,
// and `session.start` (surface `terminal`) about 100-250 ms later, while the
// SessionStart hook still runs. Under `-p`, `session.start` (surface null)
// comes only once SessionStart has answered, and the engine sets
// CLAUDE_CODE_ENTRYPOINT=sdk-cli (`cli` under the REPL).

/** What a startup in a terminal looks like: no surface until session.start. */
function startingTerminal(on: On) {
  let up = false
  const w = world(on, () => (up ? ['terminal'] : []))
  const seen = stdinOf(on)
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  const start = async ($: Engine) => {
    up = true
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
  }
  return { w, seen, start }
}

/** Settles once `promise` has, or after the event loop settled without the clock moving; true when it had. */
async function settledBy<T>(promise: Promise<T>, clock: { settle: () => Promise<void> }): Promise<boolean> {
  let done = false
  void promise.then(() => { done = true })
  await clock.settle()
  return done
}

for (const source of ['startup', 'resume'] as const) {
  test(`a ${source} that opens the process: SessionStart before the terminal waits for it, and is marked`, async ($, on) => {
    mock.env(on, { CLAUDE_CODE_ENTRYPOINT: 'cli' })
    const { w, seen, start } = startingTerminal(on)
    const answered = $.classic.SessionStart({ source })
    expect(await settledBy(answered, w.clock)).toBe(false)
    await w.clock.advance(150)
    await start($)
    await w.clock.advance(100)
    await answered
    expect(seen.SessionStart?.baton_mod).toBe(true)
    expect(seen.SessionStart?.source).toBe(source)
  })
}

test('SessionStart after session.start, with the terminal already up: marked at once, no wait', async ($, on) => {
  const { w, seen, start } = startingTerminal(on)
  await start($)
  expect(await settledBy($.classic.SessionStart({ source: 'startup' }), w.clock)).toBe(true)
  expect(seen.SessionStart?.baton_mod).toBe(true)
})

test('a -p run: SessionStart is not held and gets no mark; session.start then says null', async ($, on) => {
  mock.env(on, { CLAUDE_CODE_ENTRYPOINT: 'sdk-cli' })
  const w = world(on, [])
  const seen = stdinOf(on)
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  expect(await settledBy($.classic.SessionStart({ source: 'startup' }), w.clock)).toBe(true)
  expect(seen.SessionStart?.hook_event_name).toBe('SessionStart')
  expect('baton_mod' in (seen.SessionStart ?? {})).toBe(false)
  await $.session.start({ cwd: CWD, surface: null, isInteractive: false })
})

test('the SDK (sdk-ts) is headless too: no wait, no mark', async ($, on) => {
  mock.env(on, { CLAUDE_CODE_ENTRYPOINT: 'sdk-ts' })
  const w = world(on, [])
  const seen = stdinOf(on)
  expect(await settledBy($.classic.SessionStart({ source: 'startup' }), w.clock)).toBe(true)
  expect('baton_mod' in (seen.SessionStart ?? {})).toBe(false)
})

test('a host that never says: the wait is bounded, then no mark (the receipt stays)', async ($, on) => {
  const w = world(on, [])
  const seen = stdinOf(on)
  const answered = $.classic.SessionStart({ source: 'startup' })
  await w.clock.advance(STARTUP_WAIT_MS - 100)
  expect(await settledBy(answered, w.clock)).toBe(false)
  await w.clock.advance(100)
  await answered
  expect('baton_mod' in (seen.SessionStart ?? {})).toBe(false)
  expect(STARTUP_WAIT_MS).toBeLessThanOrEqual(2_000)
})

test('once session.start has come and no terminal draws, a later SessionStart does not wait', async ($, on) => {
  const w = world(on, [])
  const seen = stdinOf(on)
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: CWD, surface: null, isInteractive: false })
  expect(await settledBy($.classic.SessionStart({ source: 'compact' }), w.clock)).toBe(true)
  expect('baton_mod' in (seen.SessionStart ?? {})).toBe(false)
})

test('a session whose surfaces cannot be read gets no mark, and the event still goes through', async ($, on) => {
  world(on, 'unreadable')
  const seen = stdinOf(on)
  await $.classic.Stop({ stop_hook_active: false })
  expect(seen.Stop?.hook_event_name).toBe('Stop')
  expect('baton_mod' in (seen.Stop ?? {})).toBe(false)
})

test('a classic event keeps what the hooks beneath answered', async ($, on) => {
  world(on)
  on('classic.SessionStart', () => ({ additionalContext: ['from Python'] }))
  expect(await $.classic.SessionStart({ source: 'clear' })).toEqual({ additionalContext: ['from Python'] })
})

test('session.start loads the panel for this session and folder into the state', async ($, on) => {
  const w = world(on)
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
  await w.loads(1)
  expect(w.runs[0]?.argv.slice(2)).toEqual(['panel', '--json', '--session', SESSION, '--cwd', CWD])
  expect((w.state.get('panel') as { state?: string }).state).toBe('normal')
  expect(w.state.get('loadedAt')).toBe(5_000)
})

test('the end of a main-loop turn reloads the panel', async ($, on) => {
  const w = world(on)
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  await $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  await w.loads(1)
  expect(w.runs.length).toBe(1)
})

test('the end of a subagent turn does not run baton.py', async ($, on) => {
  const w = world(on)
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  const turn = (turnId: string, agentId?: string) => $.turn.complete({
    answer: 'done', durationMs: 1, isAborted: false, turnId, reason: 'answer', ...(agentId !== undefined && { agentId }),
  })
  await turn('t1')
  await w.loads(1)
  // The subagent's end comes first: a run for it would be under way before the main one's.
  await turn('t2', 'a1')
  await turn('t3')
  await w.loads(2)
  expect(w.runs.length).toBe(2)
})

const MESSAGES: SessionMessage[] = [{ role: 'user', text: 'hello', toolUses: [] }, { role: 'assistant', text: 'hi', toolUses: [] }]

test('a compaction of the main conversation reloads the panel', async ($, on) => {
  const w = world(on)
  on('session.compact', (_$, e) => ({ messages: e.messages.slice(-1) }))
  await $.session.compact({ trigger: 'manual', messages: MESSAGES })
  await w.loads(1)
  expect(w.runs.length).toBe(1)
})

test('a precompute or a subagent compaction installs nothing in the main one: no reload', async ($, on) => {
  const w = world(on)
  on('session.compact', (_$, e) => ({ messages: e.messages.slice(-1) }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  await $.session.compact({ trigger: 'precompute', messages: MESSAGES })
  await $.session.compact({ trigger: 'auto', agentId: 'a1', messages: MESSAGES })
  // Two main-loop turns after them: a run for either compaction would be under
  // way before theirs, so it would be counted by the time both have loaded.
  // (Each awaited: a newer load supersedes one still under way, which then writes nothing.)
  await $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
  await w.loads(1)
  await $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer' })
  await w.loads(2)
  expect(w.runs.length).toBe(2)
})

test('a /clear reloads the panel: the session id changed and no session.start follows', async ($, on) => {
  const w = world(on)
  on('classic.SessionStart', () => ({}))
  await $.classic.SessionStart({ source: 'clear' })
  await w.loads(1)
  expect(w.runs.length).toBe(1)
})

test('a load that ends after a newer one has written leaves the newer one standing', async ($, on) => {
  const gate = deferred<void>()
  const firstAnswered = deferred<void>()
  const withState = (state: string) => JSON.stringify({ ...(JSON.parse(SAMPLE) as object), state })
  const w = world(on, ['terminal'], async run => {
    if (run !== 1) return withState(run === 2 ? 'ready' : 'none')
    await gate.promise
    firstAnswered.settle()
    return withState('normal')
  })
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  const turn = (turnId: string) => $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId, reason: 'answer' })
  await turn('t1')
  await turn('t2')
  await w.loads(1)
  expect((w.state.get('panel') as { state: string }).state).toBe('ready')
  gate.settle()
  await firstAnswered.promise
  // A later load: the stale one, ahead of it, would have written by the time it has.
  await turn('t3')
  await w.loads(2)
  expect(w.panels).toEqual(['ready', 'none'])
})
