"""Find this repository's Claude Code transcripts (spec §2.4).

Claude Code stores a session under ``<projects root>/<slug of the start cwd>/<session>.jsonl``.
Candidate folders are those named after P or one of its worktrees (or a subdirectory of them);
a transcript is kept only when its entries' ``cwd`` lies inside one of the checkouts, which rejects
prefix collisions such as ``D--spec-kit`` vs ``D--spec-kit-usage-bridge``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import tu_compat
from .paths import claude_slug, is_inside, same_path


@dataclass(frozen=True)
class SubagentFile:
    path: Path
    meta: Path | None


@dataclass(frozen=True)
class SessionFiles:
    session_id: str
    main: Path
    subagents: tuple[SubagentFile, ...] = ()
    stamps: tuple[tuple[str, int, int], ...] = ()

    def key(self) -> list[tuple[str, int, int]]:
        """(path, size, mtime_ns) of the main transcript, then of every subagent file (sorted),
        as observed when the session was discovered."""
        return list(self.stamps)


def _stamp(path: Path) -> tuple[str, int, int]:
    try:
        st = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), st.st_size, st.st_mtime_ns)


def projects_roots(payload: Mapping[str, Any], env: Mapping[str, str]) -> list[Path]:
    """Existing Claude projects roots: the payload's own, token-usage's, and $CLAUDE_CONFIG_DIR's."""
    candidates: list[Path] = []
    transcript = (payload or {}).get("transcript_path")
    if isinstance(transcript, str) and transcript:
        candidates.append(Path(transcript).parent.parent)
    candidates.append(tu_compat.projects_root())
    config_dir = env.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        candidates.append(Path(config_dir) / "projects")
    roots: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir() and not any(same_path(candidate, root) for root in roots):
            roots.append(candidate)
    return roots


def session_cwd(main: Path, max_lines: int = 50) -> str | None:
    """The first ``cwd`` recorded in a transcript (looking at most ``max_lines`` entries)."""
    entries = tu_compat.iter_entries(main)
    try:
        for index, entry in enumerate(entries):
            if index >= max_lines:
                break
            cwd = entry.get("cwd")
            if isinstance(cwd, str) and cwd:
                return cwd
    finally:
        entries.close()
    return None


def _session_files(main: Path) -> SessionFiles:
    folder = main.parent / main.stem / "subagents"
    subagents: list[SubagentFile] = []
    if folder.is_dir():
        for path in sorted(folder.rglob("agent-*.jsonl")):
            meta = path.with_suffix(".meta.json")
            subagents.append(SubagentFile(path, meta if meta.is_file() else None))
    stamps = (_stamp(main), *sorted(_stamp(sub.path) for sub in subagents))
    return SessionFiles(main.stem, main, tuple(subagents), stamps)


def discover(checkouts: Sequence[Path], roots: Sequence[Path], extra_dirs: Sequence[Path]) -> list[SessionFiles]:
    """Every session of this repository (sorted by main transcript path)."""
    slugs = [claude_slug(Path(c).absolute()).lower() for c in checkouts]
    seen: set[str] = set()
    found: list[SessionFiles] = []

    def consider(main: Path, check_membership: bool) -> None:
        marker = os.path.normcase(os.path.abspath(main))
        if marker in seen:
            return
        if check_membership:
            cwd = session_cwd(main)
            if cwd is None or not is_inside(cwd, checkouts):
                return
        seen.add(marker)
        found.append(_session_files(main))

    for root in roots:
        try:
            folders = sorted(d for d in Path(root).iterdir() if d.is_dir())
        except OSError:
            continue
        for folder in folders:
            name = folder.name.lower()
            if any(name == s or name.startswith(s + "-") for s in slugs):
                for main in sorted(folder.glob("*.jsonl")):
                    consider(main, True)
    for folder in extra_dirs:
        folder = Path(folder)
        if folder.is_dir():
            for main in sorted(folder.glob("*.jsonl")):
                consider(main, False)
    return sorted(found, key=lambda s: str(s.main))
