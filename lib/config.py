"""baton's configuration: defaults, global and per project.

Two optional files, shaped like Claude Code's own `settings.json` so there is no
new concept to learn:

    ~/.claude/baton.json              your preference across every project
    <project>/.claude/baton.json      that repo only; wins over the global one

With neither, the defaults apply. A broken config never blocks baton: it warns
naming the file and carries on with the good values.
"""
from __future__ import annotations

import json
from pathlib import Path

from lib import budget, output, projects

DEFAULTS = {
    "limits": dict(budget.DEFAULT_LIMITS),
    # Always relative to the project root.
    "document": ".baton/HANDOFF.md",
    "history_max": 10,
    # Which session starts get the handoff injected.
    "inject_on": ["startup", "clear", "compact", "resume", "fork"],
    # Minutes between two automatic handoff requests.
    "cooldown_minutes": 30,
    # How far down a root is scanned for projects with their own handoff. Read
    # only from the root: it describes the shape of the tree, not a project.
    "discovery": {"depth": projects.DEFAULT_DEPTH, "max_dirs": projects.DEFAULT_MAX_DIRS},
    # The one-line receipt proving the hook fired.
    "receipt": True,
    # Language of everything a human reads: section headings, messages and the
    # instructions injected into the model. Config keys stay in English.
    "language": output.DEFAULT_LANGUAGE,
}

#: Typos worth a concrete hint instead of an unhelpful "unknown key".
SUGGESTIONS = {
    "topes": "limits",
    "max_lines": "limits.lines",
    "lines_max": "limits.lines",
    "max_characters": "limits.characters",
    "max_tokens": "limits.tokens",
    "history": "history_max",
    "path": "document",
    "lang": "language",
    "locale": "language",
}


class Config(dict):
    """A dict carrying the list of problems found while loading it."""

    def __init__(self, data, warnings=None):
        super().__init__(data)
        self.warnings = list(warnings or [])


def _read(path: Path, warnings: list):
    """Read a config JSON. Any problem becomes a warning."""
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"{path.name}: could not be read ({type(exc).__name__}); using defaults")
        return {}
    if not isinstance(data, dict):
        warnings.append(
            f"{path.name}: expected a JSON object, found {type(data).__name__}; using defaults")
        return {}
    return data


def _valid_int(value, minimum: int) -> bool:
    """bool is a subclass of int in Python, so `True` would pass as a number.
    Excluding it here once keeps that trap out of every call site."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _safe_path(value) -> bool:
    """The document lives INSIDE the project. No absolutes and no '..'."""
    if not isinstance(value, str) or not value.strip():
        return False
    p = Path(value)
    return not p.is_absolute() and ".." not in p.parts


def _merge(base: dict, over: dict, path: Path, warnings: list) -> dict:
    """One-level merge: `limits` merges key by key, everything else replaces.

    One level is exactly what is needed: touching `limits.lines` must not leave
    you without `limits.characters`, and at the same time nobody has to reason
    about deep merges that no one asked for.
    """
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for key, value in over.items():
        if key in SUGGESTIONS:
            warnings.append(f"{path.name}: unknown key '{key}'. Did you mean '{SUGGESTIONS[key]}'?")
        elif key not in DEFAULTS:
            warnings.append(f"{path.name}: unknown key '{key}'; ignoring it")
        elif key == "limits" and isinstance(value, dict):
            for name, number in value.items():
                if name not in DEFAULTS["limits"]:
                    warnings.append(f"{path.name}: unknown limit 'limits.{name}'; ignoring it")
                elif not _valid_int(number, 1):
                    warnings.append(f"{path.name}: 'limits.{name}' must be a positive integer; "
                                    f"using {DEFAULTS['limits'][name]}")
                else:
                    out["limits"][name] = number
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
        elif key == "document":
            if _safe_path(value):
                out["document"] = value
            else:
                warnings.append(f"{path.name}: 'document' points outside the project; "
                                f"using {DEFAULTS['document']}")
        elif key == "history_max":
            if _valid_int(value, 0):
                out["history_max"] = value
            else:
                warnings.append(f"{path.name}: 'history_max' must be an integer >= 0; "
                                f"using {DEFAULTS['history_max']}")
        elif key == "language":
            if isinstance(value, str) and value in output.available_languages():
                out["language"] = value
            else:
                warnings.append(
                    f"{path.name}: unknown language {value!r}; available: "
                    f"{', '.join(output.available_languages())}")
        else:
            out[key] = value
    return out


def default_global_path() -> Path:
    return Path.home() / ".claude" / "baton.json"


def load(root, global_path=None, parent=None) -> Config:
    """Defaults -> global -> root -> project. The most specific one wins.

    `parent` is the root's directory when `root` is a subproject of it. The chain
    exists so a global `language` keeps applying without being repeated in every
    project folder.

    `discovery` is the exception: it describes the shape of the tree, so only the
    root gets to set it, and a subproject that tries is told so rather than
    ignored in silence.

    `global_path` exists so tests do not depend on whoever's HOME runs them; in
    production nobody passes it.
    """
    warnings: list = []
    data = dict(DEFAULTS)
    data["limits"] = dict(DEFAULTS["limits"])
    data["discovery"] = dict(DEFAULTS["discovery"])
    globals_ = Path(global_path) if global_path else default_global_path()

    layers = [globals_]
    nested = parent is not None and Path(parent) != Path(root)
    if nested:
        layers.append(Path(parent) / ".claude" / "baton.json")
    layers.append(Path(root) / ".claude" / "baton.json")

    for i, path in enumerate(layers):
        raw = _read(path, warnings)
        if not raw:
            continue
        if nested and i == len(layers) - 1 and "discovery" in raw:
            warnings.append(f"{path.name}: 'discovery' is only read from the root; ignoring it")
            raw = {k: v for k, v in raw.items() if k != "discovery"}
        data = _merge(data, raw, path, warnings)
    return Config(data, warnings)
