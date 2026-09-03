# Multi-project roots — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a session opened at a folder that contains several projects see an index of them, load one on demand, and write its handoff into that project instead of into a shared root document.

**Architecture:** A new module `lib/projects.py` answers "which project are we talking about" (discovery, name resolution, activation), leaving `lib/storage.py` as "where one project's files live". The hook and the CLI both resolve a target before doing anything else; everything downstream already works per-directory, so `Paths(target)` is most of the change. Rendering of the index lives in `lib/output.py`, next to the wrapper it has to fit inside.

**Tech Stack:** Python 3 standard library only. `unittest`. No dependencies, in the code or in the tests.

**Spec:** `docs/superpowers/specs/2026-09-03-multi-project-roots-design.md` — read it before Task 1; every task argues from it.

## Global Constraints

- **Stdlib only.** No new dependency in `lib/`, `hooks/`, `scripts/` or `tests/`.
- **Test command:** `bash tests/run.sh` (which is `python3 -m unittest discover -s tests -t .`). A single test: `python3 -m unittest tests.test_projects.TestDiscovery.test_name -v`. There is no pytest in this repo.
- **Temporary projects in tests always live under a path with a space and an accent** — use `tests.helpers.BaseCase`, which already creates `Agentes IA/próyecto de prueba`. The awkward path is the base case, not a separate test.
- **No hook may ever raise.** `hooks/baton_hook.py:main` exits 0 on every path, including `BaseException`. Nothing added in this plan may change that.
- **No user-facing string in the code.** Every new message goes to `templates/en.json` AND `templates/es.json`, under the same key. Config keys, the mode enum and the `baton-index` tag name stay English in both files.
- **Harness ceiling:** 8000 characters / 200 lines (`lib/budget.py:20`). Anything injected has to be measured against it, never estimated.
- **Volatile state only under `.baton/local/`.** The user has one line in `.gitignore` and it must keep being enough.
- **Docstrings and comments in English, and they say WHY, not what.** Match the surrounding files.
- **Conventional Commits, subject in Spanish** (matching this repo's history: `fix: el aviso de frescura saltaba por los propios commits de baton`).
- **Every commit message ends with these two lines, verbatim:**

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
```

- **The full suite must be green before every commit.** It is 216 tests today.

## File Structure

| File | Responsibility |
|---|---|
| `lib/projects.py` (new) | Which project: `SubProject`, `discover()`, `resolve()`, `Target`, activation read/write/clear. Touches disk, never raises. |
| `lib/storage.py` (modify) | Unchanged responsibility. `_read_json`/`_write_json` become public `read_json`/`write_json` because `projects.py` needs them for `active.json`. |
| `lib/output.py` (modify) | Gains `index_block()` and an `index=` parameter on `wrap()`, so the index is counted as fixed text and cannot push the injection over the ceiling. |
| `lib/config.py` (modify) | The `discovery` key, and the global -> root -> subproject chain. |
| `hooks/baton_hook.py` (modify) | Resolves a target before the enabled gate; injects index or document+index; clears activation on a fresh session. |
| `scripts/baton.py` (modify) | `load` subcommand, `--project` on `context`/`write`/`show`, the "which project?" exit, doctor lines. |
| `templates/en.json`, `templates/es.json` (modify) | Every new string. |
| `tests/test_projects.py` (new) | Discovery, resolution, activation. |
| `tests/test_multi_project.py` (new) | The hook and the CLI end to end on a root with two projects. |
| `skills/baton/SKILL.md`, `commands/baton.md`, `README.md`, `README.es.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json` (modify) | Docs and release. |

---

### Task 1: Discovery

**Files:**
- Create: `lib/projects.py`
- Create: `tests/test_projects.py`

**Interfaces:**
- Consumes: `lib/storage.py` (nothing yet in this task).
- Produces:
  - `projects.SubProject(rel: str, name: str, path: Path)` — frozen dataclass. `rel` is the POSIX path relative to the root, `name` its last segment.
  - `projects.Discovery(projects: tuple[SubProject, ...], truncated: bool)` — frozen dataclass, truthy when it has projects.
  - `projects.discover(root, depth=2, max_dirs=400, document_rel=".baton/HANDOFF.md") -> Discovery`
  - `projects.DEFAULT_DEPTH = 2`, `projects.DEFAULT_MAX_DIRS = 400`, `projects.SKIP_NAMES`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_projects.py`:

```python
"""Which project: discovery, name resolution and activation."""
import sys

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import projects  # noqa: E402


class Base(BaseCase):
    def make_project(self, rel):
        """A directory that qualifies: it has its own handoff."""
        d = self.project / rel
        (d / ".baton").mkdir(parents=True, exist_ok=True)
        (d / ".baton" / "HANDOFF.md").write_text(
            "---\nbaton: 1\nmode: memory\ndate: 2026-09-03T10:00:00-05:00\n"
            "branch: main\ncommit: abc1234\n---\n\n## State\nx\n", encoding="utf-8")
        return d


class TestDiscovery(Base):
    def test_no_projects_is_an_empty_discovery(self):
        found = projects.discover(self.project)
        self.assertEqual(found.projects, ())
        self.assertFalse(found)
        self.assertFalse(found.truncated)

    def test_finds_a_loose_folder_at_depth_one(self):
        self.make_project("radar")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects], ["radar"])
        self.assertEqual(found.projects[0].name, "radar")

    def test_finds_a_grouped_folder_at_depth_two(self):
        self.make_project("proyectos/radar")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects], ["proyectos/radar"])
        self.assertEqual(found.projects[0].name, "radar")

    def test_finds_both_shapes_mixed_in_one_root(self):
        self.make_project("suelto")
        self.make_project("proyectos/uno")
        self.make_project("proyectos/dos")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects],
                         ["proyectos/dos", "proyectos/uno", "suelto"])

    def test_depth_three_is_not_reached_by_default(self):
        self.make_project("a/b/c")
        self.assertEqual(projects.discover(self.project).projects, ())
        deeper = projects.discover(self.project, depth=3)
        self.assertEqual([p.rel for p in deeper.projects], ["a/b/c"])

    def test_a_found_project_is_not_descended_into(self):
        self.make_project("radar")
        self.make_project("radar/interno")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects], ["radar"])

    def test_hidden_and_heavy_folders_are_skipped(self):
        self.make_project(".oculto")
        self.make_project("node_modules/paquete")
        self.assertEqual(projects.discover(self.project).projects, ())

    def test_symlinked_directories_are_not_followed(self):
        target = self.make_project("real")
        link = self.project / "enlace"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("this filesystem does not allow symlinks")
        found = projects.discover(self.project)
        self.assertEqual([p.rel for p in found.projects], ["real"])

    def test_the_cap_stops_the_scan_and_says_so(self):
        for i in range(10):
            (self.project / f"vacia{i}").mkdir()
        self.make_project("zzz-ultima")
        found = projects.discover(self.project, max_dirs=3)
        self.assertTrue(found.truncated)

    def test_a_custom_document_path_is_honoured(self):
        d = self.project / "otro"
        (d / "docs").mkdir(parents=True)
        (d / "docs" / "H.md").write_text("x", encoding="utf-8")
        found = projects.discover(self.project, document_rel="docs/H.md")
        self.assertEqual([p.rel for p in found.projects], ["otro"])

    def test_an_unreadable_root_returns_empty_instead_of_raising(self):
        found = projects.discover(self.project / "no-existe")
        self.assertEqual(found.projects, ())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_projects -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.projects'`

- [ ] **Step 3: Write the implementation**

Create `lib/projects.py`:

```python
"""Which project this session is talking about.

`storage.py` answers where one project's files live. This module answers the
question that comes first when the session is opened at a folder holding several
projects: which projects are there, which one did the user name, and which one is
active right now.

A project is a directory with its own handoff. Nothing else qualifies one: no
`package.json`, no nested `.git`, no naming convention. baton lists the projects
someone decided to track, it does not invent them -- and that keeps the rule
identical to the one `storage.is_enabled` already applies one level up.

Same module rule as storage: nothing here raises towards a hook.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Levels below the root that are scanned. 2 covers a loose project folder and
#: one grouping level, which are the shapes that actually occur. Depth 3 would
#: be tens of thousands of stat calls on every session start of every project on
#: the machine, and under a cap it would truncate arbitrarily -- a project
#: missing for no visible reason is worse than one not looked for.
DEFAULT_DEPTH = 2

#: Bounds the worst case: a root with thousands of children.
DEFAULT_MAX_DIRS = 400

#: Never descended into. Dotted names are skipped separately.
SKIP_NAMES = frozenset({
    "node_modules", "dist", "build", "target", "vendor", "__pycache__", "Library",
})

#: The name that means "the root itself" wherever a project is asked for.
ROOT_NAME = "."

DEFAULT_DOCUMENT = ".baton/HANDOFF.md"


@dataclass(frozen=True)
class SubProject:
    rel: str    # POSIX, relative to the root: "proyectos/radar"
    name: str   # last segment: "radar"
    path: Path


@dataclass(frozen=True)
class Discovery:
    projects: tuple = ()
    truncated: bool = False

    def __bool__(self) -> bool:
        return bool(self.projects)


def discover(root, depth: int = DEFAULT_DEPTH, max_dirs: int = DEFAULT_MAX_DIRS,
             document_rel: str = DEFAULT_DOCUMENT) -> Discovery:
    """Directories under `root` that carry their own handoff.

    Breadth-first and sorted at every level, so the result is stable rather than
    filesystem-ordered: an index that reshuffles between sessions reads like
    something changed when nothing did.

    Never raises. An unreadable directory is skipped and the scan carries on: a
    broken scan cannot stop a session from starting.
    """
    root = Path(root)
    found: list = []
    seen = 0
    truncated = False
    level = [root]

    for _ in range(max(int(depth or 0), 0)):
        following: list = []
        for parent in level:
            try:
                entries = sorted(p for p in parent.iterdir() if p.is_dir())
            except OSError:
                continue
            for directory in entries:
                if seen >= max_dirs:
                    truncated = True
                    break
                seen += 1
                if directory.name.startswith(".") or directory.name in SKIP_NAMES:
                    continue
                if directory.is_symlink():
                    continue  # a link can point back up and loop the scan
                try:
                    is_project = (directory / document_rel).is_file()
                except OSError:
                    continue
                if is_project:
                    found.append(SubProject(
                        rel=directory.relative_to(root).as_posix(),
                        name=directory.name, path=directory))
                    continue  # its own subprojects are its business, not the root's
                following.append(directory)
            if truncated:
                break
        if truncated:
            break
        level = following

    return Discovery(tuple(sorted(found, key=lambda p: p.rel)), truncated)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_projects -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Run the whole suite**

Run: `bash tests/run.sh`
Expected: OK, 227 tests (216 + 11).

- [ ] **Step 6: Commit**

```bash
git add lib/projects.py tests/test_projects.py
git commit -F- <<'EOF'
feat: descubrimiento de subproyectos por su propio handoff

Una raiz puede contener varios proyectos. Un subproyecto es cualquier
carpeta con handoff propio: la misma regla que ya decide si un proyecto
esta activo, aplicada un nivel mas abajo. Ni convencion de nombres ni
registro, que se desactualiza en cuanto alguien renombra una carpeta.

Profundidad 2 y tope de carpetas porque el escaneo corre en cada arranque
de cada proyecto del disco: su peor caso tiene que estar acotado.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 2: Name resolution

**Files:**
- Modify: `lib/projects.py`
- Modify: `tests/test_projects.py`

**Interfaces:**
- Consumes: `SubProject`, `Discovery` from Task 1.
- Produces:
  - `projects.Target(root: Path, project: SubProject | None)` — frozen; `.path`, `.rel`, `.label`, `.is_root`.
  - `projects.resolve(root, discovery, name, allow_new=False) -> tuple[Target | None, list[SubProject]]` — a `None` target means unresolved and the list holds the candidates to print.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_projects.py`:

```python
class TestResolve(Base):
    def setUp(self):
        super().setUp()
        self.make_project("proyectos/radar-licitaciones")
        self.make_project("proyectos/instrumentos")
        self.found = projects.discover(self.project)

    def resolve(self, name, **kw):
        return projects.resolve(self.project, self.found, name, **kw)

    def test_dot_means_the_root(self):
        target, candidates = self.resolve(".")
        self.assertTrue(target.is_root)
        self.assertEqual(target.path, self.project)
        self.assertEqual(candidates, [])

    def test_exact_relative_path(self):
        target, _ = self.resolve("proyectos/radar-licitaciones")
        self.assertEqual(target.rel, "proyectos/radar-licitaciones")

    def test_exact_name_ignoring_case(self):
        target, _ = self.resolve("RADAR-licitaciones")
        self.assertEqual(target.rel, "proyectos/radar-licitaciones")

    def test_unique_substring(self):
        target, _ = self.resolve("radar")
        self.assertEqual(target.rel, "proyectos/radar-licitaciones")

    def test_an_ambiguous_substring_resolves_to_nothing(self):
        self.make_project("proyectos/radar-otro")
        self.found = projects.discover(self.project)
        target, candidates = self.resolve("radar")
        self.assertIsNone(target)
        self.assertEqual(len(candidates), 2)

    def test_an_unknown_name_lists_every_project(self):
        target, candidates = self.resolve("nada-que-ver")
        self.assertIsNone(target)
        self.assertEqual(len(candidates), 2)

    def test_no_name_resolves_to_nothing(self):
        target, candidates = self.resolve(None)
        self.assertIsNone(target)
        self.assertEqual(len(candidates), 2)

    def test_allow_new_accepts_an_existing_folder_without_handoff(self):
        (self.project / "proyectos" / "nuevo").mkdir()
        target, _ = self.resolve("proyectos/nuevo", allow_new=True)
        self.assertEqual(target.rel, "proyectos/nuevo")

    def test_allow_new_rejects_a_folder_that_does_not_exist(self):
        target, candidates = self.resolve("proyectos/typo", allow_new=True)
        self.assertIsNone(target)
        self.assertEqual(len(candidates), 2)

    def test_allow_new_cannot_escape_the_root(self):
        # Absolute paths and .. are how a typo turns into writing outside the
        # project. The same rule config.py applies to `document`.
        for escape in ("../fuera", "/tmp", "proyectos/../../fuera"):
            with self.subTest(escape=escape):
                target, _ = self.resolve(escape, allow_new=True)
                self.assertIsNone(target)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_projects.TestResolve -v`
Expected: FAIL — `AttributeError: module 'lib.projects' has no attribute 'resolve'`

- [ ] **Step 3: Write the implementation**

Append to `lib/projects.py`:

```python
@dataclass(frozen=True)
class Target:
    """A resolved destination: the root itself, or one subproject."""
    root: Path
    project: SubProject | None = None

    @property
    def is_root(self) -> bool:
        return self.project is None

    @property
    def path(self) -> Path:
        return self.root if self.project is None else self.project.path

    @property
    def rel(self) -> str:
        return ROOT_NAME if self.project is None else self.project.rel

    @property
    def label(self) -> str:
        return ROOT_NAME if self.project is None else self.project.name


def _inside(root: Path, candidate: Path) -> bool:
    """`candidate` really is under `root`, with symlinks and `..` resolved."""
    try:
        return candidate.resolve(strict=False).is_relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False


def resolve(root, discovery: Discovery, name, allow_new: bool = False):
    """Turn a name typed by a human into a Target.

    Returns `(target, candidates)`. A None target means the caller must not pick:
    the candidates are printed and the command stops. Ambiguity is never resolved
    by choosing, because the thing being chosen is which handoff gets
    overwritten.

    `allow_new` is the cold start: `write --project` may name a directory that
    does not have a handoff YET. It must already exist -- baton creates `.baton/`
    inside a folder, never the project folder itself, so a typo cannot found a
    project in a directory nobody made.
    """
    root = Path(root)
    everything = list(discovery.projects)
    if name is None:
        return None, everything

    key = str(name).strip()
    if key in (ROOT_NAME, ""):
        return Target(root), []

    for matches in (
        [p for p in everything if p.rel == key],
        [p for p in everything if p.name.casefold() == key.casefold()],
        [p for p in everything if key.casefold() in p.name.casefold()],
    ):
        if len(matches) == 1:
            return Target(root, matches[0]), []
        if len(matches) > 1:
            return None, matches

    if allow_new:
        candidate = root / key
        if candidate.is_dir() and _inside(root, candidate):
            return Target(root, SubProject(
                rel=candidate.relative_to(root).as_posix(),
                name=candidate.name, path=candidate)), []

    return None, everything
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_projects -v`
Expected: PASS, 21 tests.

- [ ] **Step 5: Run the whole suite and commit**

Run: `bash tests/run.sh` (expected OK, 237 tests), then:

```bash
git add lib/projects.py tests/test_projects.py
git commit -F- <<'EOF'
feat: resolucion de nombre de proyecto sin adivinar

Ante un nombre ambiguo devuelve los candidatos en vez de elegir: lo que
se esta eligiendo es que handoff se sobrescribe, y equivocarse ahi borra
trabajo de otra sesion.

allow_new exige que la carpeta exista. baton crea .baton/ dentro de una
carpeta, nunca la carpeta del proyecto, para que un typo no funde un
proyecto en un directorio que nadie hizo.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 3: Activation

**Files:**
- Modify: `lib/storage.py` (`_read_json`/`_write_json` -> public `read_json`/`write_json`)
- Modify: `lib/projects.py`
- Modify: `tests/test_projects.py`

**Interfaces:**
- Consumes: `Target`, `SubProject`, `Discovery`.
- Produces:
  - `storage.read_json(path) -> dict` and `storage.write_json(path, data) -> None` (creates parents, never raises).
  - `projects.active_path(root) -> Path` — `<root>/.baton/local/active.json`
  - `projects.read_active(root, discovery) -> SubProject | None`
  - `projects.set_active(root, project, session="") -> None`
  - `projects.clear_active(root) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_projects.py`:

```python
class TestActivation(Base):
    def setUp(self):
        super().setUp()
        self.make_project("proyectos/radar")
        self.found = projects.discover(self.project)
        self.radar = self.found.projects[0]

    def test_nothing_is_active_to_begin_with(self):
        self.assertIsNone(projects.read_active(self.project, self.found))

    def test_set_then_read(self):
        projects.set_active(self.project, self.radar, session="s-1")
        active = projects.read_active(self.project, self.found)
        self.assertEqual(active.rel, "proyectos/radar")

    def test_it_lives_under_baton_local(self):
        projects.set_active(self.project, self.radar)
        self.assertEqual(projects.active_path(self.project),
                         self.project / ".baton" / "local" / "active.json")

    def test_clear_removes_it(self):
        projects.set_active(self.project, self.radar)
        projects.clear_active(self.project)
        self.assertIsNone(projects.read_active(self.project, self.found))

    def test_an_activation_pointing_at_a_vanished_folder_is_ignored(self):
        # Folders get renamed between sessions. A stale pointer must not send a
        # handoff somewhere nobody is looking.
        projects.set_active(self.project, self.radar)
        empty = projects.Discovery()
        self.assertIsNone(projects.read_active(self.project, empty))

    def test_corrupt_state_reads_as_nothing_active(self):
        path = projects.active_path(self.project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(projects.read_active(self.project, self.found))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_projects.TestActivation -v`
Expected: FAIL — `AttributeError: module 'lib.projects' has no attribute 'read_active'`

- [ ] **Step 3: Make the JSON helpers public in `lib/storage.py`**

Rename `_read_json` -> `read_json` and change `_write_json(path, data, paths)` -> `write_json(path, data)`, which creates its own parent directory instead of taking a `Paths`:

```python
def read_json(path) -> dict:
    """Any garbage -- invalid JSON, valid JSON that is not an object, an empty
    file -- reads back as {}. State files can be touched by an editor, a merge
    or a session killed mid-write, and none of that may raise towards a hook."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path, data: dict) -> None:
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
```

Update the four call sites inside `storage.py` (`record_delivery`, `arm_pending`, `has_pending`, `consume_pending`): `_read_json(paths.deliveries)` -> `read_json(paths.deliveries)`, `_write_json(paths.pending, data, paths)` -> `write_json(paths.pending, data)`. Nothing outside `storage.py` referenced them.

- [ ] **Step 4: Write the activation functions**

Append to `lib/projects.py`:

```python
def active_path(root) -> Path:
    return Path(root) / ".baton" / "local" / "active.json"


def read_active(root, discovery: Discovery):
    """The active subproject, or None.

    It is validated against what exists right now instead of being trusted: a
    folder renamed between sessions would otherwise send the handoff to a path
    nobody is looking at.
    """
    from lib import storage
    rel = storage.read_json(active_path(root)).get("project")
    if not rel:
        return None
    for project in discovery.projects:
        if project.rel == rel:
            return project
    return None


def set_active(root, project: SubProject, session: str = "") -> None:
    """`session` is diagnostic only. `CLAUDE_SESSION_ID` is not guaranteed to be
    there, so nothing may depend on it."""
    from lib import storage
    storage.write_json(active_path(root), {
        "project": project.rel, "since": storage.now_utc(), "session": session or "",
    })


def clear_active(root) -> None:
    try:
        active_path(root).unlink(missing_ok=True)
    except OSError:
        pass
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_projects -v` (expected PASS, 27 tests), then `bash tests/run.sh` (expected OK, 243 tests).

- [ ] **Step 6: Commit**

```bash
git add lib/projects.py lib/storage.py tests/test_projects.py
git commit -F- <<'EOF'
feat: proyecto activo de la sesion en .baton/local/active.json

La activacion se valida contra lo que existe ahora en vez de confiarse:
una carpeta renombrada entre sesiones mandaria el handoff a una ruta que
nadie mira.

read_json/write_json pasan a publicas en storage porque projects.py las
necesita; no habia ningun uso fuera del modulo.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 4: Rendering the index

**Files:**
- Modify: `lib/projects.py` (reading each handoff's head)
- Modify: `lib/output.py`
- Modify: `templates/en.json`, `templates/es.json`
- Modify: `tests/test_output.py`

**Interfaces:**
- Consumes: `SubProject`, `document.read_mode`, `document.read_fields`, `document.HEAD`, `budget.trim_to_lines`.
- Produces:
  - `projects.Card(name: str, rel: str, mode: str, date: str)` and `projects.describe(project, document_rel) -> Card`
  - `output.index_block(root, cards, strings, truncated=False) -> str`
  - `output.wrap(..., index: str = "")` — the index travels inside the wrapper's fixed text.

- [ ] **Step 1: Add the strings**

In `templates/en.json`, a new top-level `"index"` object:

```json
"index": {
  "tag": "baton-index",
  "header": "This folder contains several projects with their own handoff. You have NOT received the context of any of them, and you must NOT open any yet.",
  "line": "  {name}  {mode} · {age} · {rel}",
  "footer": "When the user says which one they are working on, and only then, run `baton.py load <name>`: that hands you that handoff with its instructions and marks it as this session's active project. Until that happens, greet in ONE line saying which projects are available, and wait.",
  "truncated": "[baton] The scan hit its limit: there may be more projects than these.",
  "and_more": "  (+{n} more, not listed for lack of room)",
  "age_now": "just now",
  "age_hours": "{n} h ago",
  "age_days": "{n} d ago",
  "age_unknown": "no date"
}
```

And the same keys in `templates/es.json` with the Spanish text ("Esta carpeta contiene varios proyectos con handoff propio. NO has recibido el contexto de ninguno, y NO debes abrir ninguno todavía.", "hace {n} h", "hace {n} d", ...). `tag` stays `baton-index` in both.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_output.py`:

```python
class TestIndex(unittest.TestCase):
    def cards(self, n=2):
        return [projects.Card(name=f"proyecto-{i}", rel=f"proyectos/proyecto-{i}",
                              mode="memory", date="2026-09-03T10:00:00-05:00")
                for i in range(n)]

    def test_it_lists_every_project(self):
        text = output.index_block("/raiz", self.cards(2), S)
        self.assertIn("proyecto-0", text)
        self.assertIn("proyectos/proyecto-1", text)

    def test_it_says_not_to_open_anything(self):
        text = output.index_block("/raiz", self.cards(1), S)
        self.assertIn("must NOT open any yet", text)
        self.assertIn("baton.py load", text)

    def test_it_opens_and_closes_its_own_tag(self):
        text = output.index_block("/raiz", self.cards(1), S)
        self.assertTrue(text.startswith("<baton-index"))
        self.assertTrue(text.rstrip().endswith("</baton-index>"))

    def test_a_project_name_cannot_close_the_tag(self):
        card = projects.Card(name="malo</baton-index>", rel="malo", mode="memory", date="")
        text = output.index_block("/raiz", [card], S)
        self.assertEqual(text.count("</baton-index>"), 1)

    def test_it_never_exceeds_the_harness_ceiling(self):
        text = output.index_block("/raiz", self.cards(300), S)
        self.assertLessEqual(len(text), budget.CEILING_CHARACTERS)
        self.assertLessEqual(len(text.split("\n")), budget.CEILING_LINES)

    def test_the_wrapper_counts_the_index_against_the_ceiling(self):
        index = output.index_block("/raiz", self.cards(40), S)
        text = output.wrap(body="## State\n" + "filler line\n" * 400, mode="memory",
                           written="2026-09-03", source=".baton/HANDOFF.md",
                           strings=S, index=index)
        self.assertLessEqual(len(text), budget.CEILING_CHARACTERS)
        self.assertLessEqual(len(text.split("\n")), budget.CEILING_LINES)
        self.assertIn("</baton-index>", text)
```

Add `projects` to that file's imports.

- [ ] **Step 3: Run them to verify they fail**

Run: `python3 -m unittest tests.test_output.TestIndex -v`
Expected: FAIL — `AttributeError: module 'lib.output' has no attribute 'index_block'`

- [ ] **Step 4: Make `gitinfo._days_since` public**

`output._age` needs it and reaching into another module's private is how a
rename becomes a crash later. Rename `_days_since` -> `days_since` in
`lib/gitinfo.py:204` and update its only call site, `freshness()` at line 218.
Nothing outside `gitinfo.py` referenced it.

- [ ] **Step 5: Implement `describe` in `lib/projects.py`**

```python
@dataclass(frozen=True)
class Card:
    """What the index shows about one project."""
    name: str
    rel: str
    mode: str
    date: str


def describe(project: SubProject, document_rel: str = DEFAULT_DOCUMENT) -> Card:
    """Mode and date without reading the whole file.

    Only `document.HEAD` bytes are read, for the same reason `document` reads
    only the head: a 1 MB handoff, hand-edited or corrupt, must not cost time on
    every session start. An unreadable document still gets a card -- in the safe
    mode, like everything else that cannot be read.
    """
    from lib import document
    try:
        with open(project.path / document_rel, encoding="utf-8", errors="replace") as fh:
            head = fh.read(document.HEAD)
    except OSError:
        head = ""
    return Card(name=project.name, rel=project.rel,
                mode=document.read_mode(head), date=document.read_fields(head).get("date", ""))
```

- [ ] **Step 6: Implement `index_block` and the `index=` parameter in `lib/output.py`**

```python
#: A project name is a directory name, and directory names travel inside cloned
#: repos. Same treatment as the document body, plus a cap: a 300-character name
#: would push the listing out of the budget on its own.
MAX_NAME = 60


def _age(date: str, strings: dict) -> str:
    from lib import gitinfo
    days = gitinfo._days_since(date)
    if days is None:
        return strings["index"]["age_unknown"]
    if days >= 1:
        return strings["index"]["age_days"].format(n=int(days))
    hours = int(days * 24)
    return (strings["index"]["age_now"] if hours < 1
            else strings["index"]["age_hours"].format(n=hours))


def index_block(root, cards, strings=None, truncated: bool = False) -> str:
    """The index injected when the root holds several projects.

    It grants nothing. Receiving a list of what exists is not receiving context,
    and it is certainly not authorisation to work: that is the same decision the
    memory mode makes, applied one level up.
    """
    s = strings or load_strings()
    i = s["index"]
    tag = i["tag"]

    lines = []
    for card in cards:
        name = sanitize(card.name)[:MAX_NAME]
        lines.append(i["line"].format(name=name, mode=card.mode,
                                      age=_age(card.date, s), rel=sanitize(card.rel)[:200]))

    head = [f'<{tag} root="{sanitize(str(root))}" count="{len(cards)}">', "",
            i["header"], ""]
    tail = ["", i["footer"], ""] + ([i["truncated"], ""] if truncated else []) + [f"</{tag}>"]
    fixed = "\n".join(head + tail) + "\n"

    room_chars = budget.CEILING_CHARACTERS - len(fixed) - len(i["and_more"]) - 2
    room_lines = budget.CEILING_LINES - len(fixed.split("\n")) - 2
    shown, cut = budget.trim_to_lines("\n".join(lines), room_chars, room_lines)
    body = [shown.rstrip("\n")]
    if cut:
        body.append(i["and_more"].format(n=len(lines) - len(shown.rstrip("\n").split("\n"))))

    return _disable_closing_tag("\n".join(head + body + tail), tag)
```

In `wrap()`, add the parameter and put the index inside the fixed text so the
trim accounts for it:

```python
def wrap(body, mode, written, source, freshness_notice="", repeat=None,
         strings=None, index="") -> str:
    ...
    tail = [s["document_close"], f"</{tag}>"]
    if index:
        # Inside `tail`, not concatenated by the caller: `fixed` is what decides
        # how much room the document gets, and an index added afterwards would
        # be room nobody measured.
        tail += ["", index]
```

The existing `fixed = "\n".join(head + [s["document_open"]] + tail) + "\n"` then
counts it with no further change.

- [ ] **Step 7: Run the tests and the suite**

Run: `python3 -m unittest tests.test_output -v`, then `bash tests/run.sh`.
Expected: OK, 249 tests.

- [ ] **Step 8: Commit**

```bash
git add lib/output.py lib/projects.py lib/gitinfo.py templates/en.json templates/es.json tests/test_output.py
git commit -F- <<'EOF'
feat: bloque de indice de proyectos, medido contra el techo del harness

El indice no concede nada: recibir una lista de lo que existe no es
recibir contexto, y menos aun permiso para trabajar. Es la decision del
modo memoria, un nivel mas arriba.

Va dentro del texto fijo de wrap() y no concatenado despues, porque es
`fixed` quien decide cuanto sitio le queda al documento: un indice sumado
al final seria sitio que nadie midio, y el techo de 8000 es justo lo que
este modulo existe para no cruzar.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 5: Configuration

**Files:**
- Modify: `lib/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `projects.DEFAULT_DEPTH`, `projects.DEFAULT_MAX_DIRS`.
- Produces: `config.load(root, global_path=None, parent=None) -> Config` with a `discovery` key: `{"depth": int, "max_dirs": int}`. `parent` is the root's directory when loading a subproject's config.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py` (follow the file's existing helper for writing a config; it uses `global_path=` so tests never depend on a real HOME):

```python
class TestDiscoveryKey(BaseCase):
    def write_cfg(self, where, data):
        (where / ".claude").mkdir(parents=True, exist_ok=True)
        (where / ".claude" / "baton.json").write_text(json.dumps(data), encoding="utf-8")

    def test_the_default_is_depth_two(self):
        cfg = config.load(self.project, global_path=self.project / "nope.json")
        self.assertEqual(cfg["discovery"]["depth"], 2)
        self.assertEqual(cfg["discovery"]["max_dirs"], 400)

    def test_the_root_can_deepen_it(self):
        self.write_cfg(self.project, {"discovery": {"depth": 3}})
        cfg = config.load(self.project, global_path=self.project / "nope.json")
        self.assertEqual(cfg["discovery"]["depth"], 3)
        self.assertEqual(cfg["discovery"]["max_dirs"], 400)

    def test_an_absurd_depth_warns_and_falls_back(self):
        self.write_cfg(self.project, {"discovery": {"depth": 99}})
        cfg = config.load(self.project, global_path=self.project / "nope.json")
        self.assertEqual(cfg["discovery"]["depth"], 2)
        self.assertTrue(any("depth" in w for w in cfg.warnings))

    def test_a_subproject_inherits_the_root_and_overrides_language(self):
        sub = self.project / "proyectos" / "radar"
        sub.mkdir(parents=True)
        self.write_cfg(self.project, {"language": "es", "history_max": 3})
        self.write_cfg(sub, {"history_max": 5})
        cfg = config.load(sub, global_path=self.project / "nope.json", parent=self.project)
        self.assertEqual(cfg["language"], "es")
        self.assertEqual(cfg["history_max"], 5)

    def test_discovery_in_a_subproject_is_ignored_with_a_warning(self):
        sub = self.project / "proyectos" / "radar"
        sub.mkdir(parents=True)
        self.write_cfg(self.project, {"discovery": {"depth": 3}})
        self.write_cfg(sub, {"discovery": {"depth": 1}})
        cfg = config.load(sub, global_path=self.project / "nope.json", parent=self.project)
        self.assertEqual(cfg["discovery"]["depth"], 3)
        self.assertTrue(any("discovery" in w for w in cfg.warnings))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_config.TestDiscoveryKey -v`
Expected: FAIL — `KeyError: 'discovery'`

- [ ] **Step 3: Implement**

In `DEFAULTS`, after `"cooldown_minutes"`:

```python
    # How far down a root is scanned for projects with their own handoff. Read
    # only from the root: it describes the shape of the tree, not a project.
    "discovery": {"depth": projects.DEFAULT_DEPTH, "max_dirs": projects.DEFAULT_MAX_DIRS},
```

(import `projects` at the top; `lib/projects.py` imports nothing from `config`,
so there is no cycle.)

In `_merge`, alongside the `limits` branch:

```python
        elif key == "discovery" and isinstance(value, dict):
            for name, number in value.items():
                if name not in DEFAULTS["discovery"]:
                    warnings.append(f"{path.name}: unknown key 'discovery.{name}'; ignoring it")
                elif name == "depth" and not (_valid_int(number, 1) and number <= 4):
                    warnings.append(f"{path.name}: 'discovery.depth' must be an integer "
                                    f"between 1 and 4; using {DEFAULTS['discovery']['depth']}")
                elif name == "max_dirs" and not _valid_int(number, 50):
                    warnings.append(f"{path.name}: 'discovery.max_dirs' must be an integer "
                                    f">= 50; using {DEFAULTS['discovery']['max_dirs']}")
                else:
                    out["discovery"][name] = number
```

Add `"discovery"` to the `dict(v)` copy already done at the top of `_merge` (it
copies any dict value, so nothing to change there), and extend `load`:

```python
def load(root, global_path=None, parent=None) -> Config:
    """Defaults -> global -> root -> project. The most specific one wins.

    `parent` is the root's directory when `root` is a subproject of it. The
    chain exists so a global `language` keeps applying without being repeated in
    every project folder.

    `discovery` is the exception: it is a property of the tree's shape, so only
    the root gets to set it, and a subproject trying to is told so instead of
    being silently ignored.
    """
    warnings: list = []
    data = dict(DEFAULTS)
    data["limits"] = dict(DEFAULTS["limits"])
    data["discovery"] = dict(DEFAULTS["discovery"])
    globals_ = Path(global_path) if global_path else default_global_path()

    layers = [globals_]
    if parent is not None and Path(parent) != Path(root):
        layers.append(Path(parent) / ".claude" / "baton.json")
    layers.append(Path(root) / ".claude" / "baton.json")

    for i, path in enumerate(layers):
        raw = _read(path, warnings)
        if not raw:
            continue
        is_project_layer = (parent is not None and i == len(layers) - 1
                            and Path(parent) != Path(root))
        if is_project_layer and "discovery" in raw:
            warnings.append(f"{path.name}: 'discovery' is only read from the root; ignoring it")
            raw = {k: v for k, v in raw.items() if k != "discovery"}
        data = _merge(data, raw, path, warnings)
    return Config(data, warnings)
```

- [ ] **Step 4: Run the tests and the suite, then commit**

Run: `python3 -m unittest tests.test_config -v`, then `bash tests/run.sh` (expected OK, 254 tests).

```bash
git add lib/config.py tests/test_config.py
git commit -F- <<'EOF'
feat: clave discovery y cadena global -> raiz -> subproyecto

La cadena existe para que un language global siga aplicando sin
repetirlo en cada carpeta de proyecto.

discovery solo se lee de la raiz porque describe la forma del arbol, no
un proyecto; a un subproyecto que lo intente se le dice, en vez de
ignorarlo en silencio.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 6: The hook at session start

**Files:**
- Modify: `hooks/baton_hook.py`
- Create: `tests/test_multi_project.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: the injection contract of §2 of the spec. No new public function outside the hook.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_multi_project.py`:

```python
"""A root that holds several projects: what the session receives, and where the
handoff ends up."""
import json
import sys

from tests.helpers import REPO_ROOT, BaseCase

sys.path.insert(0, str(REPO_ROOT))
from lib import document, output, projects, storage  # noqa: E402

S = output.load_strings("en")


class Base(BaseCase):
    def handoff(self, where, mode="memory", body="## State\nx\n"):
        text = document.compose(body=body, mode=mode, date="2026-09-03T10:00:00-05:00",
                                branch="main", commit="abc1234",
                                context="- branch `main`, working tree clean", strings=S)
        paths = storage.Paths(where)
        paths.document.parent.mkdir(parents=True, exist_ok=True)
        paths.document.write_text(text, encoding="utf-8")
        return where

    def sub(self, rel, **kw):
        d = self.project / rel
        d.mkdir(parents=True, exist_ok=True)
        return self.handoff(d, **kw)

    def start(self, source="startup", **extra):
        return self.run_hook("session-start",
                             self.payload("SessionStart", source=source, **extra))

    def context(self, out):
        return out["hookSpecificOutput"]["additionalContext"]


class TestSessionStart(Base):
    def test_a_root_with_no_document_and_no_projects_stays_silent(self):
        rc, out, _ = self.start()
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_a_normal_project_is_unchanged(self):
        self.handoff(self.project, body="## State\ncanary xylophone-7731\n")
        _, out, _ = self.start()
        text = self.context(out)
        self.assertIn("xylophone-7731", text)
        self.assertNotIn("baton-index", text)

    def test_two_projects_and_no_root_document_inject_the_index(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        _, out, _ = self.start()
        text = self.context(out)
        self.assertIn("<baton-index", text)
        self.assertIn("radar", text)
        self.assertIn("instrumentos", text)
        self.assertIn("baton.py load", text)

    def test_the_index_does_not_carry_any_project_body(self):
        self.sub("proyectos/radar", body="## State\ncanary xylophone-7731\n")
        text = self.context(self.start()[1])
        self.assertNotIn("xylophone-7731", text)

    def test_the_mixed_case_carries_the_root_document_and_the_index(self):
        self.handoff(self.project, body="## State\ncanary xylophone-7731\n")
        self.sub("proyectos/radar")
        text = self.context(self.start()[1])
        self.assertIn("xylophone-7731", text)
        self.assertIn("<baton-index", text)
        self.assertLess(text.index("MEMORY MODE"), text.index("<baton-index"),
                        "the mode instruction has to come first: it survives any trim")

    def test_the_receipt_names_how_many_projects_are_available(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        _, out, _ = self.start()
        self.assertIn("2 project", out["systemMessage"])
        self.assertIn("none loaded", out["systemMessage"])

    def test_a_fresh_session_clears_the_active_project(self):
        radar = self.sub("proyectos/radar")
        found = projects.discover(self.project)
        projects.set_active(self.project, found.projects[0], session="old")
        self.start(source="startup")
        self.assertIsNone(projects.read_active(self.project, found))

    def test_a_compaction_preserves_the_active_project(self):
        # Clearing here would drop the target exactly when the automatic cycle
        # is about to ask for the handoff.
        self.sub("proyectos/radar")
        found = projects.discover(self.project)
        projects.set_active(self.project, found.projects[0], session="s")
        self.start(source="compact")
        self.assertIsNotNone(projects.read_active(self.project, found))

    def test_the_activation_is_cleared_even_when_injection_is_disabled(self):
        self.sub("proyectos/radar")
        (self.project / ".claude").mkdir(exist_ok=True)
        (self.project / ".claude" / "baton.json").write_text(
            json.dumps({"inject_on": ["resume"]}), encoding="utf-8")
        found = projects.discover(self.project)
        projects.set_active(self.project, found.projects[0], session="old")
        self.start(source="startup")
        self.assertIsNone(projects.read_active(self.project, found))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_multi_project -v`
Expected: FAIL — the index tests get `None` (silence), because the enabled gate returns early.

- [ ] **Step 3: Implement in `hooks/baton_hook.py`**

In `main()`, between resolving the config and the enabled gate:

```python
        cfg = config.load(root)
        paths = storage.Paths(root, document_rel=cfg["document"])
        found = projects.discover(root, depth=cfg["discovery"]["depth"],
                                  max_dirs=cfg["discovery"]["max_dirs"],
                                  document_rel=cfg["document"])

        # Before the inject_on filter, not after: a root whose config drops
        # `startup` must still not carry yesterday's active project into today.
        if event == "session-start" and (entry.get("source") or "startup") in ("startup", "clear"):
            projects.clear_active(root)

        if not paths.document.is_file() and not found.projects:
            storage.log_event(paths, event=event, result="silent: project not enabled")
            return 0

        payload, result = handler(entry, paths, cfg, root, found)
```

Add `projects` to the imports. Change the three handler signatures to
`(entry, paths, cfg, root, found)` and, in `_session_start`, build the index:

```python
def _session_start(entry, paths, cfg, root, found) -> tuple[dict, str]:
    """Inject the handoff, the index, or both."""
    source = entry.get("source") or "startup"
    if source not in cfg["inject_on"]:
        return {}, f"silent: '{source}' is not in inject_on"

    strings = output.load_strings(cfg["language"])
    index = ""
    if found.projects:
        cards = [projects.describe(p, cfg["document"]) for p in found.projects]
        index = output.index_block(root, cards, strings, truncated=found.truncated)

    if not paths.document.is_file():
        payload = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                          "additionalContext": index}}
        if cfg["receipt"]:
            payload["systemMessage"] = (
                f"baton: {len(found.projects)} project(s) available, none loaded")
        return payload, f"index injected: {len(found.projects)} projects"

    # ... the existing body, unchanged, with `index=index` passed to output.wrap
```

and in the existing branch add `index=index` to the `output.wrap(...)` call plus
the count to the receipt when `found.projects`.

- [ ] **Step 4: Run the tests and the suite**

Run: `python3 -m unittest tests.test_multi_project -v`, then `bash tests/run.sh`.
Expected: OK. **`test_hook_session_start.py` and `test_hook_contract.py` must pass untouched** — if either needed editing, the compatibility promise of spec §11 broke and the change is wrong.

- [ ] **Step 5: Commit**

```bash
git add hooks/baton_hook.py tests/test_multi_project.py
git commit -F- <<'EOF'
feat: el arranque inyecta el indice cuando la raiz tiene varios proyectos

El escaneo corre antes de la puerta de "proyecto activo", porque una
raiz sin documento propio nunca llegaria a descubrir nada si el return
temprano se queda donde estaba.

La activacion se limpia antes del filtro inject_on: una raiz que quite
startup de su config seguiria arrastrando el proyecto activo de ayer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 7: The automatic cycle

**Files:**
- Modify: `hooks/baton_hook.py`
- Modify: `tests/test_multi_project.py`

**Interfaces:**
- Consumes: `projects.read_active`, Task 6's handler signature.
- Produces: `_hook_target(root, paths, cfg, found) -> storage.Paths | None` inside the hook — the active project's paths, the root's, or None.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_multi_project.py`:

```python
class TestAutomaticCycle(Base):
    def compact(self, **extra):
        return self.run_hook("post-compact", self.payload(
            "PostCompact", compact_summary="a summary", trigger="auto", **extra))

    def stop(self, **extra):
        return self.run_hook("stop", self.payload("Stop", stop_hook_active=False, **extra))

    def activate(self, rel):
        found = projects.discover(self.project)
        target = [p for p in found.projects if p.rel == rel][0]
        projects.set_active(self.project, target, session="test-session")
        return self.project / rel

    def test_the_summary_lands_in_the_active_project(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        radar = self.activate("proyectos/radar")
        self.compact()
        self.assertTrue(any((radar / ".baton" / "local" / "auto").glob("summary-*.md")))
        self.assertFalse((self.project / ".baton" / "local" / "auto").exists())

    def test_stop_asks_and_names_the_active_project(self):
        self.sub("proyectos/radar")
        self.activate("proyectos/radar")
        self.compact()
        _, out, _ = self.stop()
        self.assertEqual(out["decision"], "block")
        self.assertIn("radar", out["reason"])

    def test_with_no_active_project_and_no_root_document_it_stays_quiet(self):
        # Interrupting with a question the hook cannot answer on its own is
        # worse than saying nothing.
        self.sub("proyectos/radar")
        self.compact()
        _, out, _ = self.stop()
        self.assertIsNone(out)

    def test_a_single_project_root_still_gets_asked(self):
        self.handoff(self.project)
        self.compact()
        _, out, _ = self.stop()
        self.assertEqual(out["decision"], "block")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_multi_project.TestAutomaticCycle -v`
Expected: FAIL — the summary lands in the root's `.baton/local/auto`, not in the project's.

- [ ] **Step 3: Implement**

In `hooks/baton_hook.py`:

```python
def _hook_target(root, paths, cfg, found):
    """Where an unattended hook writes: the active project, else the root.

    Returns None when neither exists. Both hooks have to agree on this, because
    `post-compact` arms the flag that `stop` reads back: pointing them at
    different directories would arm a flag nobody reads.
    """
    active = projects.read_active(root, found)
    if active is not None:
        return storage.Paths(active.path, document_rel=cfg["document"]), active.name
    if paths.document.is_file():
        return paths, ""
    return None, ""
```

`_post_compact` and `_stop` start by calling it and return silence when it is
None:

```python
def _post_compact(entry, paths, cfg, root, found) -> tuple[dict, str]:
    target, _ = _hook_target(root, paths, cfg, found)
    if target is None:
        return {}, "silent: no target for the summary"
    storage.save_summary(target, entry.get("compact_summary") or "",
                         trigger=entry.get("trigger") or "auto")
    storage.arm_pending(target, entry.get("session_id") or "")
    return {}, "summary saved, handoff pending"


def _stop(entry, paths, cfg, root, found) -> tuple[dict, str]:
    if entry.get("stop_hook_active"):
        return {}, "silent: already inside a blocked Stop"
    target, label = _hook_target(root, paths, cfg, found)
    if target is None:
        return {}, "silent: no resolvable target"
    if not storage.has_pending(target, cfg["cooldown_minutes"]):
        return {}, "silent: nothing pending"
    storage.consume_pending(target)
    ...
```

and the `reason` text gains, when `label`, a sentence naming the project so the
model does not have to work out where to write: `f"The active project is
`{label}`; the handoff goes there."`

- [ ] **Step 4: Run the tests and the suite**

Run: `python3 -m unittest tests.test_multi_project -v`, then `bash tests/run.sh`.
Expected: OK. `tests/test_auto_cycle.py` must pass untouched.

- [ ] **Step 5: Commit**

```bash
git add hooks/baton_hook.py tests/test_multi_project.py
git commit -F- <<'EOF'
feat: el ciclo automatico escribe en el proyecto activo, o calla

Los dos hooks resuelven el mismo destino porque post-compact arma la
bandera que stop lee: apuntarlos a directorios distintos armaria una
bandera que nadie lee.

Sin destino resoluble, stop se queda callado. Interrumpir con una
pregunta que el hook no puede responder solo es peor que no decir nada,
y es el mismo criterio conservador del resto del plugin.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 8: `baton.py load`

**Files:**
- Modify: `scripts/baton.py`
- Modify: `templates/en.json`, `templates/es.json`
- Modify: `tests/test_multi_project.py`

**Interfaces:**
- Consumes: `projects.resolve`, `projects.set_active`, `output.wrap`, `gitinfo.freshness`, `storage.record_delivery`.
- Produces: `baton.py load <name> [--cwd DIR]` — prints the wrapped handoff on stdout, exit 0; prints candidates on stderr, exit 3 (`ENVIRONMENT`) when unresolved.

- [ ] **Step 1: Add the strings**

In both templates, under `cli`:

```json
"which_project": "baton: which project? Pass one of these with --project (or `.` for the root):",
"unknown_project": "baton: no project matches '{name}'. Available:",
"loaded": "baton: `{name}` is now this session's active project.",
"no_projects": "baton: this root has no projects with their own handoff."
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_multi_project.py`:

```python
class TestLoad(Base):
    def setUp(self):
        super().setUp()
        self.sub("proyectos/radar", body="## State\ncanary xylophone-7731\n")
        self.sub("proyectos/instrumentos")

    def test_it_prints_the_handoff_with_its_wrapper(self):
        p = self.cli("load", "radar")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("xylophone-7731", p.stdout)
        self.assertIn("MEMORY MODE", p.stdout)
        self.assertIn("baton-handoff", p.stdout)

    def test_it_marks_the_project_as_active(self):
        self.cli("load", "radar")
        found = projects.discover(self.project)
        self.assertEqual(projects.read_active(self.project, found).rel, "proyectos/radar")

    def test_an_ambiguous_name_loads_nothing(self):
        self.sub("proyectos/radar-dos")
        p = self.cli("load", "radar")
        self.assertEqual(p.returncode, 3)
        self.assertIn("radar-dos", p.stderr)
        found = projects.discover(self.project)
        self.assertIsNone(projects.read_active(self.project, found))

    def test_an_unknown_name_lists_what_exists(self):
        p = self.cli("load", "nada")
        self.assertEqual(p.returncode, 3)
        self.assertIn("instrumentos", p.stderr)

    def test_loading_the_root_clears_the_activation(self):
        self.handoff(self.project)
        self.cli("load", "radar")
        p = self.cli("load", ".")
        self.assertEqual(p.returncode, 0, p.stderr)
        found = projects.discover(self.project)
        self.assertIsNone(projects.read_active(self.project, found))

    def test_freshness_only_counts_commits_that_touched_this_project(self):
        # Spec 8: `git -C <project>` with the pathspec `.` scopes the count to
        # that folder. Without it, in a monorepo every project's handoff would
        # look stale the moment any other project got a commit -- and a notice
        # that always fires is one the model learns to ignore.
        self.init_git()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "todo")
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.handoff(self.project / "proyectos" / "radar")
        radar_doc = self.project / "proyectos" / "radar" / ".baton" / "HANDOFF.md"
        radar_doc.write_text(radar_doc.read_text(encoding="utf-8").replace(
            "commit: abc1234", f"commit: {head}"), encoding="utf-8")
        (self.project / "proyectos" / "instrumentos" / "otro.txt").write_text(
            "cambio ajeno\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "cambio en el otro proyecto")

        p = self.cli("load", "radar")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("new commits", p.stdout)

    def test_the_second_load_says_it_is_a_repeat(self):
        self.cli("load", "radar")
        p = self.cli("load", "radar")
        self.assertIn("already been delivered", p.stdout)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python3 -m unittest tests.test_multi_project.TestLoad -v`
Expected: FAIL — `invalid choice: 'load'` from argparse, exit 2.

- [ ] **Step 4: Implement**

Replace `_project(args)` with a target-aware version and add the command:

```python
def _resolve(args, allow_new=False):
    """Root, target, config, paths and strings. The preamble to every subcommand.

    Returns (ctx, error_code). A non-zero code means the caller prints nothing
    more and returns it: the candidates have already been written to stderr.
    """
    root = storage.project_root(args.cwd or os.getcwd())
    root_cfg = config.load(root)
    found = projects.discover(root, depth=root_cfg["discovery"]["depth"],
                              max_dirs=root_cfg["discovery"]["max_dirs"],
                              document_rel=root_cfg["document"])
    name = getattr(args, "project", None)

    if name is None:
        active = projects.read_active(root, found)
        if active is not None:
            target = projects.Target(root, active)
        elif not found.projects:
            target = projects.Target(root)          # the ordinary single project
        else:
            target = None
        candidates = list(found.projects)
    else:
        target, candidates = projects.resolve(root, found, name, allow_new=allow_new)

    strings = output.load_strings(root_cfg["language"])
    if target is None:
        key = "unknown_project" if name else "which_project"
        print(strings["cli"][key].format(name=name or ""), file=sys.stderr)
        for project in candidates:
            print(f"  {project.name}  ({project.rel})", file=sys.stderr)
        return None, ENVIRONMENT

    cfg = config.load(target.path, parent=root)
    paths = storage.Paths(target.path, document_rel=cfg["document"])
    return Ctx(root, target, cfg, paths, output.load_strings(cfg["language"]), found), OK
```

with a small `Ctx` dataclass (`root`, `target`, `cfg`, `paths`, `strings`,
`found`) at the top of the file. Every existing subcommand switches from
`root, cfg, paths, strings = _project(args)` to:

```python
    ctx, code = _resolve(args)
    if code:
        return code
```

and then uses `ctx.paths`, `ctx.cfg`, `ctx.strings`, `ctx.target.path` (where
the old code used `root`, e.g. `gitinfo.snapshot(ctx.target.path)`).

`cmd_load`:

```python
def cmd_load(args) -> int:
    """Deliver one project's handoff and make it this session's active one.

    It prints exactly what the hook would have injected -- same wrapper, same
    freshness, same repeat notice, same trim. A handoff has to carry identical
    guarantees whether it arrived through the hook or through this command,
    otherwise the mode instruction becomes something the model can be talked out
    of.
    """
    ctx, code = _resolve(args)
    if code:
        return code
    if not ctx.paths.document.is_file():
        print(ctx.strings["cli"]["no_projects"], file=sys.stderr)
        return ENVIRONMENT

    text = ctx.paths.document.read_text(encoding="utf-8", errors="replace")
    fields = document.read_fields(text)
    notice = gitinfo.freshness(ctx.target.path, fields.get("date"), fields.get("branch", ""),
                               fields.get("commit", ""), ctx.strings).notice()
    repeat = storage.record_delivery(
        ctx.paths, document.fingerprint(text, ctx.strings["context_section"]))

    print(output.wrap(
        body=document.extract_body(text, ctx.strings["context_section"]) or text,
        mode=document.read_mode(text), written=fields.get("date", "?"),
        source=ctx.target.rel, freshness_notice=notice, repeat=repeat,
        strings=ctx.strings))

    if ctx.target.is_root:
        projects.clear_active(ctx.root)
    else:
        projects.set_active(ctx.root, ctx.target.project,
                            session=os.environ.get("CLAUDE_SESSION_ID", ""))
        print(ctx.strings["cli"]["loaded"].format(name=ctx.target.label), file=sys.stderr)
    return OK
```

In `main()`:

```python
    load = with_cwd("load", "deliver a project's handoff and make it active", cmd_load)
    load.add_argument("project", help="project name, relative path, or `.` for the root")
```

`with_cwd` already sets `--cwd`; the positional lands in `args.project`, which is
exactly the attribute `_resolve` reads.

- [ ] **Step 5: Run the tests and the suite, then commit**

Run: `python3 -m unittest tests.test_multi_project -v`, then `bash tests/run.sh`.
Expected: OK. `tests/test_cli.py` must pass untouched.

```bash
git add scripts/baton.py templates/en.json templates/es.json tests/test_multi_project.py
git commit -F- <<'EOF'
feat: baton.py load entrega un proyecto y lo deja activo

Imprime exactamente lo que habria inyectado el hook: mismo envoltorio,
misma frescura, mismo aviso de repeticion, mismo recorte. Si por este
camino llegara mas flojo, la instruccion de modo pasaria a ser algo de
lo que al modelo se le puede convencer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 9: `--project` on `context`, `write` and `show`

**Files:**
- Modify: `scripts/baton.py`
- Modify: `tests/test_multi_project.py`

**Interfaces:**
- Consumes: `_resolve` from Task 8.
- Produces: `--project` on the three subcommands; `write` accepts a directory with no handoff yet (`allow_new=True`) and prints the absolute path it wrote to.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_multi_project.py`:

```python
class TestWriteTarget(Base):
    def draft(self, where, text="## State\nwhere we are, concretely\n"):
        d = where / ".baton" / "local"
        d.mkdir(parents=True, exist_ok=True)
        (d / "draft.md").write_text(text, encoding="utf-8")

    def test_it_writes_into_the_active_project(self):
        radar = self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        self.cli("load", "radar")
        self.draft(radar)
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(str(radar), p.stdout)
        self.assertIn("where we are, concretely", (radar / ".baton" / "HANDOFF.md").read_text())

    def test_with_projects_and_none_active_it_refuses_and_lists_them(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        self.draft(self.project)
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, 3)
        self.assertIn("radar", p.stderr)
        self.assertIn("instrumentos", p.stderr)

    def test_an_explicit_project_bootstraps_a_folder_with_no_handoff(self):
        self.sub("proyectos/radar")
        nuevo = self.project / "proyectos" / "nuevo"
        nuevo.mkdir(parents=True)
        self.draft(nuevo)
        p = self.cli("write", "--mode", "memory", "--project", "proyectos/nuevo")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((nuevo / ".baton" / "HANDOFF.md").is_file())

    def test_a_typo_does_not_found_a_project_in_a_folder_nobody_made(self):
        self.sub("proyectos/radar")
        self.draft(self.project)
        p = self.cli("write", "--mode", "memory", "--project", "proyectos/nuevoo")
        self.assertEqual(p.returncode, 3)
        self.assertFalse((self.project / "proyectos" / "nuevoo").exists())

    def test_a_single_project_root_is_unaffected(self):
        self.draft(self.project)
        p = self.cli("write", "--mode", "memory")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.project / ".baton" / "HANDOFF.md").is_file())

    def test_context_reports_the_target_project(self):
        radar = self.sub("proyectos/radar")
        self.cli("load", "radar")
        p = self.cli("context")
        self.assertIn(str(radar), p.stdout)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_multi_project.TestWriteTarget -v`
Expected: FAIL — `unrecognized arguments: --project`, exit 2.

- [ ] **Step 3: Implement**

In `main()`, extend `with_cwd` so the three commands share the flag:

```python
    def with_cwd(name, help_text, func, project_flag=True):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--cwd", default=None, help="project directory (defaults to the current one)")
        if project_flag:
            sp.add_argument("--project", default=None,
                            help="which project in this root (name, relative path, or `.`)")
        sp.set_defaults(func=func)
        return sp
