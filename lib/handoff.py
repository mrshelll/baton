"""Compose and measure a handoff, and write it only when it is valid and fits.

`baton.py write` and the hooks both end up here, so a handoff carries the same
frontmatter, git context and budget wherever it came from. What stays in the CLI
is what only makes sense with a model on the other end: the attempt counter and
the minimal escape after the last attempt. A hook has nobody to retry, so it
gets an outcome instead of a second chance.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lib import budget, document, gitinfo, storage


@dataclass(frozen=True)
class Built:
    """A composed handoff and what was learned composing it.

    When the draft is invalid there is nothing to compose: `final` is empty and
    `verdict` measures that emptiness, so read `parsed.valid` first.
    """
    final: str
    parsed: document.ParsedDraft
    verdict: budget.Verdict


def assembler(mode: str, root: Path, strings: dict):
    """A `body -> document` function bound to the repo's state right now.

    The git snapshot is taken once, here; the date is taken on every call, the
    moment the document is put together.
    """
    snap = gitinfo.snapshot(root)
    context = gitinfo.context_block(snap, strings)

    def assemble(body: str) -> str:
        return document.compose(
            body=body, mode=mode, date=gitinfo.now_iso(),
            branch=snap.branch, commit=snap.commit,
            context=context, strings=strings)

    return assemble


def build(body: str, mode: str, root: Path, cfg: dict, strings: dict) -> Built:
    """Validate the draft, compose the document and measure it. Writes nothing."""
    if mode not in document.MODES:
        parsed = document.ParsedDraft(False, errors=[strings["cli"]["invalid_mode"].format(
            mode=mode, valid=" or ".join(document.MODES))])
    else:
        parsed = document.validate_draft(body, mode=mode, strings=strings)
    if not parsed.valid:
        # No git for a draft that will not be written.
        return Built("", parsed, budget.evaluate("", cfg["limits"]))
    final = assembler(mode, root, strings)(parsed.body)
    return Built(final, parsed, budget.evaluate(final, cfg["limits"]))


def write_if_fits(paths: storage.Paths, built: Built, cfg: dict) -> str:
    """Write the handoff only when it is valid and fits; never raises.

    Returns "written", "invalid", "over_budget" or "busy". On anything but
    "written" the previous handoff is left exactly as it was.
    """
    if not built.parsed.valid:
        return "invalid"
    if not built.verdict.fits:
        return "over_budget"
    try:
        storage.write_document(paths, built.final, history_max=cfg["history_max"])
    except (storage.BusyError, storage.StorageError, OSError):
        return "busy"
    return "written"
