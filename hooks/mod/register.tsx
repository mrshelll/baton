import type { EngineInterface, Register } from 'claude-code'
import type { PanelStrings } from '../../types'
import { band, bandLine, stack, type BandActions } from './band'
import { current, refresh } from './data'

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
    openPanel: act(() => $.ui.open({ id: 'baton', title: 'baton', focus: true })),
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
  // changed and no session.start follows.
  on('classic.SessionStart', async ($, e, next) => {
    const answered = await next(await marked($, e))
    void refresh($)
    return answered
  }).catch(($, e, next) => next(e))
  on('classic.Stop', async ($, e, next) => next(await marked($, e))).catch(($, e, next) => next(e))
  on('classic.PreCompact', async ($, e, next) => next(await marked($, e))).catch(($, e, next) => next(e))
  on('classic.PostCompact', async ($, e, next) => next(await marked($, e))).catch(($, e, next) => next(e))
}