```

`load` passes `project_flag=False` (it takes a positional instead). In
`cmd_write`, resolve with `allow_new=True`:

```python
    ctx, code = _resolve(args, allow_new=True)
    if code:
        return code
```

and print the absolute path, which `strings["cli"]["written"]` already does via
`{path}` — verify `paths.document` is absolute (it is: `Paths` is built from an
absolute root). In `cmd_context`, the first output line becomes
`f"project: {ctx.target.path}"`, unchanged in shape.

- [ ] **Step 4: Run the tests and the suite, then commit**

Run: `bash tests/run.sh`.

```bash
git add scripts/baton.py tests/test_multi_project.py
git commit -F- <<'EOF'
feat: --project en context, write y show, con arranque en frio

Con varios proyectos y ninguno activo, write no elige: lista y falla.
La conversacion no se usa para deducir el destino porque en una sesion
que toco dos proyectos, deducir mal pisa un handoff bueno.

Siempre imprime la ruta absoluta donde escribio: un destino equivocado
tiene que verse en el acto, no dentro de tres dias.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 10: `doctor`

**Files:**
- Modify: `scripts/baton.py`
- Modify: `tests/test_multi_project.py`

**Interfaces:**
- Consumes: `Ctx.found`, `projects.read_active`.
- Produces: no new function; `doctor` prints the discovery block.

