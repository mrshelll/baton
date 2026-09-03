# Changelog

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
