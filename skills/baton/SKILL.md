---
name: baton
description: Use when the user wants to hand context off to a new Claude Code session - "write the handoff", "/baton", "I'm running out of context", "let's start a fresh session", "save where we are", "wrap this up, we continue tomorrow". Writes a size-capped handoff document that the next session receives automatically.
user-invocable: true
allowed-tools: Bash, Read, Write, Glob, Grep
---

# Writing the handoff

You draft **the body only**. The code composes the final file: frontmatter, date,
branch, commit and git context. Do not write any of that.

## 0. Which project

If the session started with a `<baton-index>` instead of a handoff, this root
holds several projects. Do not write anything until you know which one:

- The user named one, or you already ran `baton.py load <name>` this session:
  that is the target, and `/baton` writes there on its own.
- Otherwise, ask in one line. Never infer it from which files were touched: in a
  session that touched two projects, guessing overwrites a good handoff.

Pass `--project <name>` to `context` and `write` only to override the active
project, or to create the handoff of a project that does not have one yet — the
folder must already exist.

## 1. Ask for the context

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" context
```

It tells you where to write the draft, what the budget is and which sections are
valid — in the configured language. Read it before drafting.

## 2. Pick the mode

If the user gave you the mode in the arguments, use it and skip to step 3.

Choose `continue` **only** if you can answer yes to all three:

1. Is there a concrete task, already started, unfinished?
2. Can you name the next step in one imperative sentence with a file and a line?
3. Does the user expect you to resume it **without asking them anything first**?

If any answer is no, or if you are unsure: `memory`. No exceptions.

`memory` is not the consolation prize, it is right almost always: the work
finished, it was an exploration with no open task, or the user said "stop here".
Over-choosing `continue` is the failure that makes the next session start on its
own and touch work nobody asked for.

## 3. Draft the body

Use `Write` at the draft path from step 1. **The body only**, starting directly at
the required section.

Sections, in this order. Only the first is required:

| Section | What goes in | What does not |
|---|---|---|
| `State` | What is done and what is not, with concrete paths | Narrating the session |
| `Decisions and why` | One line per decision: "what — why" | The what without the why |
| `Blockers` | What prevents progress and what it depends on | Difficulties already solved |
| `Next step` | One imperative sentence with file and line | A list of options |
| `Traps` | What cost you time and would cost it again | The obvious parts of the language |

Use the section names exactly as `context` printed them: they follow the
configured language.

**Hard rule: if a section does not apply, do not write it.** No "Blockers: none",
no "N/A", no "—". The validator rejects them, and empty sections are exactly where
these documents put on weight.

What earns the budget:

- **The why behind decisions.** The *what* is already in the code and in git; the
  *why* is nowhere and is what dies when the session closes.
- **Concrete paths and lines**, not descriptions ("`src/pay.ts:214`", not "the
  payments module").
- **What you cannot deduce by reading the repo.** If 30 seconds of reading the
  code recovers it, leave it out.

Do not repeat the branch, the commit or the changed files: the code adds those.

## 4. Write it

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/baton.py" write --mode <memory|continue>
```

By exit code:

- **0** — written. Report the path, the mode and the lines used. **Stop there**:
  do not open a new session and do not carry on working.
- **1 — does not fit.** Trim and repeat. If it rejects you twice, on the third
  attempt **do not rewrite shorter: delete a whole section**. Shortening sentences
  does not save 27 lines; deleting `Traps` does. Rewrite the **whole** draft with
  `Write`, never `Edit`.
- **2 — wrong structure.** Fix what the error says (missing required section,
  invented section, filler, `continue` without a next step). This is not a size
  problem: do not trim.
- **3 — environment.** Stop and tell the user. Do not retry.

## When the hook asks you after a compaction

If you got here because baton asked at the end of a turn, the compaction summary
is in your context: it is your best material. Do the same as always and respect
the budget — **do not copy the summary, distil it**.
