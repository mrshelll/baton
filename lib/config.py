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

from lib import budget, output

DEFAULTS = {
    "limits": dict(budget.DEFAULT_LIMITS),
    # Always relative to the project root.
    "document": ".baton/HANDOFF.md",
    "history_max": 10,
    # Which session starts get the handoff injected.
    "inject_on": ["startup", "clear", "compact", "resume", "fork"],
    # Minutes between two automatic handoff requests.
    "cooldown_minutes": 30,
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


def load(root, global_path=None) -> Config:
    """Defaults -> global -> project. The project one wins.

    `global_path` exists so tests do not depend on whoever's HOME runs them; in
    production nobody passes it.
    """
    warnings: list = []
    data = dict(DEFAULTS)
    data["limits"] = dict(DEFAULTS["limits"])
    globals_ = Path(global_path) if global_path else default_global_path()
    for path in (globals_, Path(root) / ".claude" / "baton.json"):
        raw = _read(path, warnings)
        if raw:
            data = _merge(data, raw, path, warnings)
    return Config(data, warnings)
