# baton

**Context handoff between Claude Code sessions, with a document that doesn't grow.**

***English** · [Español](README.es.md)*

[![tests](https://img.shields.io/badge/tests-596-brightgreen)](tests/)
[![python](https://img.shields.io/badge/python-3%20stdlib-blue)](#requirements)
[![licence](https://img.shields.io/badge/licence-MIT-lightgrey)](LICENSE)

---

## The problem

When a Claude Code session runs long, quality degrades and you need to start a
fresh one. The handoff is manual, and the plugins that automate it share one
measured flaw: **the document grows without bound**.

```mermaid
xychart-beta
    title "Tokens every new session pays just to start"
    x-axis "Handoffs accumulated" [1, 10, 20, 30, 40]
    y-axis "Tokens in the document" 0 --> 16000
    line "A document that accumulates" [420, 3600, 7100, 10600, 14200]
    line "baton (hard cap)" [1700, 1700, 1700, 1700, 1700]
```

The upper line is a real case: **931 lines ≈ 14,200 tokens**. The document that
existed to *save* context became the single largest consumer of context at
startup.

And it gets worse. Verified against the Claude Code 2.1.259 binary, the context a
hook injects is **truncated at 8,000 characters or 200 lines, silently**.

```mermaid
block-beta
  columns 5
  A["Document<br/>14,200 tokens"] space B["Harness ceiling<br/>8,000 characters"] space C["What reaches<br/>the model"]
  A --> B
  B --> C
```

A handoff that size **does not fit**. It arrives cut in half and nobody says so:
the model reads half a sentence and treats it as whole.

## How baton solves it

```mermaid
flowchart LR
    subgraph w["When writing"]
        M["The model drafts<br/>the body only"] --> V{"Fits the<br/>budget?"}
        V -- "no" --> R["Fails and names<br/>the section to cut"]
        R -.-> M
        V -- "yes" --> C["The code composes<br/>and writes it whole"]
    end
    subgraph i["When the next session starts"]
        C --> S["SessionStart"]
        S --> I["Mode instruction<br/>+ freshness notice<br/>+ sanitized document"]
    end
    style R fill:#ffe6e6,stroke:#c00
    style C fill:#e6ffe6,stroke:#0a0
```

- **Rewritten whole, never appended to.** One file, no stacked entries.
- **A hard budget enforced by code**: 120 lines / 6,000 characters, derived
  backwards from the harness's real ceiling. If it doesn't fit, the command
  **fails and names the section to cut** — it never cuts mid-sentence, because a
  truncated handoff lies. On the third failed attempt baton writes a minimal
  handoff itself, keeping the required section and declaring the trim inside the
  document: a cut that says so beats a model looping on a budget it cannot meet.
- **Genuinely optional sections.** No blockers? The section *doesn't exist*. No
  "Blockers: none": empty sections are where the others put on weight.
- **Git facts come from the code**, not the model: branch, commit, uncommitted
  files, date. Exact, and free of budget.

## The two modes

This is the differentiator, and no equivalent plugin has it: the others assume
there is always unfinished work, so the new session starts on its own and touches
what nobody asked for.

```mermaid
flowchart TD
    Q{"Is there a task<br/>started and unfinished?"}
    Q -- "yes, and I can name<br/>the next step" --> CONT["continue mode"]
    Q -- "no, or I'm unsure" --> MEM["memory mode"]
    CONT --> CA["The new session<br/>resumes and starts"]
    MEM --> MA["The new session<br/>does NOT start work:<br/>it waits for you"]
    style CONT fill:#e8f0fe,stroke:#1a73e8
    style MEM fill:#fef7e0,stroke:#f9ab00
```

| | `continue` | `memory` |
|---|---|---|
| When | A task is half done | Progress made, nothing to continue |
| Requires `Next step` | Yes, the code enforces it | No |
| The new session | Confirms and starts | Greets and **waits** |

Waiting is not silence. Say *let's carry on* or *where were we* and a `memory`
session tells you what the document leaves open and asks which to take — without
opening a file, because telling is not starting.

On any ambiguity — broken frontmatter, corrupt document, unknown version — baton
falls back to `memory`. An unreadable document can never authorise continuing
work.

## The automatic cycle

While you work you aren't thinking about handoffs. baton is, at three moments:
when the context window starts to fill, at the end of a turn with nothing
running; right before the harness compacts, through the model that writes the
summary; and right after, if that did not produce one.

### Before the harness compacts: the context window

A compaction is the harness deciding for you what survives of the conversation,
and it decides when the window is full, not when you are ready to stop. baton gets
there first:

```mermaid
sequenceDiagram
    participant U as You
    participant CC as Claude Code
    participant B as baton
    participant D as .baton/HANDOFF.md

    U->>CC: you work
    CC->>B: PostToolBatch (after a batch of tools)
    B->>B: reads the transcript, 61% of the window
    B-->>CC: "do not start a new task"
    CC->>B: Stop (end of turn, nothing running)
    B->>B: 66%, past the 65% threshold
    B-->>U: on screen, context at 66%
    B-->>CC: "ask whether to write the handoff"
    CC->>U: shall I write the handoff now?
    U->>CC: yes
    CC->>D: handoff drafted and validated
    U->>CC: you open a new session
```

- **At 60%**, after a batch of tools, the model is told once not to start a new
  task and to finish the one in progress.
- **At 65%**, when the turn ends — the one moment nothing is running, no tool and
  no subagent — baton asks the model to **ask you**, in one line, whether to write
  the handoff. Nothing is written until you answer. Say no and it will not ask
  again at that threshold.
- **At 85%**, if you carried on anyway, it asks once more, and the handoff is
  rewritten whole: the one from 65% has aged.

**How it knows how full the window is.** Hooks receive no figure about the
context. The session transcript does: every answer records the `usage` of its
request, and `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`
is exactly the context that request occupied — the same sum the statusline
paints. The window size comes from the model: baton carries the table Claude Code
itself uses, and reads the model from the transcript *with* its `[1m]` suffix,
because `message.model` never carries it. The frontier does not follow the family
— within Opus it moves at 4.7, within Sonnet at 5 — which is why it is a table and
not a rule.

A model newer than the table starts at 200k and is **learnt**: a session that
reaches N tokens is proof the window holds at least N, so the size only ever goes
up. `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, Claude
Code's `autoCompactWindow` setting and `context_window.budget_tokens` all win over
the table.

**Why the thresholds stop at 95.** Drafting a handoff costs a few thousand tokens.
At 65% that is nothing; at the very edge it could trigger the compaction it exists
to get ahead of.

### When the harness compacts

Claude Code compacts in three ways: when the window fills, when you type
`/compact`, and when the session sits idle. **Idle compaction** kicks in when the
session has been quiet for close to an hour and the conversation is past 200,000
tokens: it compacts just before the prompt cache expires, so coming back does not
re-read the whole conversation uncached. It exists to save tokens, and it is
worth keeping on.

It also changes what baton has to catch. With a 1M window, idle compaction
arrives at 20–30% of the context, long before the 65% threshold, so the threshold
ask never comes. On one real project the context never went past 48%, and every
handoff there came out of a compaction summary, asked for after coming back. A
hook cannot even tell idle compaction from the window one: both arrive as `auto`.

So baton writes the handoff right before any compaction, whatever started it:

```mermaid
sequenceDiagram
    participant U as You
    participant CC as Claude Code
    participant S as Summarizer
    participant B as baton
    participant D as .baton/HANDOFF.md

    Note over U,CC: idle, window full or /compact
    CC->>B: PreCompact
    B-->>CC: "after the summary, append the handoff"
    CC->>S: the conversation plus that instruction
    S-->>CC: summary and handoff block
    CC->>B: PostCompact (carries compact_summary)
    B->>D: block validated and written, memory mode
    B-->>U: handoff ready, type /clear
    U->>CC: /clear
    CC->>B: SessionStart
    B-->>CC: the fresh handoff
```

**`PreCompact` does work for this, through the summarizer.** Earlier versions of
this README said it could not: a compaction has no model turn, and the binary
rejects hooks that need a conversation — *"no conversation context is
available"*. That is still true, but whatever a `PreCompact` hook prints is
appended to the summarizer's instructions, and the summarizer is a model with the
conversation in front of it. baton asks it to append the handoff after the
summary, between `<baton-handoff>` marks, with the sections, the budget and the
mode rule of the `baton` skill. `PostCompact` takes that block and writes it
through the same path as `/baton` — same budget, same history — so nothing lands
that a `/baton` would have refused.

There is no extra call: the handoff comes out of the same request as the summary,
with the cache warm, and only its output tokens are added. The turn baton used to
force after a compaction, to draft from the summary, is gone.

**Always in `memory` mode, whatever the block asks for.** Claude Code keeps the
last messages verbatim and summarises only what came before them — in practice
the model's last answer, usually the turn's conclusion. The summarizer never sees
it, so the step it calls next may already be done. In testing that is exactly
what happened: a block chose `continue` with a step already finished. A new
session would have repeated it. `memory` only waits for you.

**What you see.** On `/compact`, Claude Code shows the instruction baton passed
to the summarizer — kept to 12 lines — and keeps it in the compacted context.
Once the handoff is written:

```
baton: handoff ready. Type /clear to continue in a fresh session.
```

Claude Code prints it after its own `PostCompact [...] completed successfully:`
prefix. The `/clear` is always yours. If you carry on in the compacted session
instead, baton stays quiet: the handoff is saved. And that session does not get
the old handoff injected on top of the summary that carries the new one.

**Only where `/baton` would write without asking**: the session's active project,
or the root of a plain repo. At a root with several projects and none loaded,
baton prints nothing, and the compaction goes the way below if the root has a
handoff of its own; otherwise baton stays out of it, as before.

**When it wrote the active project's handoff, the `/clear` that follows carries
on with that project**: the new session gets its handoff, as `load` would give
it, instead of the index. Only that one `/clear`, within 12 hours, and only if
the project is still the active one; any other fresh start forgets the active
project, as always.

**If the block does not come out, baton asks right after.** The summarizer left
it out, it was cut, it did not fit the budget, a `/baton` was mid-draft, or there
was no clear destination but the root has a handoff: baton keeps the summary, arms
a flag, and asks for the handoff at the end of the next turn.

```mermaid
sequenceDiagram
    participant U as You
    participant CC as Claude Code
    participant B as baton
    participant D as .baton/HANDOFF.md

    U->>CC: work until the window fills
    CC->>CC: compacts (auto)
    CC->>B: PostCompact (carries compact_summary)
    B->>B: saves the summary, arms the flag
    Note over B,D: never touches the handoff: a summary<br/>nobody wrote must not overwrite one that was
    U->>CC: you keep working
    CC->>B: Stop (end of turn)
    B-->>CC: "write the handoff now"
    Note over CC: the context has just been emptied:<br/>the cheapest moment in the session
    CC->>D: handoff drafted and validated
    U->>CC: you open a new session
    CC->>B: SessionStart
    B-->>CC: additionalContext with mode and freshness
```

**Why ask right after it.** The context has just been emptied and the summary is
fresh: it is the cheapest moment in the session to draft.

**At most one interruption per threshold and per compaction**, with the harness's
native loop guard (`stop_hook_active`) and a 30-minute cooldown that both reasons
share — what it protects is you, not a mechanism. When both are due at once the
compaction wins: its summary is the better material, and the threshold stays
available.

**The summary is input, never the product.** A real compaction summary measured
**12,780 bytes** against a 6,000-character budget. Storing it as the handoff — the
easy thing, and what a naive design would do — would double the cap and not even
fit the 8,000-character ceiling. It gets distilled instead: that same session
produced a 45-line handoff, 2,763 characters injected.

## Freshness: flag it, never expire it

A handoff from days ago with commits on top lies. On injection, baton compares
against git and says so:

> `[baton] Freshness notice: this handoff was written 6 days ago, on branch`
> `feature/coupons, and you are now on main. Since then there are 14 new commits`
> `and 9 changed files. Treat anything it says about the code as uncertain.`

It also detects that the commit is gone (rebase or squash). **It never expires**:
a project idle for two weeks doesn't invalidate its handoff, you just need to
know it is old. And when there is nothing to say, it spends no lines.

**It also says when it is repeating itself.** A handoff that reaches a session
which already received it arrives with the count and the date of the last time.
Work that has not moved is not news, and without that line the new session reads
it as though it were.

## What you see when a session starts

The handoff goes to the model's context, which means it never reaches your
screen. So baton prints what the session left behind, on the receipt line, before
you type anything:

```
baton: handoff injected -- memory mode, 47 lines, written 2 h ago, and the code moved since
  Blockers
  1. The question that ended the session: do I carry on with the heavy one, do the four
     light ones first to bring the queue down, or do we stop?
  2. Security question still open: if they ever want to give someone access to only some
     venues, deciding that later costs far more than deciding it now.
  (also in the document: State, Decisions and why, Traps)
```

**Long items are wrapped, never cut.** A handoff cut mid-sentence lies, which is
the argument the whole plugin rests on, so the receipt spends its budget in whole
items and counts the ones that did not fit. The author's own numbering is kept —
they numbered the questions so an answer could name one — and a continuation line
hangs under the text it continues, so a marker at the left margin is visibly a new
item.

**It is extracted, never summarised.** baton writes no prose about your work: it
takes the section verbatim and cuts on whole lines. Which section depends on what
was left, because "what was left" is not always a question:

| The document has | You see |
|---|---|
| Blockers, or questions nobody answered | those, first |
| No blockers but a written next step | the next step |
| Neither, just a state | the state, which always says what is still missing |
| `continue` mode | the next step first, which is the point of the mode |
| Several projects and none loaded | the list, with mode and age |

The point is not the reading. It is that your first message stops being "let's
carry on" and becomes the actual decision. That is a better instruction, and it
is also what names the session in `/resume`: the name is generated from your
first message, before any reply, and it is generated once.

`receipt_lines` sets how many lines it may add under the first one. It is a cap,
not a target: a handoff with one thing left in it spends two lines whatever the
cap says. Set `0` for the first line alone.

Lines are wrapped to a readable measure, never to the full width of the window.
A wide terminal filled edge to edge is harder to read, and a line measured
against it overflows the indent the harness prints it inside — at which point
the terminal wraps the remainder to column zero, under nothing, undoing the
structure.

With baton's mod in the terminal, the receipt moves to the panel, next.

## The band and the panel

baton also brings a mod for Claude Code's terminal, so it can be used with clicks
instead of commands: a line always visible above the prompt — the band — and a
panel with the whole handoff.

| When | The band reads | Button |
|---|---|---|
| Normal | `baton · handoff 2 h ago · memory` | |
| After a compaction wrote it | `baton · ✓ handoff ready · just now` | `[ New session ]` |
| A threshold was crossed | `baton · ⚠ context at 65 %` | `[ Write handoff ]` |
| The handoff has blockers | `baton · ⚠ 2 open items · 3 h ago` | |
| No handoff yet | `baton · no handoff in this project` | `[ Write handoff ]` |
| The handoff cannot be read | `baton · ⚠ could not read the handoff` | |

Clicking the line opens the panel; `click → panel` sits on the right when it
fits. `[ New session ]` runs `/clear` for you, as if you had typed it.
`[ Write handoff ]` runs `/baton:baton`. No button has a key: a digit typed into
an empty prompt never presses anything.

Without the mouse: `ctrl+x tab` gives the band the focus, `Tab` or the arrows
move it onto baton's line or a button, and `Enter` presses it — on the line, it
opens the panel. `Esc` gives the focus back to the prompt.

A threshold and a handoff take turns: the band shows whichever came last.
Writing the handoff after `⚠ context at 65 %` settles the warning, and a
threshold crossed after a compaction wrote the handoff replaces
`✓ handoff ready`.

**The panel** is what the receipt shows, whole:

```
baton · my-project                                        ✓ Handoff ready
memory · written just now, on compaction · 42 lines · context 8 %
[ New session ]   Write handoff

⚠ Blockers (2)
  1. …
  2. …
Next step
  …
State
  …
▸ Decisions and why (5)   ▸ Traps (4)

Other projects
  radar · memory · 2 d ago
```

- **The header** says where and how it stands: the status in a word with its
  icon, the mode, when and how it was written, its size and how full the context
  is now. A handoff older than the code carries the freshness warning.
- **One main action**, the one for the moment: `New session` after a compaction,
  `Write handoff` otherwise.
- **Blockers first**, then the next step, then the state. Decisions and traps are
  folded under their names; a long section shows six items and `see more`.
- **Other projects** under the same root open in the same panel, as
  `baton › radar` with a `Back` button. That view only reads: `/baton` writes the
  session's own project, never the one on screen.

**It opens on its own** at startup and after `/clear` when the handoff has
blockers, beside the conversation if the terminal is at least 144 columns wide.
Narrower, it waits for your click: that is Claude Code's rule for a panel nobody
asked for.

**With the mod, the hooks step back.** No receipt at session start, no line after
a compaction — the band says it — and crossing a threshold no longer interrupts
the turn: the band shows `⚠ context at 65 %` with `[ Write handoff ]`. The 60%
warning to the model stays, and so does the ask after a compaction whose block
did not come out: that one is not a threshold.

**`/baton:baton` stays.** Everything the buttons do, the command does; the
buttons type it for you.

**Terminal only.** The mod draws only in the terminal. Without it — a Claude Code
without mods, or the desktop app, VS Code or mobile — everything works as before:
the receipt, the `Stop` that asks at a threshold, and the command. Writing the
handoff at compaction uses plain hooks, so it works on every surface.

The hooks know the mod is there because it marks their input when the session has
a terminal. When the mark does not arrive, they behave as if there were no mod: a
receipt too many beats none. `"display": "panel"` in the config tells them the
same from your side; use it only with the mod, because without it you lose the
receipt and the threshold ask.

**Next to other mods.** The line above the prompt is shared. baton draws its line
under whatever the other mods drew, and nothing while a survey is up.
[`agents-panel`](https://github.com/mrshelll/agents-panel) 0.3.0 stacks with it:
its box above, baton's line below, in either load order. Earlier versions give
up the whole band when something is drawn under them, so depending on load order
their box disappears: update to 0.3.0. A `clear-questions` card still comes
first: while a question is up, `agents-panel` steps aside as it always did.
Whether baton's line stays depends on the order the two run in. With
`clear-questions` below baton in the chain, baton gets the card and draws its
line under it. In the other order, `clear-questions` 0.2.0 returns its card
without letting the mods below it draw, so baton's line is gone while the
question is up and comes back once it is answered.

## Install

```bash
claude plugin marketplace add mrshelll/baton
claude plugin install baton@baton
```

> [!IMPORTANT]
> **Restart Claude Code after installing.** Hooks are loaded at startup: without
> a restart they never fire, and a hook that doesn't fire gives no error — it
> gives nothing. This is the number one failure.

Check it landed:

```bash
/hooks                                    # baton on SessionStart, PreCompact, PostCompact, PostToolBatch and Stop
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" doctor
```

## Use

```bash
/baton                                    # that is all of it
/baton do not resume, just remember this  # anything after it is a note for the model
```

baton picks the mode and works out which project the handoff belongs to. The
note is free text: what you want captured, or the mode you want.

And to inspect:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" show      # summary and cost
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" doctor    # why it isn't working
```

`context`, `write` and `load` complete the CLI, and the skill is what runs them:
they are the steps of a `/baton`, not a second way to use it.

## What a handoff looks like

```markdown
---
baton: 1
mode: continue
date: 2026-09-03T00:54:51-05:00
branch: feature/coupons
commit: a3f9c21
---
<!-- Generated by baton. REWRITTEN IN FULL on every /baton. -->

## Context
- branch `feature/coupons`, 3 uncommitted: src/pay.ts, src/coupon.ts, tests/pay.test.ts
- last commit `a3f9c21` feat: validate the coupon before charging (2026-09-02)

## State
Migrating charging from Stripe Charges to PaymentIntents. `src/pay.ts` already uses
PaymentIntents on the happy path and its 4 tests pass. Refund and webhook are left.

## Decisions and why
- Idempotency key = `order_id`, not a fresh UUID — a client retry must not charge twice.
- The coupon is validated before creating the PaymentIntent — otherwise orphan intents pile up.

## Next step
Implement `refund(order_id)` in `src/pay.ts:214` using the same idempotency key.

## Traps
- `paymentIntents.confirm` returns 200 with `status: "requires_action"`. That is not success.
```

**22 lines out of 120.** The code writes the frontmatter and `## Context`; the
model only writes from `## State` down.

## Where everything lives

```mermaid
flowchart TB
    subgraph home["~/.claude/"]
        P["plugins/baton/<br/><i>the code, once</i>"]
        G["baton.json<br/><i>your default config</i>"]
    end
    subgraph proj["&lt;your project&gt;/"]
        T[".baton/HANDOFF.md<br/><b>committed</b>"]
        L[".baton/local/<br/><i>history, drafts, registers</i><br/>one .gitignore line"]
        CP[".claude/baton.json<br/><i>config for this repo only</i>"]
    end
    P -.->|"reads and writes<br/>wherever you are"| proj
    G -.->|"the project one wins"| CP
    style T fill:#e6ffe6,stroke:#0a0
    style L fill:#f5f5f5,stroke:#999
```

Add **one line** to your `.gitignore`:

```gitignore
.baton/local/
```

**Install once, at user level, and it works across every project.** baton keeps no
registry of projects: each hook receives the session's directory and works there.
In a project where you never ran `/baton`, the plugin is installed but **inert**:
it creates no files and writes nothing. The first `/baton` enables it.

And **you don't need git**. If the project is a repo, baton uses branch and
commits. If it isn't, it works the same without those facts.

## Several projects in one folder

Sometimes you open the session at a folder that *contains* projects rather than
being one — a client folder, a software factory, a monorepo. baton handles it
without you declaring anything:

**A project is any folder under the root with its own `.baton/HANDOFF.md`.** The
path convention is irrelevant; loose folders and grouped ones mix freely:

```
CLIENT-X/                          ROOT/
├── radar/                         ├── projects/
│   └── .baton/HANDOFF.md   ✓      │   ├── one/.baton/HANDOFF.md   ✓
├── portal/                        │   └── two/.baton/HANDOFF.md   ✓
│   └── .baton/HANDOFF.md   ✓      ├── loose/.baton/HANDOFF.md     ✓
└── notes/                  ·      └── .baton/HANDOFF.md           ✓ (the root)
```

At session start you get an **index**, not a document: which projects exist, in
what mode, how old. It grants nothing and authorises nothing — you have not
received anyone's context yet.

```mermaid
flowchart TD
    S["Session starts at a folder"] --> D{"Root has its<br/>own handoff?"}
    D -->|yes| P{"Subprojects<br/>with a handoff?"}
    D -->|no| Q{"Subprojects<br/>with a handoff?"}
    P -->|no| A["the handoff,<br/><i>and nothing else</i>"]
    P -->|yes| B["the handoff, then the index"]
    Q -->|yes| C["the index only"]
    Q -->|no| E["silence: baton is not used here"]
    style A fill:#e6ffe6,stroke:#0a0
    style C fill:#e6f0ff,stroke:#06a
```

When you say which project you are working on, the model runs `baton.py load
<name>` and gets that handoff with the same wrapper, the same freshness notice
and the same budget the hook would have applied. That also marks it as **this
session's active project**, so a bare `/baton` writes there.

### You never type arguments

`/baton` takes none. The mode is the model's decision, and the target is worked
out from disk, in this order:

1. the project loaded with `load` this session,
2. the project the session is standing in — a project folder has its own
   `.baton/`, so baton stops there instead of climbing to the root.

Only two situations are left, and in both baton stops and says so rather than
guessing — the thing it would be guessing is which handoff gets overwritten.
Not even a root with exactly one project decides on its own: being the only
project on disk is not evidence that this handoff is that project's.

- **The first handoff of a project**, where nobody has decided yet whether it
  belongs to a subfolder or to the root — whether the session is standing in
  that folder, or at the root talking about it. A one-time decision, once per
  project, forever.
- **Several projects, none loaded**, when the session never said which it was
  about.

In both, the model asks you in one line and passes the flag itself. You answer
in words.

The activation lives one session: a fresh start clears it, a compaction keeps it.

The scan looks **two levels down** by default, which covers both shapes above. If
your projects sit deeper, say so once in the root's config:

```json
{ "discovery": { "depth": 3 } }
```

Deeper scans cost real time on every session start of every project on the
machine, which is why it is a decision and not a default. `baton.py doctor`
reports how deep it looked, what it found and which project is active.

## Configuration

All optional. `~/.claude/baton.json` for your general preference,
`<project>/.claude/baton.json` for one repo (that one wins).

```json
{
  "limits": { "lines": 120, "characters": 6000, "tokens": 1700 },
  "document": ".baton/HANDOFF.md",
  "history_max": 10,
  "inject_on": ["startup", "clear", "compact", "resume", "fork"],
  "cooldown_minutes": 30,
  "receipt": true,
  "receipt_lines": 12,
  "display": "receipt",
  "language": "en",
  "discovery": { "depth": 2, "max_dirs": 400 },
  "context_window": {
    "enabled": true, "watch_at": 60, "thresholds": [65, 85],
    "confirm": true, "budget_tokens": 0, "min_tokens": 40000
  }
}
```

| Key | Default | What it does |
|---|---|---|
| `limits.characters` | `6000` | **Binding**: the unit the harness truncates by |
| `limits.lines` | `120` | The one a human sees and can fix |
| `limits.tokens` | `1700` | Informational, never rejects alone |
| `document` | `.baton/HANDOFF.md` | Relative to the root; no `..`, no absolutes |
| `history_max` | `10` | Previous versions kept; `0` disables |
| `inject_on` | all five | Which session starts get the handoff |
| `cooldown_minutes` | `30` | Minimum between automatic requests |
| `receipt` | `true` | Whether baton prints anything on screen at session start |
| `receipt_lines` | `12` | Lines the receipt may add under the first; `0` for the first line alone |
| `display` | `receipt` | Who tells you what baton did: the hooks' own lines (`receipt`) or the mod's band and panel (`panel`). The mod's own mark wins when it arrives; `panel` only for when it does not |
| `language` | `en` | Language of everything a human reads |
| `discovery.depth` | `2` | How far down projects are looked for (1-4). **Root only** |
| `discovery.max_dirs` | `400` | Cap on directories examined per scan |
| `context_window.enabled` | `true` | The handoff asked for when the window fills |
| `context_window.watch_at` | `60` | % at which the model is told, once, to wrap up; `0` disables |
| `context_window.thresholds` | `[65, 85]` | % at which baton asks for the handoff at the end of a turn: 1 to 4 values, none above 95 |
| `context_window.confirm` | `true` | Ask you before writing; `false` writes straight away |
| `context_window.budget_tokens` | `0` | Window size in tokens; `0` works it out from the model |
| `context_window.min_tokens` | `40000` | Nothing fires below this many tokens, whatever the percentage says |

`cooldown_minutes` and `context_window` are read from the folder the session runs
in, not from a subproject loaded into it.

**Config keys stay in English in every language.** They are a machine interface,
and whoever types them shouldn't need to speak another one. `"language"` changes
what people read: section headings, messages, and the instructions injected into
the model. Currently `en` and `es` — adding one is a JSON file in `templates/`.

A broken config file never blocks baton: it warns naming the file and carries on
with the good values. Write `lines_max` and it suggests `limits.lines`.

## Security

`.baton/HANDOFF.md` is committed and travels with the repo, so **whoever clones
someone else's repo gets whatever that file says injected into their context**.
baton treats it as untrusted input:

- Control characters, ANSI sequences, bidi marks and zero-width spaces are stripped.
- The content **cannot close its own tag** to escape the block.
- It is preceded by an explicit warning that it is a data document, not instructions.
- The mode is read **only** from the frontmatter, which the code writes: a body
  faking another mode changes nothing.

**baton reads the session transcript.** To know how full the window is, the hooks
that run at the end of a turn and after a batch of tools read the end of the
transcript Claude Code keeps for the session (`transcript_path`): the last 256 KB,
and up to 16 MB when a few large tool results — images read, say — fill that on
their own. They also read its first 1 MB when the model's identity is not in the
tail. The lines are parsed in memory to find three numbers — the input counters
of the latest answer — and the model id. Nothing the conversation says is kept,
logged or sent anywhere: what reaches the disk is a token count per model in
`.baton/local/window.json`. The format is Claude Code's internal one and it will
change; when baton does not understand it, it stays quiet rather than guess.

## Checking your install actually works

Unit tests cannot see the failures that only appear on a real install. These
checks can, and they are the ones that caught the freshness bug in 0.3.1 that 211
unit tests had missed. They take two minutes.

**1. The hook fires.** Open a session in a project where you have run `/baton`.
The startup line should read:

```
SessionStart:startup says: baton: handoff injected -- memory mode, N lines, written ...
```

Under it you should see what was left: blockers, a next step, or the state. No
line at all means the hook did not fire. Run `doctor`. With baton's mod in the
terminal there is no receipt: check 7 replaces this one.

**2. Memory mode — the one that defines the product.** With a `memory` handoff,
open a fresh session and type something trivial and unrelated, like `hello`.

- ✅ It greets in one line and waits.
- ❌ It opens files, proposes a plan, or asks "shall we carry on with X?".

Then type `let's carry on`. It must tell you what the document leaves open and
ask which to take. "Context loaded, what do you want to do?" is the failure: you
just said what you want.

**3. The canary — proves the context reached the model, not just the file.** Put a
line like `canary: xylophone-7731` in `## State`, then ask a fresh session *what
does the canary say*. If it answers, the injection works. If it doesn't, the
handoff reached the file but never the context — the failure no unit test sees.

**4. The handoff at compaction.** In a project where you have run `/baton`, after
a few exchanges, run `/compact`. Above the result you see the instruction baton
passed to the summarizer, and at the end `baton: handoff ready. Type /clear to
continue in a fresh session.` — with the mod, the band says `✓ handoff ready`
instead. `baton.py show` must show a handoff written just now, in `memory` mode.
Carry on without `/clear`: baton must **not** ask for the handoff. Check the
trail:

```bash
cat .baton/local/log.jsonl
```

```
pre-compact   -> handoff block requested                       (asks the summarizer)
session-start -> silent: handoff travels in the compaction summary
post-compact  -> summary saved, handoff written from compaction in memory mode
stop          -> silent: context 9% of 1000k (model)           (nothing to ask)
```

`session-start` and `post-compact` may swap places: Claude Code runs them at the
same time. If `post-compact` reads `summary saved, handoff pending; …`, the block
did not come out and the reason follows the semicolon. Then the next turn must ask
for the handoff on its own, once (`stop -> handoff requested after compaction`),
and **not ask again**.

**5. Two projects in one folder.** Create `<root>/a/` and `<root>/b/`. From a
session opened at `<root>`, work on `a` and run `/baton`: it must ask in one line
whether the handoff belongs to `a` or to the root, and write to
`<root>/a/.baton/HANDOFF.md` when you say `a`. Then the same for `b`.

- Open a new session at `<root>`: you get the **index**, and no project body. Ask
  for the canary of `a` — it must not know it yet.
- Say *work on a*: the model runs `baton.py load a`, and only then does the canary
  answer.
- Run `/baton`: it must write to `<root>/a/.baton/HANDOFF.md` and print that path.
- `baton.py doctor` lists both projects and names `a` as active.

**6. The context window.** In a project where you have run `/baton`, put this in
`.claude/baton.json`, so the thresholds are crossed from the first turn:

```json
{ "context_window": { "watch_at": 1, "thresholds": [1, 85], "min_tokens": 0 } }
```

Ask for anything that uses a tool. When the turn ends you should see
`baton: context at N%` and the model should ask, in one line, whether to write the
handoff. Answer no: it carries on, and **does not ask again**. With the mod,
nothing interrupts the turn: the band shows `⚠ context at N %` with
`[ Write handoff ]`. `baton.py doctor` prints the last reading. If your statusline
shows the context, the window size must match it exactly; the tokens trail it by
the last answer, because Claude Code writes the transcript one step behind its
hooks. Remove those lines when you are done.

**7. The band and the panel.** With the mod loaded, open a session in a terminal
at least 144 columns wide, in a project whose handoff has blockers. The band
reads `baton · ⚠ N open items` above the prompt, with no receipt at the top, and
the panel opens on its own beside the conversation, blockers first. With
`agents-panel` loaded too, its box sits above baton's line. Run `/compact`: the
band turns to `✓ handoff ready` with `[ New session ]`, and pressing it starts a
fresh session that opens the panel again if blockers are left.

## When it doesn't work

A hook that doesn't fire gives no error: it gives nothing. Hence four layers:

1. **The receipt** — its first line on injection. No line, no fire. With the mod,
   the band takes its place.
2. **The log** (`.baton/local/log.jsonl`) — the only thing telling *"didn't fire"*
   apart from *"fired and stayed quiet because there was no document"*: identical
   from outside, opposite causes. Every turn's entry carries the context
   percentage. The one exception is the check after each batch of tools, which
   writes only when it speaks: it runs too often to log every time.
3. **`doctor`** — checks hooks, `python3`, `git`, whether the plugin is enabled
   and whether there is recent activity. If there isn't, it lists causes by
   likelihood, starting with "you installed without restarting".
4. **Silence means exactly one thing**: there is no document. Every other problem
   warns naming the file.

**"It never asked, and I was past 65%."** In order of likelihood: you already
said no at that threshold in this session; another request went out less than 30
minutes earlier (`cooldown_minutes`); or the window size is wrong. `doctor` prints
the last reading, the size it used and **where that size came from** — `model`,
`env`, `settings`, `config`, `calibrated` or `default`. Compare it with your
statusline: the window size must match exactly — the tokens trail it by the last
answer. If the size is wrong, set `context_window.budget_tokens`.

## Requirements

Python 3 (stdlib, **zero dependencies**) and Claude Code. `git` is optional.
The band and the panel need a Claude Code that loads mods (built against
2.1.307); on one that does not, baton works as it always did.

## Development

```bash
./tests/run.sh
```

596 tests on the stdlib's `unittest`: **no Claude Code, nothing to install**. The
hook tests invoke the script as a subprocess with JSON on stdin, exactly like the
harness, because that is the only way to cover the real contract. Temporary
projects are created under a path with a space and an accent, so the awkward case
is the base case.

The mod has its own tests, in TypeScript, run by Claude Code itself:

```bash
claude plugin test .
```

To validate the README diagrams against the real Mermaid parser:

```bash
npm install mermaid jsdom && node tools/validate-mermaid.mjs README.md
```

## What baton will never do

Append to the document instead of rewriting it · write sections saying "none" ·
expire a handoff · open the new session for you · `PostToolUse` or
`UserPromptSubmit` hooks · a `Stop` that interrupts with work in flight, or twice
at the same threshold · block anything after a batch of tools · a second
implementation in bash.

## Licence

MIT