- [ ] **Step 1: Write the failing tests**

```python
class TestDoctor(Base):
    def test_it_lists_the_projects_and_the_active_one(self):
        self.sub("proyectos/radar")
        self.sub("proyectos/instrumentos")
        self.cli("load", "radar")
        p = self.cli("doctor")
        self.assertIn("proyectos/radar", p.stdout)
        self.assertIn("proyectos/instrumentos", p.stdout)
        self.assertIn("active", p.stdout.lower())

    def test_it_says_how_deep_it_looked(self):
        p = self.cli("doctor")
        self.assertIn("depth 2", p.stdout)

    def test_it_warns_when_the_scan_hit_its_cap(self):
        (self.project / ".claude").mkdir(exist_ok=True)
        (self.project / ".claude" / "baton.json").write_text(
            '{"discovery": {"max_dirs": 50}}', encoding="utf-8")
        for i in range(60):
            (self.project / f"vacia{i}").mkdir()
        p = self.cli("doctor")
        self.assertIn("limit", p.stdout.lower())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_multi_project.TestDoctor -v`
Expected: FAIL — the strings are absent from `doctor`'s output.

- [ ] **Step 3: Implement**

`doctor`'s lines are the one place this codebase keeps English text in the code
rather than in `templates/` -- it is a diagnostic aimed at whoever is debugging
an install, and every existing line there is hardcoded. Follow that convention:
these new lines do NOT go to the templates.

