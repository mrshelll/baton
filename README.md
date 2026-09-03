# baton

**Context handoff between Claude Code sessions, with a document that doesn't grow.**

***English** · [Español](README.es.md)*

[![tests](https://img.shields.io/badge/tests-299-brightgreen)](tests/)
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
  **fails and forces a trim** — it never cuts mid-sentence, because a truncated
  handoff lies.
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

On any ambiguity — broken frontmatter, corrupt document, unknown version — baton
falls back to `memory`. An unreadable document can never authorise continuing
work.

## The automatic cycle

When the harness compacts on its own, you aren't thinking about handoffs. baton is.

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

**Why after compacting and not before.** Before, you are at 70-80% of the window:
drafting there is expensive and the drafting itself can trigger the very
compaction you were trying to pre-empt. After, the context is freshly emptied.

`PreCompact` cannot do this: a compaction has no model turn. The binary itself
says so when it rejects hooks that need a conversation — *"no conversation
context is available"*.

**At most one interruption per compaction**, with the harness's native loop guard
(`stop_hook_active`) and a configurable 30-minute cooldown.

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
/hooks                                    # baton on SessionStart, PostCompact and Stop
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" doctor
```

## Use

```bash
/baton                    # baton picks the mode
/baton memory             # force "just keep this in mind"
/baton continue           # force "carry on with this"
```

And to inspect:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" show      # summary and cost
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" doctor    # why it isn't working
```

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
    P -->|no| A["the handoff<br/><i>exactly as before</i>"]
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
   `.baton/`, so baton stops there instead of climbing to the root,
3. the only project there is, when the root is not one itself.

Only two situations are left, and in both baton stops and says so rather than
guessing — the thing it would be guessing is which handoff gets overwritten:

- **The first handoff of a project**, where nobody has decided yet whether it
  belongs to the folder you are in or to the root. A one-time decision, once per
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
  "language": "en",
  "discovery": { "depth": 2, "max_dirs": 400 }
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
| `receipt` | `true` | The line proving the hook fired |
| `language` | `en` | Language of everything a human reads |
| `discovery.depth` | `2` | How far down projects are looked for (1-4). **Root only** |
| `discovery.max_dirs` | `400` | Cap on directories examined per scan |

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

## Checking your install actually works

Unit tests cannot see the failures that only appear on a real install. These five
checks can, and they are the ones that caught the freshness bug in 0.3.1 that 211
unit tests had missed. They take two minutes.

**1. The hook fires.** Open a session in a project where you have run `/baton`.
The startup line should read:

```
SessionStart:startup says: baton: handoff injected -- memory mode, N lines
```

No line means the hook did not fire. Run `doctor`.

**2. Memory mode — the one that defines the product.** With a `memory` handoff,
open a fresh session and type something trivial and unrelated, like `hello`.

- ✅ It greets in one line and waits.
- ❌ It opens files, proposes a plan, or asks "shall we carry on with X?".

**3. The canary — proves the context reached the model, not just the file.** Put a
line like `canary: xylophone-7731` in `## State`, then ask a fresh session *what
does the canary say*. If it answers, the injection works. If it doesn't, the
handoff reached the file but never the context — the failure no unit test sees.

**4. The automatic cycle.** Run `/compact`. After your next exchange baton should
ask for the handoff on its own, and **not ask again**. Check the trail:

```bash
cat .baton/local/log.jsonl
```

```
stop          -> silent: nothing pending        (before compacting: no interruption)
post-compact  -> summary saved, handoff pending (saves and arms)
stop          -> handoff requested              (asks, once)
```

**5. Two projects in one folder.** Create `<root>/a/` and `<root>/b/` and run
`/baton a` and `/baton b` from a session opened at `<root>`.

- Open a new session at `<root>`: you get the **index**, and no project body. Ask
  for the canary of `a` — it must not know it yet.
- Say *work on a*: the model runs `baton.py load a`, and only then does the canary
  answer.
- Run `/baton`: it must write to `<root>/a/.baton/HANDOFF.md` and print that path.
- `baton.py doctor` lists both projects and names `a` as active.

## When it doesn't work

A hook that doesn't fire gives no error: it gives nothing. Hence four layers:

1. **The receipt** — one line on injection. No line, no fire.
2. **The log** (`.baton/local/log.jsonl`) — the only thing telling *"didn't fire"*
   apart from *"fired and stayed quiet because there was no document"*: identical
   from outside, opposite causes.
3. **`doctor`** — checks hooks, `python3`, `git`, whether the plugin is enabled
   and whether there is recent activity. If there isn't, it lists causes by
   likelihood, starting with "you installed without restarting".
4. **Silence means exactly one thing**: there is no document. Every other problem
   warns naming the file.

## Requirements

Python 3 (stdlib, **zero dependencies**) and Claude Code. `git` is optional.

## Development

```bash
./tests/run.sh
```

299 tests on the stdlib's `unittest`: **no Claude Code, nothing to install**. The
hook tests invoke the script as a subprocess with JSON on stdin, exactly like the
harness, because that is the only way to cover the real contract. Temporary
projects are created under a path with a space and an accent, so the awkward case
is the base case.

To validate the README diagrams against the real Mermaid parser:

```bash
npm install mermaid jsdom && node tools/validate-mermaid.mjs README.md
```

## What baton will never do

Append to the document instead of rewriting it · write sections saying "none" ·
expire a handoff · open the new session for you · `PostToolUse` or
`UserPromptSubmit` hooks · a `Stop` that interrupts outside the moment right after
a compaction · a second implementation in bash.

## Licence

MIT
