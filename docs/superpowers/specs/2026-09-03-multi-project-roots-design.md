# Multi-project roots

**Status:** design approved, not implemented.
**Target version:** 0.4.0 (new feature, no breaking change).

## The problem

baton assumes one session equals one project. `project_root()` walks up from the
session's `cwd` until it finds `.git`, `.claude` or `.baton`, and everything --
the document, the history, the lock, the automatic cycle -- hangs off that one
directory.

That assumption breaks when the session is opened at a folder that CONTAINS
several projects. Real case:

```
/Users/miguelacho/SECOP/
├── .claude/                                    <- root marker
├── Instrumentos de control/
└── proyectos/
    ├── radar-licitaciones-secop/
    └── instrumentos-control-documental/
```

The session starts at `SECOP`, and the user says which project to work on
afterwards, in the conversation. Today both projects would share a single
handoff at `SECOP/.baton/HANDOFF.md`: one 6000-character budget for two
unrelated bodies of work, and an injection at startup that is about the other
project half of the time.

`--cwd` does not solve it either. It also walks up, and since the project
folders carry no root marker, it lands back on `SECOP`.

The deeper constraint: **at `SessionStart` the information does not exist yet.**
The hook only has `cwd`. Which project this session is about is decided later,
by the user, in the conversation. Any design that tries to guess it at startup
is guessing.

## What we are building

A subproject is any directory under the root that has its own
`.baton/HANDOFF.md`. They are discovered by scanning, not declared in config.

When a root has subprojects, the session start injects a short INDEX instead of
a document: which projects exist, in what mode, how old. It grants no context
and authorises nothing. When the user says which project, the model runs
`baton.py load <name>`, which delivers that handoff with the same guarantees the
hook would have given it, and marks it as the session's active project.
`/baton` then writes to the active project.

Nothing is guessed from the conversation, and nothing changes for a root that
has no subprojects.

## Non-goals

- Detecting "projects" by any signal other than an existing handoff. No
  `package.json`, no `project-manifest.json`, no nested `.git`. baton lists the
  projects the user decided to track, it does not invent them.
- A registry of projects. Folders get renamed and moved; a registry goes stale
  and the document already is the signal (`is_enabled`, `lib/storage.py:104`).
- Cross-project handoffs, aggregation, or any view over several documents at
  once.
- Making the root's own handoff aware of its subprojects.

## 1. Discovery

New in `lib/storage.py`, sibling of `project_root`:

```python
@dataclass(frozen=True)
class SubProject:
    rel: str        # POSIX relative path from the root: "proyectos/radar"
    name: str       # last segment: "radar"
    path: Path      # absolute

def discover(root, depth=2, max_dirs=400) -> DiscoveryResult
# .projects: list[SubProject] sorted by rel
# .truncated: bool -- the cap was hit, the listing may be incomplete
```

Rules:

- A directory is a subproject when `<dir>/.baton/HANDOFF.md` is a file. Nothing
  else qualifies a directory, and the path convention is irrelevant: loose
  folders at depth 1, grouped under `proyectos/` at depth 2, and both mixed in
  the same root all work identically.
- Breadth-first, levels 1..`depth`, entries sorted at each level so the result
  is stable rather than filesystem-ordered.
- **A found subproject is not descended into.** Its own subprojects are its
  business; this keeps one root from listing grandchildren as siblings.
- Skipped: dotted names, symlinked directories (loop safety), and the fixed list
  `node_modules`, `dist`, `build`, `target`, `vendor`, `__pycache__`, `Library`.
- `max_dirs` bounds the worst case (a root with thousands of children). On hit,
  the scan stops and `truncated` is set, so `doctor` can say so instead of
  leaving a project mysteriously missing.
- Never raises. `OSError` on a directory skips that directory; an error at the
  root returns an empty result. Same rule as the rest of the module: a broken
  scan cannot stop a session from starting.

Depth 2 is the default because it covers the two shapes that actually occur and
costs a few hundred `stat` calls -- less than the log write the hook already
does on every event. Depth 3 would be tens of thousands of calls on every
session start of every project on the machine, and under a cap it would truncate
arbitrarily, which is worse than not looking.

## 2. Session start

The gate in `hooks/baton_hook.py:main` changes: a project is enabled when the
root has its own document **or** discovery found at least one subproject.
Otherwise the hook still returns early, so the hundreds of repos where `/baton`
was never used keep seeing absolute silence. Discovery therefore runs before the
gate, on every event -- `session-start`, `post-compact` and `stop` alike.

Clearing the activation (§4) also happens before the `inject_on` check, not
after: a root whose config drops `startup` from `inject_on` must still not carry
yesterday's active project into today's session.

Four cases at `session-start`, decided by (root has own document) x (subprojects
found):

