# Changelog

## 0.5.1 — 2026-09-25

### Fixed
- **After a turn that read images, the context was read blind.** baton looked
  for the latest answer in the last 256 KB of the transcript, and an image read
  leaves its result there as a single line of up to 1.4 MB: the answer sat just
  before it, out of reach, and baton logged "context unknown" and stayed quiet.
  The ask was delayed, not lost — a blind turn does not consume the threshold —
  but across 237 real transcripts it happened at 1.3% of the moments a hook
  runs, all of them in sessions that read screenshots. When the tail holds no
  answer it now grows four times over, up to 16 MB; the farthest answer seen was
  2 MB back. What is read is still parsed in memory for the same three numbers.

## 0.5.0 — 2026-09-25

Until now baton wrote the handoff when asked, or right after a compaction. By
then it was late: a compaction is the harness deciding by itself what survives of
the conversation, and it decides when the window is full, not when you are ready
to stop. This release gets there first.

### Added
- **The handoff is asked for when the context window fills up.** At 60% the
  model is told once, after a batch of tools, not to start a new task. At 65%,
  when the turn ends — the one moment no tool and no subagent is running — it is
  asked to **ask you**, in one line, whether to write the handoff, and it writes
  nothing until you answer. At 85%, if you carried on, it asks once more and the
  handoff is rewritten whole, because the one from 65% has aged. Every value is
  configurable under `context_window`; `confirm: false` skips the question.
- **How full the window is, read from the transcript.** Hooks receive no figure
  about the context, but every answer in the session transcript records the
  `usage` of its request, and the sum of its three input fields is the context
  that request occupied — the same sum the statusline paints. `output_tokens` is
  not part of it. Answers that measure zero are skipped: Claude Code writes
  "No response requested." as an assistant entry with every counter at zero, 30
  of them in one machine's transcripts, and reading one as the latest would say
  0%. The reading trails the statusline by one answer: Claude Code writes the
  transcript a step after its hooks run, which a real session showed — when the
  tool hooks fire, the answer that called the tool is not written yet. A few
  thousand tokens, nothing next to a threshold.
- **The window size, from the table Claude Code itself uses.** Extracted from
  2.1.282, with the model read from the transcript's identity entry, the only
  place the `[1m]` suffix survives. The frontier does not follow the family:
  within Opus it moves at 4.7, within Sonnet at 5 — a `claude-sonnet-5` session
  without a suffix really reached 295,549 tokens. A model newer than the table
  starts at 200k and is learnt: reaching N tokens proves the window holds at
  least N, so the size only goes up. The two `CLAUDE_CODE_*` window variables,
  the `autoCompactWindow` setting and `context_window.budget_tokens` win over the
  table.
- `doctor` prints the last reading, the size it used and where that size came
  from, so "why did it not ask me at 80%?" is one command away. Every turn's log
  entry carries the percentage.

### Changed
- **A promise in "What baton will never do" is withdrawn.** It read: *"a `Stop`
  that interrupts outside the moment right after a compaction"*. It described the
  mechanism when what it protected was the principle — never interrupt with work
  in flight — and a `Stop` at the end of a turn, before the compaction, keeps that
  principle. It now reads: *"a `Stop` that interrupts with work in flight, or
  twice at the same threshold"*. The promise about `PostToolUse` stands: the
  early warning uses `PostToolBatch`, once per batch, and never blocks.
- The reasoning "drafting at 70-80% is expensive and can trigger the compaction
  it pre-empts" is gone from the code and both READMEs. It held at 80% of a 200k
  window; at 65% of today's windows a handoff costs a few thousand tokens. What
  survives of it is the cap: no threshold above 95.
- The compaction request and the new one share one cooldown: what it protects is
  the person, not a mechanism. When both are due at once the compaction wins and
  the threshold stays available.

### Fixed
- A `pending.json` holding only the cooldown stamp counted as a pending
  compaction. Nothing wrote one before this release; the new request does, and
  the next turn would have asked for a compaction handoff with no compaction.
  Caught by a test before it shipped.

### Security
- **baton now reads the session transcript**: the last 256 KB, plus the first
  1 MB when the model's identity is not in the tail. It keeps three numbers and
  the model id; nothing the conversation says is kept, logged or sent anywhere.
  The format is Claude Code's internal one and will change — when baton does not
  understand it, it stays quiet rather than guess. Only a path is opened: an
  integer `transcript_path` would have been taken as a file descriptor, and
  closed.

## 0.4.7 — 2026-09-14

### Fixed
- **A wide terminal broke the shape the wrapping exists to build.** The hook does
  get `COLUMNS` on a real install — a local subprocess does not, which is why
  0.4.6 measured this wrong — so the lines grew to fill a 160-column window,
  overflowed the indent the harness prints them inside, and the TERMINAL wrapped
  the remainder to column zero, under nothing. The last word of a question
  appeared to be a heading of its own. The terminal's width can now only ever
  narrow the measure, never widen it past what is comfortable to read.