In `cmd_doctor`, after the language line:

```python
    out.append(f"  [ok] discovery              depth {ctx.cfg['discovery']['depth']}, "
               f"{len(ctx.found.projects)} project(s) found")
    for project in ctx.found.projects:
        card = projects.describe(project, ctx.cfg["document"])
        out.append(f"         - {project.rel}  ({card.mode}, {card.date or 'no date'})")
    if ctx.found.truncated:
        out.append("  [!!] the scan hit its limit; raise discovery.max_dirs to see the rest")
    active = projects.read_active(ctx.root, ctx.found)
    out.append(f"  [ok] active project         {active.rel}" if active
               else "  [--] active project         none loaded in this session")
```

Note `doctor` must not fail when `_resolve` returns no target (several projects,
none active): call it with a fallback to the root so the diagnosis still prints.
Give `cmd_doctor` its own resolution:

```python
    ctx, code = _resolve(args)
    if code:  # several projects and none chosen: diagnose the ROOT anyway
        args.project = projects.ROOT_NAME
        ctx, code = _resolve(args)
        if code:
            return code
```

- [ ] **Step 4: Run the tests and the suite, then commit**

```bash
git add scripts/baton.py tests/test_multi_project.py
git commit -F- <<'EOF'
feat: doctor reporta proyectos, profundidad y proyecto activo

"No me aparece un proyecto" no puede ser un misterio: la respuesta
-hasta donde miro, que encontro, si toco el tope- queda a un comando.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

---

### Task 11: Docs and release

**Files:**
- Modify: `skills/baton/SKILL.md`, `commands/baton.md`
- Modify: `README.md`, `README.es.md`, `CHANGELOG.md`
- Modify: `.claude-plugin/plugin.json`

**Interfaces:**
- Consumes: the finished behaviour of Tasks 1-10.
- Produces: nothing code depends on.

- [ ] **Step 1: Update the skill**

In `skills/baton/SKILL.md`, before "1. Ask for the context", add a step 0:

```markdown
## 0. Which project

