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