### Changed
- `receipt_lines` defaults to 12. It is a cap and not a target — a handoff with
  one thing left in it spends two lines whatever the cap says — so the old 8 cost
  nothing on a quiet handoff and, on a loud one, let a single verbose item crowd
  out the two questions behind it.

### Documentation
- Both READMEs describe what baton does rather than what changed in it: the
  repeat notice on a handoff delivered twice, and the minimal handoff baton
  writes itself after three failed attempts, were features with no documentation
  at all. A diagram that compared a case with "exactly as before", a config row
  that called a behaviour "the old one-liner", and a layer described as "one line
  on injection" when it is now a block, all named a past release instead of the
  present behaviour.

## 0.4.6 — 2026-09-14

0.4.5 shipped on a premise read off the binary and never checked against a real
terminal: that the harness reprints every line of a hook message with its own
`SessionStart:clear says:` prefix. It does not — only the first line carries it,
the rest come out indented and clean. The receipt had been squeezed to fit a
cost that was not there.

### Changed
- **Long items are wrapped, not cut.** The per-line cut at a fixed column landed
  mid-question on its first real use — "do I carry on with the heavy one, do the
  four light ones fir…" — which is the exact half-sentence the whole plugin
  exists to refuse, committed by the one part of it a person actually reads. The
  budget is now spent in whole items, like the document's own, and the items that
  did not fit are counted instead of chopped.
- **A shape a person can scan.** The section owns a line, each item keeps the
  author's own marker — they numbered the questions so an answer could name one —
  and a continuation hangs under the text it continues, so a marker at the left
  margin is visibly a new item rather than more of the last one. Emphasis markers
  no longer reach the terminal as literal asterisks.
- `receipt_lines` now means lines added under the first one, and defaults to 8.
  The old 5 was chosen to ration a prefix that never repeats.
- Both READMEs stated the prefix claim as fact. Corrected.

## 0.4.5 — 2026-09-14

Found by using it: open a session, type "let's carry on", and get back "context
loaded, what do you want to do?". The mode was right and the document was there.

### Added
- **The receipt shows what the session left behind.** The handoff goes to the
  model's context, so it never reaches the screen: the person who wrote it could
  not see what they had left without spending a turn asking for it back. It is
  extracted verbatim and cut on whole lines, never summarised, and which section
  it shows depends on what was left — blockers or unanswered questions first, a
  written next step if there are none, and otherwise the state, which always says
  what is still missing. `continue` mode leads with the next step. A root with
  several projects lists them with mode and age. New `receipt_lines` sets the
  budget, `0` restores the old single line.

  The second effect is the one that matters: the first message stops being "let's
  carry on" and becomes the decision. That also names the session in `/resume`,
  which is generated from the first message before any reply, and generated once
  — so every session that opened with "let's carry on" was called exactly that.

### Changed
- **Memory mode now knows what to do when told to carry on.** The instruction
  covered the moment before the user speaks and said nothing about the moment
  they do, so a "let's carry on" was read as still not having said anything, and
  the reply was another question. It now answers with what the document leaves
  open and asks which to take. Telling is not starting: the mode still forbids
  opening files and running commands.

### Fixed
- **A handoff in another language showed the git context as if it were the
  work.** Found the way the last six were: running the hook against a folder
  shaped like a real install, with the whole unit suite green. `extract_body`
  drops the git section by matching the CONFIGURED label, so a Spanish
  `## Contexto` survives an English session -- and the receipt showed the one
  part of the document the code wrote itself. Section labels are now matched
  across every installed language, which also means a Spanish `Bloqueos` is
  still recognised as blockers by an English config. A handoff travels inside a
  repo: whoever clones it does not share your config.
- **A section holding only invisible characters won the pick and printed an
  empty line**, hiding the section that actually had something in it. The
  emptiness test now runs through the same sanitising pass the receipt prints
  through, so what is tested and what is shown cannot disagree.
- **A project list longer than the receipt was cut in silence**, which reads as
  "these are all the projects there are".
- **The wrapper could push a full-budget handoff past the harness ceiling**, and
  the new paragraph above made it measurable: worst case — a handoff at 6,000
  characters, 400 days old, on another branch, with 1,234 commits on top and a
  repeat notice — left a deficit of 27 characters in Spanish. The handoff would
  have been trimmed, on whole lines and declared, but trimmed. Both instructions
  were tightened, and `tests/test_output.py` now pins the invariant so the next
  sentence anyone adds fails the suite instead of quietly eating the document.

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