If the session started with a `<baton-index>` instead of a handoff, this root
holds several projects. Do not write anything until you know which one:

- The user named one, or you already ran `baton.py load <name>` this session:
  that is the target, and `/baton` writes there on its own.
- Otherwise, ask in one line. Never infer it from which files were touched: in a
  session that touched two projects, guessing overwrites a good handoff.

Pass `--project <name>` to `context` and `write` only to override the active
project, or to create the handoff of a project that does not have one yet (the
folder must already exist).
```

- [ ] **Step 2: Update the command**

In `commands/baton.md`, change `argument-hint` to
`"[memory|continue] [project] [optional short note]"` and add a paragraph saying
a bare `/baton` writes to the session's active project, and that with several
projects and none active the CLI will ask.

- [ ] **Step 3: Update both READMEs**

Add a "Several projects in one folder" / "Varios proyectos en una carpeta"
section: the rule (a folder with its own handoff), the index at startup, `load`,
`--project`, and the `discovery.depth` escape hatch. Include a mermaid diagram of
the four session-start cases — the file already requires at least 4 valid mermaid
blocks per README (`tests/test_readme.py`), so validate any new one with
`node tools/validate-mermaid.mjs` before committing.

Extend the manual acceptance checks in both with the multi-project scenario:

```
6. Two projects in one folder
   - Create <root>/a/ and <root>/b/, run /baton in each with --project.
   - Open a new session at <root>: you must see the index, and NO project body.
   - Say "work on a" -> the model runs `baton.py load a` and gets a's handoff.
   - Run /baton: it must write to <root>/a/.baton/HANDOFF.md, and say so.