| root document | subprojects | injected |
|---|---|---|
| yes | no | the document -- **byte for byte what happens today** |
| no | yes | the index |
| yes | yes | the document, then the index appended |
| no | no | nothing; logged as `silent: project not enabled`, as today |

The index:

```
<baton-index root="/Users/miguelacho/SECOP" count="2">

This folder contains several projects with their own handoff. You have NOT
received the context of any of them, and you must NOT open any yet.

  radar-licitaciones-secop         continue · 9 h ago  · proyectos/radar-licitaciones-secop
  instrumentos-control-documental  memory   · 3 d ago  · proyectos/instrumentos-control-documental

When the user says which one they are working on, and only then, run
`baton.py load <name>`: that hands you that handoff with its instructions and
marks it as this session's active project. Until that happens, greet in ONE line
saying which projects are available, and wait.

</baton-index>
```

- Two lines of fixed text per project. Ten projects is 26 lines against a
  200-line ceiling.
- `mode` and `date` come from reading at most `document.HEAD` (4096) bytes of
  each handoff, not the whole file.
- **The index computes no freshness.** Comparing against git costs several
  subprocesses per project and the notice only matters when the context is
  actually used. It is computed in `load`.
- **The index is not a delivery.** `record_delivery` is called by `load`, not
  here; otherwise every startup would inflate the counter of projects the
  session never touched.
- Project names come from directory names, which travel inside cloned repos.
  They go through `output.sanitize`, the closing-tag defence and a length cap,
  exactly like the document body.
- In the mixed case the root document governs the session as it does today;
  loading a subproject replaces the active context. The index goes after the
  document, so the mode instruction still comes first and survives any trim --
  and it is passed to `output.wrap` as part of the FIXED text, not concatenated
  afterwards. Otherwise the wrapper would compute its room without it and the
  two together could cross the 8000-character ceiling, which is the one failure
  the module exists to prevent.
- The `receipt` line reports the new shape, e.g.
  `baton: 2 projects available, none loaded`.

## 3. Loading a project

New subcommand: `baton.py load <name> [--cwd DIR]`.

Name resolution, in order, stopping at the first that yields exactly one match:

1. `.` -- the root itself (the way to target the root explicitly when
   subprojects exist).
2. exact `rel` path.
3. exact `name`, case-insensitive.
4. unique case-insensitive substring of `name`.

Zero matches or more than one: print the candidates, exit `ENVIRONMENT` (3), do
nothing. Ambiguity is never resolved by picking.

On success it prints **the same text the hook would have injected** for that
project: `output.wrap()` with its mode, its freshness notice computed against
its own git, the repeat notice from `record_delivery`, and the budget trim. A
handoff must carry identical guarantees whether it arrived through the hook or
through this command. Then it records the activation.

## 4. Activation

`<root>/.baton/local/active.json`:

```json
{"project": "proyectos/radar-licitaciones-secop", "since": "...Z", "session": "..."}
```

- Written by `load`. `session` comes from `CLAUDE_SESSION_ID` when present and
  is diagnostic only -- the hook's own comment records that it is not guaranteed,
  so nothing depends on it.
- **Cleared by the `session-start` hook when the session starts fresh
  (`startup`, `clear`); preserved when the session continues (`compact`,
  `resume`, `fork`).** The second half is not a detail: clearing on `compact`
  would drop the target exactly when the automatic cycle is about to ask for a
  handoff, which is the moment the cycle exists for.
- Lives one session. A stale activation from yesterday cannot silently absorb
  today's handoff.
- Two concurrent sessions on the same root are a known limit: the second
  `session-start` clears the first session's activation, so the first degrades
  to asking instead of writing to the wrong project. Safe direction.

## 5. Writing

`baton.py context|write|show` take `--project <name>`, resolved by the rules in
§3. Target resolution, in order:

1. `--project` given -> that one. This is also the cold start: the folder has
   no `.baton/` yet, and this argument is what creates it. The argument must
   name a directory that **already exists** under the root; `write` creates
   `.baton/` and the document inside it, never the project folder itself. A
   typo therefore fails with the candidate list instead of quietly starting a
   project in a folder nobody made.
2. an active project -> that one.
3. no subprojects discovered -> the root. This is today's path, unchanged.
4. subprojects exist, none active, none given -> **ask**. Exit `ENVIRONMENT`
   (3), printing the candidates plus `.` for the root, so the model puts one
   question to the user. The conversation is never used to infer the target:
   this is precisely the case where guessing overwrites a good handoff.

`write` always prints the absolute path it wrote to. A wrong target has to be
visible immediately, not three days later.

`/baton`'s `argument-hint` becomes `[memory|continue] [project] [note]`, and the
command doc states that a bare `/baton` uses the active project.

