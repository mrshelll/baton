# Changelog

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
