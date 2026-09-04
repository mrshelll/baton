# Changelog

## 0.4.4 — 2026-09-04

### Changed
- **`/baton` takes a note, not a grammar.** The argument hint advertised
  `[memory|continue] [project] [note]` while the skill said the command takes no
  arguments, and the README showed `/baton memory` as normal use, a hundred lines
  above "You never type arguments". The mode keyword was redundant with the
  note — "do not resume, just remember this" asks for the same thing in words —
  and `[project]` was never parsed at all. Anything after `/baton` is now a note;
  the mode stays the model's decision unless the note settles it.
- **A cold root says that a subfolder may be the target.** Traced from the way a
  factory root is actually used: session at the root, work on a subproject, a
  bare `/baton`. With no handoff and no project anywhere yet, `context` answered
  as if this were a plain repo and the handoff landed on the root in silence —
  which made the root a project, and the next `/baton` on another subfolder
  overwrote it. The one-handoff-for-two-projects failure, back in through the
  door marked "first time"; in the real install it had not bitten only because
  the first project was bootstrapped from inside its own folder. `context` now
  says so at a cold root, and the skill says what to do with it: the
  conversation decides whether there is a question, the user decides the answer,
  and a plain repo never hears about it. It still resolves to the root, so the
  first `/baton` in an ordinary repo is unchanged.

### Fixed
- The Spanish README documented `/baton memoria`, `/baton continuacion` and
  `baton.py ver`, none of which exist. The manual check for two projects in one
  folder said `/baton a` in both languages, an argument the command never read.

## 0.4.3 — 2026-09-03

