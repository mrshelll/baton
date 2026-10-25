import type { EngineInterface, Register } from 'claude-code'
import type { PanelStrings } from '../../types'
import { bandLine, compose, innerWidth, pending, section, type BandActions } from './band'
import { current, currentView, currentViewed, openMore, refresh, showOwn, showProject, STARTUP_WAIT_MS } from './data'
import { pane, type PaneActions } from './pane'

/** The pane's id: the band's click, the auto-open and the render hook name it alike. */
const PANE = 'baton'

/**
 * Whether the mod draws this session: it draws on the terminal alone, so the
 * Python hooks may leave the telling to it only where a terminal shows the
 * session (`$.session.surfaces()`, the REPL's `terminal` first). Desktop,
 * vscode, mobile alone and `-p` (no surface) keep the hooks' own receipt.
 * A surface list that cannot be read counts as not drawn: the safe default.
 */
async function isDrawn($: EngineInterface): Promise<boolean> {
  try {
    return (await $.session.surfaces()).includes('terminal')
  } catch {
    return false
  }
}

/** How often the startup's wait looks at the surfaces again. */
const STARTUP_POLL_MS = 50

/**
 * Whether this process's `session.start` has come: from then on `surfaces()` is
 * the truth. A live flag, not `$.state`: every `get` of one dispatch reads one
 * moment, so a SessionStart polling the state would never see it change.
 */
const boot = { started: false }

/**
 * Whether a terminal may still come: under the REPL (`cli`, seen on 2.1.308)
 * or where the engine does not say. `-p` (`sdk-cli`), the SDK and any other
 * host (`claude-vscode`) draw no terminal: no wait, and no mark (the receipt).
 */
async function mayGetTerminal($: EngineInterface): Promise<boolean> {
  try {
    const entrypoint = await $.env.get('CLAUDE_CODE_ENTRYPOINT')
    return entrypoint === undefined || entrypoint === 'cli'
  } catch {
    return true
  }
}

/**
 * `isDrawn` for a SessionStart, which may open the process. There it comes
 * before `session.start` and before the terminal is among the surfaces (seen
 * on 2.1.308: the terminal follows in 100-250 ms; task-13-report.md), so with
 * no surface yet, no `session.start` and the REPL's entrypoint (or none), it
 * waits for one, at most STARTUP_WAIT_MS; a `session.start` or a surface that
 * is no terminal ends the wait at the next look. A `-p` run is never held:
 * there `session.start` comes only after SessionStart answers, and it draws
 * nowhere.
 */
async function isDrawnAtStart($: EngineInterface, signal?: AbortSignal): Promise<boolean> {
  try {
    const first = await $.session.surfaces()
    if (first.includes('terminal')) return true
    if (first.length > 0 || boot.started || !(await mayGetTerminal($))) return false
    for (let waited = 0; waited < STARTUP_WAIT_MS; waited += STARTUP_POLL_MS) {
      await $.clock.sleep(STARTUP_POLL_MS, { signal })
      const now = await $.session.surfaces()
      if (now.includes('terminal')) return true
      if (now.length > 0 || boot.started) return false
    }
    return false
  } catch {
    return false
  }
}

/** Whether this load has told the process (`tell`): once is enough. */
const told = { done: false }

/**
 * Tells baton's Python hooks, for the rest of the process, that the mod draws
 * it: `BATON_MOD=terminal` in the environment every hook started after
 * inherits. The mark on the payload (`marked`) says the same, but a plugin
 * seated above this one (a Team org's built-in, `cc-plugin-sec-default`, seen
 * on 2.1.309) may send a classic event on past the mod's hooks, and the
 * payload then reaches Python unmarked. Once per load; never throws.
 * `_mod_confirmed` in hooks/baton_hook.py reads it.
 */
async function tell($: EngineInterface): Promise<void> {
  if (told.done) return
  told.done = true
  try {
    await $.env.set('BATON_MOD', 'terminal')
  } catch {
    // The mark on each payload still says it.
  }
}

/**
 * The event as baton's Python hooks should receive it on stdin: marked
 * `baton_mod: true` where the mod draws (spike S3: the field reaches them),
 * unchanged elsewhere. `_mod_active` in hooks/baton_hook.py reads the mark.
 */
async function marked<E extends object>($: EngineInterface, e: E, drawn: Promise<boolean> = isDrawn($)): Promise<E> {
  if (!(await drawn)) return e
  await tell($)
  return { ...e, baton_mod: true }
}

/**
 * What the band's Buttons run. Each press settles on its own (the Button's
 * `onPress` never throws): a failure is a toast in the project's language,
 * and the panel is loaded again either way.
 */
function bandActions($: EngineInterface, strings: PanelStrings): BandActions {
  const act = (what: () => Promise<unknown>) => (): void => {
    void (async () => {
      try {
        await what()
      } catch {
        try {
          $.ui.toast(strings.actionFailed)
        } catch {
          // Nowhere left to say it.
        }
      }
      await refresh($)
    })()
  }
  return {
    newSession: act(() => $.command.run({ command: 'clear' })),
    writeHandoff: act(() => $.command.run({ command: 'baton:baton' })),
    // A pane that waits for room (`isPlaced: false`) is open, not failed.
    openPanel: act(() => $.ui.open({ id: PANE, title: 'baton', focus: true })),
  }
}

