"""The active-feature timeline recorded at every Stop (spec §2.3).

Spec Kit itself picks the feature from ``SPECIFY_FEATURE_DIRECTORY`` or ``.specify/feature.json``;
recording that choice at the end of every turn lets later captures attribute each run to exactly
the feature Spec Kit worked on.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath

from .timefmt import iso, norm_ts

TIMELINE_FILE = "timeline.jsonl"
FEATURE_ENV = "SPECIFY_FEATURE_DIRECTORY"


@dataclass(frozen=True)
class TimelineEntry:
    ts: str
    session_id: str
    work_root: str
    feature_dir: str | None
    feature_source: str
    branch: str | None


def relative_dir(value: str, work: Path) -> str | None:
    """A feature directory as a POSIX path relative to ``work``; None when it lies outside."""
    text = value.strip().replace("\\", "/")
    if not text:
        return None
    windows = PureWindowsPath(text)
    if windows.drive and not windows.is_absolute():
        return None  # drive-relative Windows paths depend on a per-drive current directory
    try:
        base = Path(work).resolve()
        target = (base / text).resolve()
        relative = target.relative_to(base).as_posix()
    except (OSError, ValueError, RuntimeError):
        return None
    return relative if relative != "." else None



def active_feature(work: Path, env: Mapping[str, str]) -> tuple[str | None, str]:
    """The feature Spec Kit would use in ``work``: (relative POSIX dir, "env" | "feature.json" | "none")."""
    override = env.get(FEATURE_ENV, "")
    if override.strip():
        found = relative_dir(override, work)
        return (found, "env") if found else (None, "none")
    try:
        data = json.loads((Path(work) / ".specify" / "feature.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None, "none"
    value = data.get("feature_directory") if isinstance(data, dict) else None
    found = relative_dir(value, work) if isinstance(value, str) else None
    return (found, "feature.json") if found else (None, "none")


def make_entry(session_id: str, work: Path, env: Mapping[str, str], branch: str | None,
               now: datetime) -> TimelineEntry:
    feature_dir, source = active_feature(work, env)
    return TimelineEntry(iso(now), session_id, str(work), feature_dir, source, branch)


def append(runtime: Path, entry: TimelineEntry) -> None:
    """Append one line with a single write (safe for concurrent sessions)."""
    runtime = Path(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"v": 1, **asdict(entry)}, ensure_ascii=False) + "\n"
    with (runtime / TIMELINE_FILE).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)


def read(runtime: Path) -> list[TimelineEntry]:
    """All readable entries in file order; undecodable or invalid lines are skipped."""
    try:
        raw_lines = (Path(runtime) / TIMELINE_FILE).read_bytes().splitlines()
    except OSError:
        return []
    entries: list[TimelineEntry] = []
    for raw in raw_lines:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        ts = norm_ts(data.get("ts"))
        session_id = data.get("session_id")
        if ts is None or not isinstance(session_id, str):
            continue
        feature_dir = data.get("feature_dir")
        branch = data.get("branch")
        entries.append(TimelineEntry(
            ts, session_id, str(data.get("work_root") or ""),
            feature_dir if isinstance(feature_dir, str) else None,
            str(data.get("feature_source") or "none"),
            branch if isinstance(branch, str) else None,
        ))
    return entries


def by_session(entries: Iterable[TimelineEntry]) -> dict[str, list[TimelineEntry]]:
    grouped: dict[str, list[TimelineEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.session_id, []).append(entry)
    for items in grouped.values():
        items.sort(key=lambda e: e.ts)
    return grouped
