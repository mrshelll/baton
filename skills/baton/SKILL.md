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

**`/baton` takes no arguments.** The user types the command and nothing else: the
mode is your decision (step 2) and the target is baton's, resolved from disk. In
almost every session there is nothing to do here — run `context` and carry on.

The exception is a root that holds several projects. Then the commands resolve
the target in this order, without you doing anything:

1. the project you loaded with `baton.py load <name>` this session,
2. the project the session is standing in.

If neither settles it, the command **stops and tells you so**. Only then: ask the
user in ONE short line which project this handoff belongs to, and repeat the
command with `--project <name>` yourself. A folder name is enough, `.` means the
root, and a folder with no handoff yet is accepted — that is how a project gets
its first one.

Pass the same `--project` value to `context` and to `write`. Writing the draft
creates `.baton/`, which is a root marker, so the root may move between the two
commands; the value keeps meaning the same folder, but only if you do not change
it halfway.

Two rules about that question. Never work the answer out from which files the
session touched — in a session that touched two projects, guessing wrong
overwrites a good handoff. And never ask the user to type the flag: they answer
in words, you pass the flag.

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
| `Blockers` | What prevents progress and what it depends on, **questions to the user in the words you asked them** | Difficulties already solved |
| `Next step` | One imperative sentence with file and line | A list of options |
| `Traps` | What cost you time and would cost it again | The obvious parts of the language |

Use the section names exactly as `context` printed them: they follow the
configured language.

**Hard rule: if a section does not apply, do not write it.** No "Blockers: none",
no "N/A", no "—". The validator rejects them, and empty sections are exactly where
these documents put on weight.

**If the session ended waiting on the user, write the questions themselves.** Not
the problem behind them — the question, in the words you put it. The answer comes
back keyed to how you asked: reconstruct the question from the problem and you
will re-ask it differently, and then "yes, but only if it is current" no longer
says which one it answers. Number them if there are several, so an answer can
name one. This is the one case where quoting yourself is worth the lines.

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
