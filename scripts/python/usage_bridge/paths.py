"""Project, work root, runtime dir and identity helpers (spec §2.2).

P is the project that has the extension installed (where the dispatcher runs); W is the checkout
the session actually worked in — the payload ``cwd`` can be a git worktree of P, because
``${CLAUDE_PROJECT_DIR}`` stays at the checkout where the session started (spec F19).
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path

RUNTIME_NAME = "usage-bridge"
FALLBACK_RUNTIME = Path(".specify") / "extensions" / "usage-bridge" / ".runtime"


def claude_slug(path) -> str:
    """Claude Code's project-folder name for a path: every non-alphanumeric character becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def slugify(text: str, max_len: int = 40) -> str:
    """Lower-case ASCII slug: accents folded, other characters collapsed to '-'."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:max_len].strip("-")


def author_slug(alias: str, git_name: str | None, os_user: str) -> str:
    for candidate in (alias, git_name, os_user):
        value = slugify(candidate or "")
        if value:
            return value
    return "unknown"


def machine_id(hostname: str) -> str:
    return hashlib.sha256((hostname or "").lower().encode("utf-8")).hexdigest()[:6]


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def same_path(a, b) -> bool:
    return _norm(a) == _norm(b)


def is_inside(child, roots: Iterable[Path]) -> bool:
    """True when ``child`` equals or lies below one of ``roots`` (case-insensitive on Windows)."""
    target = _norm(child)
    for root in roots:
        base = _norm(root)
        if target == base or target.startswith(base.rstrip("\\/") + os.sep):
            return True
    return False


def project_root(cwd: Path) -> Path | None:
    """The nearest ancestor of ``cwd`` (inclusive) that contains a ``.specify`` directory."""
    current = Path(cwd).absolute()
    for candidate in (current, *current.parents):
        if (candidate / ".specify").is_dir():
            return candidate
    return None


def git(args: Sequence[str], cwd: Path, timeout: float = 5.0) -> str | None:
    """Run git and return its stripped stdout; None when git is missing, fails or times out."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def worktrees(project: Path) -> list[Path]:
    """Every checkout of the repository (main worktree first); [] without git."""
    listing = git(["worktree", "list", "--porcelain"], project)
    if not listing:
        return []
    return [Path(line[len("worktree "):]) for line in listing.splitlines() if line.startswith("worktree ")]


def work_root(payload_cwd: str | None, project: Path) -> Path:
    """The checkout of P that contains ``payload_cwd`` (deepest match wins); P otherwise."""
    if not payload_cwd:
        return Path(project)
    best: Path | None = None
    for candidate in [*worktrees(project), Path(project)]:
        if is_inside(payload_cwd, [candidate]) and (best is None or len(_norm(candidate)) > len(_norm(best))):
            best = candidate
    return best if best is not None else Path(project)


def runtime_dir(work: Path, project: Path) -> Path:
    """``<git common dir>/usage-bridge`` (shared by all worktrees); the .specify fallback outside git."""
    common = git(["rev-parse", "--git-common-dir"], work)
    if common:
        path = (Path(work) / common).resolve() / RUNTIME_NAME
    else:
        path = Path(project) / FALLBACK_RUNTIME
    path.mkdir(parents=True, exist_ok=True)
    return path


def current_branch(work: Path) -> str | None:
    return git(["branch", "--show-current"], work) or None


def git_user_name(work: Path) -> str | None:
    return git(["config", "user.name"], work) or None
