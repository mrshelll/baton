import { atom, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'
import type { PanelData, PanelState, PanelStrings } from '../../types'

/** The version of `baton.py panel --json` this mod reads. */
export const PANEL_VERSION = 1
/** How long baton.py may take before the load counts as failed. */
export const TIMEOUT_MS = 10_000

/** Where the mod keeps what it loaded: the band and the pane draw from here (`read($, panel)`). */
export const panel = atom({ plugin: 'baton', key: 'panel' } as const, null as PanelData | null)
export const loadedAt = atom({ plugin: 'baton', key: 'loadedAt' } as const, 0)

const STATES: readonly PanelState[] = ['ready', 'threshold', 'error', 'normal', 'none']

/**
 * The English texts of `templates/en.json`'s `panel` block, plus the mod's own
 * `loadFailed`. They stand in when baton.py cannot be heard at all, and fill
 * any key its JSON lacks (its own last resort sends `strings: {}`).
 */
export const FALLBACK_STRINGS: PanelStrings = {
  band_normal: 'baton · handoff {age} · {mode}',
  band_ready: 'baton · ✓ handoff ready · {age}',
  band_threshold: 'baton · ⚠ context at {percent} %',
  band_none: 'baton · no handoff in this project',
  band_error: 'baton · ⚠ could not read the handoff',
  band_pending: 'baton · ⚠ {n} open · {age}',
  band_no_project: 'baton · no project loaded',
  hint_open: 'click → panel',
  action_new_session: 'New session',
  action_write: 'Write handoff',
  title: 'baton · {project}',
  breadcrumb: 'baton › {project}',
  back: 'Back',
  status_ready: '✓ Handoff ready',
  status_threshold: '⚠ Context at {percent} %',
  status_normal: '✓ Handoff saved',
  status_none: 'No handoff',
  status_error: '⚠ Could not read',
  stale: '⚠ Old handoff: the code moved since it was written. Check the state before trusting it.',
  mode_memory: 'memory',
  mode_continue: 'continue',
  written: 'written {age}, {how}',
  by_compaction: 'on compaction',
  by_hand: 'by hand',
  by_threshold: 'after a threshold',
  lines: '{n} lines',
  context: 'context {percent} %',
  section_count: '{label} ({n})',
  see_more: 'see more',
  others: 'Other projects',
  other_line: '{name} · {mode} · {age}',
  empty_title: 'No handoff in this project yet',
  empty_hint: 'Write one before closing the session or when the context nears its limit: the next session will start from it.',
  no_project_title: 'No project loaded in this session',
  no_project_hint: 'baton does not know which project this session is about. Open one from the list, or write the handoff and it will ask where it goes.',
  error_read: 'Could not read the handoff at {path}.',
  error_hint: 'Open it in your editor to see what it holds; baton leaves it alone until the next handoff.',
  error_unexpected: 'baton could not prepare the panel ({detail}).',
  loadFailed: 'baton could not load the panel: baton.py did not answer.',
}

/** The panel when baton.py could not be heard: a PanelData of its own, in English. */
function loadFailed(): PanelData {
  return {
    version: PANEL_VERSION,
    language: 'en',
    state: 'error',
    project: null,
    handoff: null,
    threshold: null,
    others: [],
    strings: { ...FALLBACK_STRINGS },
    error: FALLBACK_STRINGS.loadFailed,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isRecordOrNull(value: unknown): boolean {
  return value === null || isRecord(value)
}

/**
 * What in a version 1 panel the views would trip on, or null when nothing:
 * they map `others`, branch on `project`, `handoff` and `threshold`, draw
 * `error` and fill `strings`. Better the error state now than a crash while drawing.
 */
function shapeError(parsed: Record<string, unknown>): string | null {
  if (!Array.isArray(parsed.others) || !parsed.others.every(isRecord)) return 'others'
  for (const key of ['project', 'handoff', 'threshold'] as const) {
    if (!isRecordOrNull(parsed[key])) return key
  }
  if (parsed.error !== null && typeof parsed.error !== 'string') return 'error'
  if (!isRecord(parsed.strings)) return 'strings'
  return null
}

/** The entries of `strings` that are strings: any other value leaves the fallback's in place. */
function onlyStrings(strings: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(Object.entries(strings).filter((entry): entry is [string, string] => typeof entry[1] === 'string'))
}

/** Why the load failed, in the debug log alone: a transcript row every turn would be noise (spike S1). */
function why($: EngineInterface, text: string): void {
  try {
    $.ui.log(`panel not loaded: ${text}`, { to: 'debug' })
  } catch {
    // Nowhere to say it; the panel still draws the failure.
  }
}

/**
 * Runs `baton.py panel --json` for the session and the folder and hands back
 * its JSON. Anything else (an exit code other than 0, a stdout that is not
 * that JSON, a version other than 1, a top-level shape the views would trip
 * on, a run that rejects or overruns) is the `error` state of the English
 * fallback. Never throws.
 *
 * Only the top level is checked; what lies inside `handoff` and each of
 * `others` is baton.py's, shipped in the same plugin.
 */
export async function loadPanel($: EngineInterface, sessionId: string, cwd: string): Promise<PanelData> {
  try {
    const argv = [
      'python3', `${$.plugin.root}/scripts/baton.py`, 'panel', '--json', '--session', sessionId, '--cwd', cwd,
    ]
    const { exitCode, stdout, stderr } = await $.process.run(argv, { timeoutMs: TIMEOUT_MS })
    if (exitCode !== 0) {
      why($, `exit ${exitCode}: ${stderr.slice(0, 500)}`)
      return loadFailed()
    }
    let parsed: unknown
    try {
      parsed = JSON.parse(stdout)
    } catch {
      why($, `stdout is not JSON: ${stdout.slice(0, 200)}`)
      return loadFailed()
    }
    if (!isRecord(parsed) || parsed.version !== PANEL_VERSION || !STATES.includes(parsed.state as PanelState)) {
      why($, `not a version ${PANEL_VERSION} panel: ${stdout.slice(0, 200)}`)
      return loadFailed()
    }
    const wrong = shapeError(parsed)
    if (wrong !== null) {
      why($, `a version ${PANEL_VERSION} panel of the wrong shape (${wrong}): ${stdout.slice(0, 200)}`)
      return loadFailed()
    }
    return { ...parsed, strings: { ...FALLBACK_STRINGS, ...onlyStrings(parsed.strings as Record<string, unknown>) } } as PanelData
  } catch (error) {
    why($, error instanceof Error ? error.message : String(error))
    return loadFailed()
  }
}

/**
 * The number of the last load started. A load that ends after a newer one
 * started writes nothing, so an older answer never covers a newer one. A
 * reload of the module starts over at 0, which is harmless.
 */
let latest = 0

/**
 * Loads the panel for the session as it stands now (its id and folder) and
 * keeps it in the mod's state; the drawings that read it are drawn again.
 * Never throws: on any failure the state keeps what it had.
 */
export async function refresh($: EngineInterface): Promise<void> {
  const ticket = ++latest
  try {
    const [sessionId, cwd] = await Promise.all([$.session.id(), $.session.cwd()])
    const data = await loadPanel($, sessionId, cwd)
    if (ticket !== latest) return
    const at = await $.clock.now()
    if (ticket !== latest) return
    await update($, panel, () => data)
    await update($, loadedAt, () => at)
  } catch (error) {
    why($, `state not written: ${error instanceof Error ? error.message : String(error)}`)
  }
}
