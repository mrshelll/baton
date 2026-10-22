import { expect, test } from 'claude-code/testing'
import type { EngineInterface, ProcessRunInit, ProcessRunResult } from 'claude-code'
import { FALLBACK_STRINGS, loadPanel } from './data'
import { SAMPLE } from './testdata'

/** A plugin root with spaces, as `$.plugin.root` hands it over (spike S2). */
const ROOT = '/Users/someone/Agentes IA/baton plugin'

type Call = { argv: readonly string[]; init: ProcessRunInit | undefined }

/**
 * The part of the plugin's `$` that `loadPanel` reaches: its root, `$.process.run`
 * answered by `run`, and a `$.ui.log` that keeps what it was told.
 */
function fake(run: () => Promise<ProcessRunResult>) {
  const calls: Call[] = []
  const logs: { text: string; to: unknown }[] = []
  const $ = {
    plugin: { name: 'baton', root: ROOT },
    process: {
      run: (argv: readonly string[], init?: ProcessRunInit) => {
        calls.push({ argv, init })
        return run()
      },
    },
    ui: { log: (text: string, options?: { to?: unknown }) => void logs.push({ text, to: options?.to }) },
  } as unknown as EngineInterface
  return { $, calls, logs }
}

function exited(exitCode: number, stdout: string, stderr = ''): () => Promise<ProcessRunResult> {
  return async () => ({ exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false })
}

/** The state every failure comes back as: a valid PanelData, in English, saying so. */
function expectLoadFailed(data: Awaited<ReturnType<typeof loadPanel>>) {
  expect(data).toEqual({
    version: 1,
    language: 'en',
    state: 'error',
    project: null,
    handoff: null,
    threshold: null,
    others: [],
    strings: FALLBACK_STRINGS,
    error: FALLBACK_STRINGS.loadFailed,
  })
}

test('loadPanel runs baton.py panel for the session and the folder, by argv, with a 10 s limit', async () => {
  const { $, calls } = fake(exited(0, SAMPLE))
  await loadPanel($, 'session 1', '/Users/someone/Mis proyectos/proyecto uno')
  expect(calls).toEqual([{
    argv: [
      'python3', `${ROOT}/scripts/baton.py`, 'panel', '--json',
      '--session', 'session 1', '--cwd', '/Users/someone/Mis proyectos/proyecto uno',
    ],
    init: { timeoutMs: 10_000 },
  }])
})

test('loadPanel for another project adds --project with its rel, raw, as the last two argv', async () => {
  const { $, calls } = fake(exited(0, SAMPLE))
  await loadPanel($, 'session 1', '/Users/someone/Mis proyectos/proyecto uno', 'sub/el radar')
  expect(calls).toEqual([{
    argv: [
      'python3', `${ROOT}/scripts/baton.py`, 'panel', '--json',
      '--session', 'session 1', '--cwd', '/Users/someone/Mis proyectos/proyecto uno',
      '--project', 'sub/el radar',
    ],
    init: { timeoutMs: 10_000 },
  }])
})

test('loadPanel hands back the JSON of baton.py panel as it came', async () => {
  const { $, logs } = fake(exited(0, SAMPLE))
  const data = await loadPanel($, 's1', '/x')
  expect(data.state).toBe('normal')
  expect(data.project).toEqual({ name: 'proyecto uno', path: '/Users/someone/Mis proyectos/proyecto uno' })
  expect(data.handoff?.sections.map(s => s.slug)).toEqual(['blockers', 'next', 'state', 'decisions', 'traps'])
  expect(data.handoff?.sections[1]?.items).toEqual(['• finish src/pay.ts:40'])
  expect(data.others).toEqual([{ name: 'radar', rel: 'sub/radar', where: 'sub/radar', mode: 'continue', age: '48 d ago' }])
  expect(data.strings.band_normal).toBe('handoff {age} · {mode}')
  expect(data.error).toBe(null)
  expect(logs).toEqual([])
})

test('loadPanel fills in a string the JSON lacks from the English fallback, and keeps the rest', async () => {
  // baton.py's own last resort sends `strings: {}` when it cannot even load them.
  const parsed = JSON.parse(SAMPLE) as Record<string, unknown>
  const { $ } = fake(exited(0, JSON.stringify({ ...parsed, strings: { band_normal: 'mine {age}' } })))
  const data = await loadPanel($, 's1', '/x')
  expect(data.state).toBe('normal')
  expect(data.strings.band_normal).toBe('mine {age}')
  expect(data.strings.status_error).toBe(FALLBACK_STRINGS.status_error)
  expect(data.strings.loadFailed).toBe(FALLBACK_STRINGS.loadFailed)
})