### Changed
- **A session that ends waiting on the user now records the questions themselves,
  in the words they were asked** — not just the problem behind them. Found in a
  real handoff: the three pending product decisions were all there, numbered and
  explained, but as problems. The next session would re-ask them in its own
  words, and an answer already written against the original wording ("yes, but
  only if it is current") no longer says which question it answers. The budget
  was not the constraint — that handoff used 85 of its 120 lines. It was drafting
  guidance the skill did not give.

  This is guidance, not a rule the validator can enforce: it cannot tell a
  question recorded well from one recorded badly.

## 0.4.2 — 2026-09-03

Both of these came out of the second real run, minutes after 0.4.1 shipped.

### Fixed
- **`context` took `proyectos/radar` and `write` refused the very same string.**
  Writing the draft in between creates `.baton/`, a root marker, so the root had
  moved down onto that folder and the relative path named nothing any more. 0.4.1
  had covered the bare-name form of this and missed the path form. A key naming
  the root itself — its folder name, or any trailing slice of its path — now
  resolves, so one string means one folder across the whole sequence.

### Changed
- **A root with exactly one project no longer decides on its own.** 0.4.1 skipped
  the question there, reasoning there was nothing to choose between. There is:
  being the only project on disk is not evidence that THIS handoff is that
  project's. A session at the root, working on a folder that has no handoff yet,
  would have had its content written over the one project that does — the exact
  failure the design forbids, reintroduced by a convenience. The count never
  changes what is being decided, which is whose handoff gets replaced.
- The question now offers all three real answers — one of the listed projects,
  the root itself, or a folder with no handoff yet — instead of only the first.

## 0.4.1 — 2026-09-03

The first real run of 0.4.0, in a folder with two factory projects, failed four
different ways in one session. None of them was visible to the 288 unit tests
that were green at the time — the same lesson 0.3.1 taught, learned again.

### Fixed
- **`--project` only accepted a full relative path**, while the index and `load`
  both take a folder name. That contradiction is charged at the cold start, the
  one call where nothing exists yet to list as a hint, and it is what blocked the
  first real session.
- **A `/baton` with the session standing inside a subfolder claimed the root in
  silence.** That is how a `.baton/` ends up in a folder nobody wanted it in —
  and, worse, makes that folder a root with a document of its own forever. It now
  asks, once: afterwards the handoff exists and everything resolves on its own.
- **The flag stopped resolving halfway through the cold start.** Writing the draft
  creates `.baton/`, which is itself a root marker, so between `context` and
  `write` the root moved down to the very folder that had been named. A folder
  named by its own name now always resolves.
- **`context` refused a project `write` would have created**, so the cold start
  died on the first command of the skill, before there was even a draft path to
  answer with.

### Changed
- **One project and a root that is not one: no question.** There is nothing to
  choose between, and choosing among several is the only case where being wrong
  costs a handoff. The folder the session is standing in still wins over it —
  picking the only project while standing somewhere else is the same failure in
  reverse.
- The messages that stop a command are written as instructions to the model, not
  to the person: ask the user in one line, then pass the flag yourself. **Nobody
  should have to type `--project`.** Arguments were always an override; now the
  skill, the command and both READMEs say so.

## 0.4.0 — 2026-09-03

### Added
- **Roots that hold several projects.** Opening a session at a folder that
  *contains* projects — a client folder, a software factory, a monorepo — used to
  make them share one handoff: a single 6,000-character budget for two unrelated
  bodies of work, and an injection about the wrong project half the time. A
  project is now any folder under the root with its own `.baton/HANDOFF.md`,
  discovered by scanning rather than declared anywhere: the same rule that
  already decides whether a project is enabled, applied one level down.
- **An index instead of a document** when the root holds several. It says which
  projects exist, in what mode and how old, and grants nothing: receiving a list
  of what exists is not receiving context, let alone authorisation to work.
- **`baton.py load <name>`** delivers one project's handoff — same wrapper, same
  freshness, same repeat notice, same trim as the hook — and marks it as the
  session's active project. A bare `/baton` then writes there.
- **`--project` on `context`, `write` and `show`**, which is also how a project
  gets its first handoff. The folder must already exist: baton creates `.baton/`
  inside one, never the project folder itself, so a typo cannot found a project
  in a directory nobody made.
- **`discovery` config**, read only from the root because it describes the shape
  of the tree, not a project. Depth 2 by default; deeper is a decision, since the
  scan runs on every session start of every project on the machine.
- `doctor` reports how deep it looked, what it found, whether the scan hit its
  cap, and which project is active — so "my project does not show up" is never a
  mystery.

### Changed
- The activation lives exactly one session: a fresh start (`startup`, `clear`)
  clears it, a continuation (`compact`, `resume`, `fork`) keeps it. Clearing on
  compaction would drop the target exactly when the automatic cycle is about to
  ask for the handoff.
- With several projects and none active, `write` lists them and stops instead of
  guessing. The conversation is never used to infer the target: in a session that
  touched two projects, guessing wrong overwrites a good handoff.
- The `Stop` hook only interrupts when there is a resolvable target. A session
  that never loaded a project in a root with no document of its own gets silence,
  not a question the hook cannot answer on its own.
- Config chains global → root → subproject, so a global `language` keeps applying
  without being repeated in every project folder.

A single-project install behaves exactly as before, and that is a test rather
than a hope: `test_hook_session_start`, `test_auto_cycle` and `test_cli` pass
untouched.

## 0.3.2 — 2026-09-03

### Added
- **A section on checking your install actually works**, in both READMEs: the
  hook fires, memory mode, the canary, and the automatic cycle. These are the
  checks that caught the 0.3.1 freshness bug, which 211 unit tests had missed.
  Undocumented, whoever installs baton has no way to tell a working install from
  a silently broken one.
- The measured contrast that justifies the design: a real compaction summary of
  **12,780 bytes** against a 6,000-character budget, distilled to a 45-line
  handoff and 2,763 characters injected.

### Fixed
- The two READMEs claimed 200 and 187 tests while the suite ran 214 — three
  numbers for one fact, with the translations drifted apart. A test now counts
  the suite and asserts the figure in every badge and body line of both files, so
  the claim cannot go stale again.

## 0.3.1 — 2026-09-03

### Fixed
- The freshness notice fired for baton's own commits. Committing the handoff --
  which the design tells you to do -- produced the self-contradicting "1 new
  commits and 0 changed files" on the next session. Since it happened on every
  single handoff, the notice would have fired always, and a notice that always
  fires is one the model learns to ignore. Commits touching nothing outside
  `.baton/` no longer count.

Found by running the manual acceptance tests on a real install, which is exactly
what they are for.

## 0.3.0 — 2026-09-03

Internationalisation. Breaking change: config keys, mode values and file names
are now in English.

### Changed
- **Config keys are English**: `limits.lines` / `limits.characters` /
  `limits.tokens`, `document`, `history_max`, `inject_on`, `cooldown_minutes`,
  `receipt`. They are a machine interface, and whoever types them should not need
  to speak another language. An old Spanish key now gets a warning pointing at
  the new one instead of an unhelpful "unknown key".
- **Mode values are English**: `continue` and `memory`. The enum stays English in
  every language, so the frontmatter can be parsed the same way everywhere.
- **The document is `.baton/HANDOFF.md`**, and the state files under
  `.baton/local/` follow (`draft.md`, `deliveries.json`, `log.jsonl`, …).
- Subcommands: `context`, `write`, `show`, `doctor`.
- Code, comments and tests are in English.

### Added
- **`language` setting**, `en` by default, with `es` included. It changes
  everything a human reads — section headings, error messages and the
  instructions injected into the model — while the keys stay English. Adding a
  language is one JSON file in `templates/`.
- `README.md` in English and `README.es.md` in Spanish, both with diagrams.
- A check that both language files carry exactly the same keys: an incomplete
  translation would otherwise fail at runtime, inside a hook.

### Migration
There are no installs to migrate yet. If you have a `.baton/TRASPASO.md`, rename
it to `.baton/HANDOFF.md` and translate the config keys.

## 0.2.1 — 2026-09-03

### Fixed
- A state file holding valid JSON that was not an object (a list, for instance)
  propagated `AttributeError` to the hook.
- A non-textual `last_request` in the pending flag raised `TypeError`, which was
  not caught.

Both broke the central guarantee — the hook always exits 0 — and now have
regression tests that fail against the previous code.

### Changed
- Simplification pass: reading and writing state files, collision-free naming and
  UTC date formatting were unified. `snapshot()` split into three. Unreachable
  code and unused parameters removed. No visible behaviour change.

## 0.2.0 — 2026-09-03

First version with the full cycle working end to end: `/baton` writes, the
automatic cycle (`PostCompact` + `Stop`) keeps it up to date, and `SessionStart`
injects it with its mode and its freshness notice.

## 0.1.0 — 2026-09-03

Installable skeleton: manifests, the three hooks registered, `doctor` and the log
that proves the hook fired.
