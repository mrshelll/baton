"""Everything baton knows about git. And only here.

Two uses:

1. **Snapshot**: branch, commit and uncommitted files, written into the document
   by CODE. The model does not write them, so it cannot get them wrong nor spend
   budget listing them.
2. **Freshness**: when injecting, compare the document against the repo as it is
   now and flag what changed. Flag, never expire: a project idle for two weeks
   does not invalidate its handoff.

Module rule: no function raises and no function stalls. Every git call has a
timeout, and if git is missing or hangs we degrade to "no-git".
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: A session start cannot wait on a stalled git (huge repo, network disk, locked
#: index). Three seconds and we carry on without those facts.
TIMEOUT = 3

#: How many dirty files are named before summarising. The rest are counted.
MAX_DIRTY = 10

NO_GIT = "no-git"

#: baton's own files are not the user's work. Without filtering them, every
#: handoff would open by reporting that baton just wrote a handoff, and the
#: freshness notice would count its own files as "code that changed". Noise in
#: both places, for the same reason.
OWN_PREFIX = ".baton/"

_git_available = None


def clear_git_cache() -> None:
    """Tests manipulate PATH; without this the detection stays stuck."""
    global _git_available
    _git_available = None


def _is_own(name: str) -> bool:
    return name.startswith(OWN_PREFIX)


def _git_available_now() -> bool:
    global _git_available
    if _git_available is None:
        _git_available = shutil.which("git") is not None
    return _git_available


def _git(root, *args):
    """Run git and return stdout, or None on any problem."""
    if not _git_available_now():
        return None
    try:
        p = subprocess.run(
            ("git", "-C", str(root)) + args,
            capture_output=True, timeout=TIMEOUT, check=False,
        )
    except Exception:
        return None
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", errors="replace")


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Snapshot:
    has_git: bool
    branch: str
    commit: str
    subject: str = ""
    commit_date: str = ""
    dirty: list = field(default_factory=list)
    ahead: str = ""


def _head(root):
    """(commit, subject, date). A freshly initialised repo has no history yet."""
    line = _git(root, "log", "-1", "--format=%h%x00%s%x00%cs")
    if not line:
        return "no-commits", "", ""
    parts = line.strip("\n").split("\0")
    return tuple((parts + ["", "", ""])[:3])


def _dirty(root):
    """-z plus NUL splitting, so names with spaces, accents or newlines stop
    being a special case."""
    raw = _git(root, "status", "--porcelain=v1", "-z") or ""
    return [e[3:] for e in raw.split("\0") if len(e) > 3 and not _is_own(e[3:])]


def _ahead(root):
    counts = _git(root, "rev-list", "--count", "--left-right", "@{upstream}...HEAD")
    if not counts or "\t" not in counts:
        return ""
    behind, ahead = counts.strip().split("\t")[:2]
    parts = []
    if ahead != "0":
        parts.append(f"{ahead} ahead")
    if behind != "0":
        parts.append(f"{behind} behind")
    return " and ".join(parts)


def snapshot(root) -> Snapshot:
    """The repo's facts right now. Without git everything stays "no-git"."""
    root = Path(root)
    if _git(root, "rev-parse", "--git-dir") is None:
        return Snapshot(has_git=False, branch=NO_GIT, commit=NO_GIT)
    branch = (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip() or NO_GIT
    commit, subject, date = _head(root)
    return Snapshot(True, branch, commit, subject, date, _dirty(root), _ahead(root))


def context_block(s: Snapshot, strings) -> str:
    """The document's `## Context`. Capped at 6 lines by contract.

    If a noisy `git status` could grow without bound it would eat the model's
    budget. Hence summarising instead of listing everything.
    """
    c = strings["context"]
    if not s.has_git:
        return c["no_git"]

    lines = []
    if s.dirty:
        names = s.dirty[:MAX_DIRTY]
        rest = len(s.dirty) - len(names)
        listing = ", ".join(names) + (c["and_more"].format(n=rest) if rest > 0 else "")
        lines.append(c["dirty"].format(branch=s.branch, n=len(s.dirty), files=listing))
    else:
        lines.append(c["clean"].format(branch=s.branch))

    if s.commit != "no-commits":
        date = f" ({s.commit_date})" if s.commit_date else ""
        lines.append(c["last_commit"].format(commit=s.commit, subject=s.subject, date=date).rstrip())
    else:
        lines.append(c["no_commits"])

    if s.ahead:
        lines.append(c["ahead"].format(state=s.ahead))
    return "\n".join(lines[:6])


@dataclass
class Freshness:
    has_git: bool
    days: float | None
    document_branch: str
    current_branch: str
    new_commits: int
    changed_files: int
    commit_lost: bool
    strings: dict = field(default_factory=dict)

    def notice(self) -> str:
        """The notice text, or empty when there is nothing to say.

        Spending zero lines on the good case is deliberate: the budget is for
        the handoff, not for saying that everything is fine.
        """
        f = self.strings["freshness"]
        if self.commit_lost:
            return f["rebased"]

        old = self.days is not None and self.days >= 1
        if not self.has_git:
            return f["no_git"].format(days=f"{self.days:.0f}") if old else ""

        branch_changed = (self.document_branch not in ("", NO_GIT)
                          and self.document_branch != self.current_branch)
        if not (old or branch_changed or self.new_commits):
            return ""

        text = f["opening"].format(age=f["days"].format(days=f"{self.days:.0f}")
                                   if old else f["today"])
        if branch_changed:
            text += f["branch"].format(was=self.document_branch, now=self.current_branch)
        if self.new_commits:
            text += f["commits"].format(commits=self.new_commits, files=self.changed_files)
        return text + f["closing"]


def _days_since(iso_date) -> float | None:
    if not isinstance(iso_date, str) or not iso_date.strip():
        return None
    try:
        when = datetime.fromisoformat(iso_date.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() / 86400


def freshness(root, document_date, document_branch, document_commit, strings) -> Freshness:
    """Compare the document against the repo as it is now. Never raises."""
    days = _days_since(document_date)
    s = snapshot(root)
    if not s.has_git:
        return Freshness(False, days, document_branch or "", NO_GIT, 0, 0, False, strings)

    lost = False
    new = changed = 0
    if document_commit and document_commit not in (NO_GIT, "no-commits"):
        if _git(root, "cat-file", "-e", f"{document_commit}^{{commit}}") is None:
            lost = True
        else:
            out = _git(root, "rev-list", "--count", f"{document_commit}..HEAD")
            try:
                new = int((out or "0").strip())
            except ValueError:
                new = 0
            if new:
                listing = _git(root, "diff", "--name-only", "-z",
                               f"{document_commit}..HEAD") or ""
                changed = len([x for x in listing.split("\0") if x and not _is_own(x)])

    return Freshness(True, days, document_branch or "", s.branch, new, changed, lost, strings)
