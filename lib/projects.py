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
#: one grouping level, which are the shapes that actually occur. Depth 3 would be
#: tens of thousands of stat calls on every session start of every project on the
#: machine, and under a cap it would truncate arbitrarily -- a project missing for
#: no visible reason is worse than one not looked for.
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
    # How this discovery was made, so a later cold-start search can walk the same
    # tree with the same limits instead of inventing its own.
    root: Path = Path(".")
    depth: int = DEFAULT_DEPTH
    max_dirs: int = DEFAULT_MAX_DIRS
    document_rel: str = DEFAULT_DOCUMENT

    def __bool__(self) -> bool:
        return bool(self.projects)


def _walk(root: Path, depth: int, max_dirs: int, is_leaf=None):
    """Breadth-first over the directories under `root`.

    Returns `(visited, leaves, truncated)`. `is_leaf(dir)` marks a directory as an
    endpoint: it is collected in `leaves` and not descended into.

    One traversal for every caller on purpose. Discovery and the cold-start
    search have to agree on what a directory even is -- same skips, same depth,
    same cap -- and two copies of this loop would drift apart on the first fix.
    """
    visited: list = []
    leaves: list = []
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
                visited.append(directory)
                if is_leaf is not None and is_leaf(directory):
                    leaves.append(directory)
                    continue  # its own subprojects are its business, not the root's
                following.append(directory)
            if truncated:
                break
        if truncated:
            break
        level = following

    return visited, leaves, truncated


def _as_subproject(root: Path, directory: Path) -> SubProject:
    return SubProject(rel=directory.relative_to(root).as_posix(),
                      name=directory.name, path=directory)


def discover(root, depth: int = DEFAULT_DEPTH, max_dirs: int = DEFAULT_MAX_DIRS,
             document_rel: str = DEFAULT_DOCUMENT) -> Discovery:
    """Directories under `root` that carry their own handoff.

    Sorted at every level, so the result is stable rather than filesystem-ordered:
    an index that reshuffles between sessions reads like something changed when
    nothing did.

    Never raises. An unreadable directory is skipped and the scan carries on: a
    broken scan cannot stop a session from starting.
    """
    root = Path(root)

    def has_handoff(directory: Path) -> bool:
        try:
            return (directory / document_rel).is_file()
        except OSError:
            return False

    _, leaves, truncated = _walk(root, depth, max_dirs, is_leaf=has_handoff)
    found = sorted((_as_subproject(root, d) for d in leaves), key=lambda p: p.rel)
    return Discovery(tuple(found), truncated, root, depth, max_dirs, document_rel)


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

    # The root, named by its own folder name. This is not a nicety: writing the
    # draft creates `.baton/`, which is a root marker, so between the `context`
    # call and the `write` call the root can move down to the very folder that
    # was named. Without this the flag stops resolving halfway through the one
    # sequence that needs it, and the cold start cannot be completed at all.
    if key.casefold() == root.name.casefold():
        return Target(root), []

    if allow_new:
        # A path relative to the root, first: it is unambiguous by construction.
        candidate = root / key
        if candidate.is_dir() and _inside(root, candidate):
            return Target(root, _as_subproject(root, candidate)), []

        # Then by folder NAME. Everything else in this interface -- the index,
        # `load` -- takes the name, so demanding a full relative path here only
        # at cold start is a contradiction the user pays for exactly once, on
        # the one call where nothing exists yet to list as a hint.
        matches = _candidates_by_name(discovery, key)
        if len(matches) == 1:
            return Target(root, matches[0]), []
        if len(matches) > 1:
            return None, matches

    return None, everything


def _candidates_by_name(discovery: Discovery, key: str):
    """Existing directories under the root whose name matches `key`.

    Only walked when a cold start asked for a folder that is not a project yet,
    so the extra traversal never happens on the common path.
    """
    root = Path(discovery.root)

    def has_handoff(directory: Path) -> bool:
        try:
            return (directory / discovery.document_rel).is_file()
        except OSError:
            return False

    visited, _, _ = _walk(root, discovery.depth, discovery.max_dirs, is_leaf=has_handoff)
    folded = key.casefold()
    for test in (lambda d: d.name.casefold() == folded,
                 lambda d: folded in d.name.casefold()):
        matches = [_as_subproject(root, d) for d in visited if test(d)]
        if matches:
            return matches
    return []


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
    every session start. An unreadable document still gets a card, in the safe
    mode -- like everything else here that cannot be read.
    """
    from lib import document
    try:
        with open(project.path / document_rel, encoding="utf-8", errors="replace") as fh:
            head = fh.read(document.HEAD)
    except OSError:
        head = ""
    return Card(name=project.name, rel=project.rel, mode=document.read_mode(head),
                date=document.read_fields(head).get("date", ""))


# --- the session's active project -----------------------------------------
#
# It lives one session. `load` writes it and a fresh session start clears it, so
# a pointer from yesterday cannot silently absorb today's handoff.


def active_path(root) -> Path:
    return Path(root) / ".baton" / "local" / "active.json"


def read_active(root, discovery: Discovery):
    """The active subproject, or None.

    Validated against what exists right now instead of trusted: a folder renamed
    between sessions would otherwise send the handoff to a path nobody is
    looking at.
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