```

- [ ] **Step 4: Fix the test count in both READMEs**

`tests/test_readme.py::test_the_test_count_is_true_in_both_readmes` compares the
badge and the prose against the real suite. Get the number:

```bash
python3 -c "import unittest; print(unittest.TestLoader().discover('tests', top_level_dir='.').countTestCases())"
```

and update `badge/tests-<N>-` and the `<N> tests on the stdlib` / `<N> tests con`
lines in both files.

- [ ] **Step 5: CHANGELOG and version**

Add a `0.4.0` entry describing the feature in the CHANGELOG's existing voice, and
set `"version": "0.4.0"` in `.claude-plugin/plugin.json`. The bump is not
cosmetic: without it `claude plugin update` does not pick the change up.

- [ ] **Step 6: Run the whole suite and commit**

Run: `bash tests/run.sh`
Expected: OK, including `test_readme.py`.

```bash
git add -A
git commit -F- <<'EOF'
feat!: raices con varios proyectos

Una sesion abierta en una carpeta con varios proyectos ya no los hace
compartir un handoff: recibe un indice, carga el que le digan y escribe
en ese. Version 0.4.0, necesaria para que claude plugin update se entere,
y reinicio para que recarguen los hooks.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01T4HjCMr1kSJAYq4LfR7tYM
EOF
```

- [ ] **Step 7: Manual acceptance on a real install**

Unit tests do not see the failures that only appear on a real install — that is
what 0.3.1 established, at the cost of a bug 211 green tests had not seen. After
committing:

1. `claude plugin update baton` and **restart Claude Code**.
2. Run the check from Step 3 against a real folder with two projects.
3. `baton.py doctor` in that root must list both projects and the active one.

Report what actually happened at each step. If any of it fails, that is a bug in
this plan's implementation, not a step to skip.