test('loadPanel: an exit code other than 0 is the load-failed state', async () => {
  const { $, logs } = fake(exited(1, SAMPLE, 'Traceback: boom'))
  expectLoadFailed(await loadPanel($, 's1', '/x'))
  // Why goes to the debug log alone: a transcript row every turn would be noise (spike S1).
  expect(logs.length).toBe(1)
  expect(logs[0]?.to).toBe('debug')
  expect(logs[0]?.text).toContain('exit 1')
})

test('loadPanel: a stdout that is not JSON is the load-failed state', async () => {
  for (const stdout of ['', 'not json', '{"version": 1', 'null', '[]', '"text"', '42']) {
    const { $ } = fake(exited(0, stdout))
    expectLoadFailed(await loadPanel($, 's1', '/x'))
  }
})

test('loadPanel: a version other than 1 or an unknown state is the load-failed state', async () => {
  const parsed = JSON.parse(SAMPLE) as Record<string, unknown>
  for (const wrong of [{ version: 2 }, { version: '1' }, { version: undefined }, { state: 'later' }, { state: null }]) {
    const { $ } = fake(exited(0, JSON.stringify({ ...parsed, ...wrong })))
    expectLoadFailed(await loadPanel($, 's1', '/x'))
  }
})

test('loadPanel: a JSON of the right version but the wrong shape is the load-failed state, not a crash later', async () => {
  const parsed = JSON.parse(SAMPLE) as Record<string, unknown>
  const shapes: Record<string, unknown>[] = [
    { version: 1, state: 'none' },
    { ...parsed, others: null },
    { ...parsed, others: undefined },
    { ...parsed, others: [1] },
    { ...parsed, others: [null] },
    { ...parsed, others: 'radar' },
    { ...parsed, project: 'proyecto uno' },
    { ...parsed, project: undefined },
    { ...parsed, handoff: [] },
    { ...parsed, handoff: 3 },
    { ...parsed, threshold: 'high' },
    { ...parsed, error: 5 },
    { ...parsed, error: undefined },
    { ...parsed, strings: null },
    { ...parsed, strings: [] },
    { ...parsed, strings: undefined },
  ]
  for (const shape of shapes) {
    const { $, logs } = fake(exited(0, JSON.stringify(shape)))
    expectLoadFailed(await loadPanel($, 's1', '/x'))
    expect(logs[0]?.to).toBe('debug')
  }
})

test('loadPanel keeps a string only where the JSON has a string: the fallback survives the rest', async () => {
  const parsed = JSON.parse(SAMPLE) as Record<string, unknown>
  const strings = { ...(parsed.strings as object), title: null, back: 3, see_more: ['x'], band_none: 'mine' }
  const { $ } = fake(exited(0, JSON.stringify({ ...parsed, strings })))
  const data = await loadPanel($, 's1', '/x')
  expect(data.state).toBe('normal')
  expect(data.strings.title).toBe(FALLBACK_STRINGS.title)
  expect(data.strings.back).toBe(FALLBACK_STRINGS.back)
  expect(data.strings.see_more).toBe(FALLBACK_STRINGS.see_more)
  expect(data.strings.band_none).toBe('mine')
})

test('loadPanel: a rejected run (the 10 s limit, python3 missing) is the load-failed state', async () => {
  const { $, logs } = fake(async () => { throw new Error('timed out after 10000 ms') })
  expectLoadFailed(await loadPanel($, 's1', '/x'))
  expect(logs[0]?.text).toContain('timed out')
})

test('loadPanel never throws, even when the call itself throws at once or the log fails', async () => {
  const $ = {
    plugin: { name: 'baton', root: ROOT },
    process: { run: () => { throw new Error('no process noun here') } },
    ui: { log: () => { throw new Error('no log either') } },
  } as unknown as EngineInterface
  expectLoadFailed(await loadPanel($, 's1', '/x'))
})

test('the fallback is a PanelData of its own: version 1, in English, and says the load failed', () => {
  expect(FALLBACK_STRINGS.loadFailed.length > 0).toBe(true)
  expect(FALLBACK_STRINGS.band_error).toBe('⚠ could not read the handoff')
})
