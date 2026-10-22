import type { EngineInterface, Register } from 'claude-code'
import type { PanelStrings } from '../../types'
import { band, bandLine, pending, stack, type BandActions } from './band'
import { current, currentView, currentViewed, openMore, refresh, showOwn, showProject } from './data'
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

/**
 * The event as baton's Python hooks should receive it on stdin: marked
 * `baton_mod: true` where the mod draws (spike S3: the field reaches them),
 * unchanged elsewhere. `_mod_active` in hooks/baton_hook.py reads the mark.
 */
async function marked<E extends object>($: EngineInterface, e: E): Promise<E> {
  return (await isDrawn($)) ? { ...e, baton_mod: true } : e
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
 * pane, unasked and unfocused, only when its handoff has blockers left (the
 * band's count). The engine places an unasked pane from 144 columns; below
 * that it waits for the click. On the session's own project. Never throws.
 */
async function openOnItsOwn($: EngineInterface, source: string): Promise<void> {
  await refresh($)
  if (source !== 'startup' && source !== 'clear') return
  try {
    const data = await current($)
    if (data === null || pending(data) === 0 || !(await isDrawn($))) return
    await showOwn($, false)
    await $.ui.open({ id: PANE, title: 'baton' })
  } catch {
    // The band already says what is left; the pane waits for the click.
  }
}

export const register: Register = on => {
  // The band, on the terminal alone. What was drawn beneath comes first: a
  // survey keeps the band to itself; otherwise baton's line goes alone or
  // under the others'. A band that cannot draw leaves what is beneath (`next`
  // already ran and is never called again).
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.surface !== 'terminal') return next(e)
    const below = await next(e)
    if (e.props.hasSurvey) return below
    try {
      const data = await current($)
      if (data === null || !(e.props.maxRows >= 1) || !(e.props.bodyColumns >= 1)) return below
      const mine = band($.ui.resolve(e), bandLine(data, e.props.bodyColumns), bandActions($, data.strings))
      return stack(below, mine)
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

  on('session.start', async ($, e, next) => {
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
  on('classic.SessionStart', async ($, e, next) => {
    const answered = await next(await marked($, e))
    void openOnItsOwn($, e.source).catch(() => undefined)
    return answered
  }).catch(($, e, next) => next(e))
  on('classic.Stop', async ($, e, next) => next(await marked($, e))).catch(($, e, next) => next(e))
  on('classic.PreCompact', async ($, e, next) => next(await marked($, e))).catch(($, e, next) => next(e))
  on('classic.PostCompact', async ($, e, next) => next(await marked($, e))).catch(($, e, next) => next(e))
}