/**
 * What the pane's Buttons run: the band's two actions as they are, and the
 * pane's own moves (a fold, «see more», another project, Volver), each
 * settling on its own and never throwing.
 */
function paneActions($: EngineInterface, strings: PanelStrings): PaneActions {
  const quiet = (what: () => Promise<unknown>): void => {
    void what().catch(() => undefined)
  }
  const { newSession, writeHandoff } = bandActions($, strings)
  return {
    newSession,
    writeHandoff,
    toggle: slug => quiet(() => openMore($, open => ({ ...open, [slug]: !open[slug] }))),
    more: slug => quiet(() => openMore($, open => ({ ...open, more: open.more.includes(slug) ? open.more : [...open.more, slug] }))),
    open: other => quiet(() => showProject($, other)),
    back: () => quiet(() => showOwn($, true)),
  }
}

/** The live context window's fill, as a whole percentage; null when the engine has none or will not say. */
async function contextPercent($: EngineInterface): Promise<number | null> {
  try {
    const percent = (await $.session.usage()).context.percent
    return typeof percent === 'number' ? percent : null
  } catch {
    return null
  }
}

/**
 * After a startup or a /clear: loads the new session's panel and opens the
 * pane, unasked and unfocused, only when that panel's handoff has blockers
 * left (the band's count). The engine places an unasked pane from 144 columns; below
 * that it waits for the click. On the session's own project. Never throws.
 */
async function openOnItsOwn($: EngineInterface, source: string): Promise<void> {
  // What this load brought, never `current($)`: a newer load (the band's own,
  // right after «Sesión nueva») may not have written yet, leaving there the
  // panel of the session before the /clear.
  const data = await refresh($)
  if (source !== 'startup' && source !== 'clear') return
  try {
    if (data === null || pending(data) === 0 || !(await isDrawn($))) return
    await showOwn($, false)
    await $.ui.open({ id: PANE, title: 'baton' })
  } catch {
    // The band already says what is left; the pane waits for the click.
  }
}

export const register: Register = on => {
  // The band, on the terminal alone. What was drawn beneath comes first: a
  // survey keeps the band to itself; otherwise baton's section goes in the
  // shared frame, alone, merged into the frame beneath, or in its own frame
  // under another tree (`compose`). It fits the frame's inner width. A band
  // that cannot draw leaves what is beneath (`next` already ran and is never
  // called again).
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.surface !== 'terminal') return next(e)
    void tell($)
    const below = await next(e)
    if (e.props.hasSurvey) return below
    try {
      const data = await current($)
      const inner = innerWidth(e.props.bodyColumns)
      if (data === null || !(e.props.maxRows >= 1) || !(inner >= 1)) return below
      const t = $.ui.resolve(e)
      return compose(t, below, section(t, bandLine(data, inner), bandActions($, data.strings)), inner)
    } catch {
      return below
    }
  })

  // The pane, on the terminal alone: the session's own project, or the other
  // one in view. Before the first load, or when it cannot draw, the engine's.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e, next) => {
    if (e.surface !== 'terminal') return next(e)
    try {
      const own = await current($)
      if (own === null) return next(e)
      const v = await currentView($)
      const other = v.project === null ? null : await currentViewed($)
      const t = $.ui.resolve(e)
      if (other !== null && other.rel === v.project) {
        return pane(t, other.data, v, paneActions($, other.data.strings), e.props.bodyColumns, null, other.name)
      }
      const mine = v.project === null ? v : { ...v, project: null }
      return pane(t, own, mine, paneActions($, own.strings), e.props.bodyColumns, await contextPercent($))
    } catch {
      return next(e)
    }
  })

  // From here `surfaces()` is the truth: a SessionStart waiting for the
  // terminal stops at its next look (`boot`).
  on('session.start', async ($, e, next) => {
    boot.started = true
    if (await isDrawn($)) await tell($)
    const started = await next(e)
    void refresh($)
    return started
  })

  // The main loop's turns only: a subagent's end changes nothing the panel shows.
  on('turn.complete', async ($, e, next) => {
    const ended = await next(e)
    if (e.agentId === undefined) void refresh($)
    return ended
  })

  // A precompute installs nothing, and a subagent's compaction is its own.
  // Here and below, each `.catch` lets the event through: a hook that throws
  // before `next` goes on as if absent (unmarked: the hooks' own receipt), one
  // that threw after it replays what `next` settled.
  on('session.compact', async ($, e, next) => {
    const compacted = await next(e)
    if (e.trigger !== 'precompute' && e.agentId === undefined) void refresh($)
    return compacted
  }).catch(($, e, next) => next(e))

  // SessionStart reloads too: after a /clear or a resume the session id
  // changed and no session.start follows. After a startup or a /clear, the
  // pane opens on its own when blockers are left; the event never waits on it.
  // It waits only for the terminal, when it opens the process (isDrawnAtStart).
  on('classic.SessionStart', async ($, e, next) => {
    const answered = await next(await marked($, e, isDrawnAtStart($, next.signal)))
    void openOnItsOwn($, e.source).catch(() => undefined)
    return answered
  }).catch(($, e, next) => next(e))
  on('classic.Stop', async ($, e, next) => next(await marked($, e))).catch(($, e, next) => next(e))
  on('classic.PreCompact', async ($, e, next) => next(await marked($, e))).catch(($, e, next) => next(e))
  on('classic.PostCompact', async ($, e, next) => next(await marked($, e))).catch(($, e, next) => next(e))
}