## 6. The automatic cycle

Both hooks resolve their target the same way, and it is a subset of §5: the
active project if there is one, the root otherwise. They never take a
`--project`, because nobody is typing them.

`post-compact` is unchanged except for where it writes: the summary and the
pending flag go to that target's `.baton/local/`, which is also where `stop`
reads the flag back from. Writing them to different places would arm a flag
nobody reads.

`stop` gains one gate before the three it already has: **it only interrupts when
there is a resolvable target** -- an active project, or a root with its own
document. A session that never loaded a project in a root with no document of
its own gets silence, not a question the hook cannot answer on its own. Same
conservative rule the plugin already follows: when in doubt, do not authorise.

When there is an active project, the `reason` text names it, so the model does
not have to work out where to write.

## 7. Configuration

The chain becomes global -> root -> subproject, each overriding the previous:

```
~/.claude/baton.json                    every project
<root>/.claude/baton.json               this root and its subprojects
<subproject>/.claude/baton.json         that subproject only
```

So a global `"language": "es"` keeps applying without being repeated anywhere.

One new key, **read only from the root** because it describes the shape of the
tree, not a project:

```json
{ "discovery": { "depth": 2, "max_dirs": 400 } }
```

Validated like the rest: `depth` an int in 1..4, `max_dirs` an int >= 50,
anything else warns naming the file and falls back to the default. `discovery`
appearing in a subproject config is ignored with a warning.

## 8. Per-project state and freshness

`Paths` is already built from a directory, so building it from the subproject
gives per-project document, history, draft, log, pending flag and lock for free.
Two sessions working on different projects of the same root do not contend: the
locks are different files.

Freshness needs **no change**, and this was verified rather than assumed:
`freshness()` runs `git -C <dir>` with the pathspec `. :(exclude).baton/`
(`lib/gitinfo.py:230`), and git resolves relative pathspecs against its working
directory. Inside a monorepo, a subproject therefore counts only the commits
that touched its own folder, and the exclusion of baton's own files rescopes
itself. That matters: the 0.3.1 bug taught that a notice which always fires is a
notice the model learns to ignore.

## 9. CLI surface

| command | change |
|---|---|
| `load <name>` | new: deliver a project's handoff and activate it |
| `context` | `--project`; header line names the target project |
| `write` | `--project`; creates the subproject on cold start; prints the absolute path |
| `show` | `--project`; with none and several projects, lists them |
| `doctor` | reports root, scan depth, projects found, whether the cap was hit, the active project and its age |

Exit codes are unchanged in meaning. An unresolvable or ambiguous project is
`ENVIRONMENT` (3): the environment is not what the command needs.

## 10. Strings

Every human-visible string added here lives in `templates/en.json` and
`templates/es.json`: the index header and instruction, the per-project line
format, the relative ages ("9 h ago", "3 d ago"), the candidate list, the
"which project?" question and the new `doctor` lines. Nothing in the code, same
as today. The `baton-index` tag name and the config keys stay English in both.

## 11. Compatibility

A current install -- root with a handoff, no subprojects -- behaves exactly as
today. This is a test, not a hope: the existing `test_hook_session_start` and
`test_auto_cycle` suites must keep passing untouched.

The document format does not change; `document.VERSION` stays 1. A subproject's
handoff is an ordinary handoff, which is why opening a session inside the
project folder already works: `.baton` is a root marker, so `project_root` stops
there.

## 12. Testing

Unit:

- discovery: loose at depth 1, grouped at depth 2, mixed, none, root document
  with and without subprojects, symlink not followed, subproject not descended
  into, `max_dirs` cap sets `truncated`, unreadable directory skipped, stable
  order.
- name resolution: exact rel, exact name, case-insensitive, unique substring,
  ambiguous, unknown, `.` for the root.
- target resolution: the four cases of §5, including that the conversation is
  never consulted.
- activation: written by `load`, cleared on `startup`/`clear`, preserved on
  `compact`/`resume`/`fork`.
- index: under the ceiling with 20 projects, sanitised project names, a name
  containing `</baton-index>` cannot close the tag.
- `stop` stays silent with no resolvable target, and names the active project
  when there is one.

Manual acceptance (added to both READMEs): a root with two projects; open a
session and confirm the index arrives and nothing is loaded; `load` one and
confirm the handoff arrives with its freshness; `/baton` and confirm it wrote
inside that project; reopen and confirm the index reflects it. Unit tests do not
see the failures that only appear on a real install -- 0.3.1 established that at
some cost.

## 13. Release

`0.4.0` in `.claude-plugin/plugin.json`, CHANGELOG entry, README and README.es
sections on multi-project roots. The version bump is required for
`claude plugin update` to pick the change up, and a restart is required for the
hooks to reload.
