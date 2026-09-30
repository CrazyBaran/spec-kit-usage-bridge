"""Cross-file dedup and run → feature attribution (spec §2.6 step 2, §3.2).

Order: the timeline entry of the Stop that closed the run's last turn (when its feature directory
still exists) → the git branch of the run's last request, resolved against the known feature
directories → unattributed. Constitution runs are project-level.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from .digest import SessionDigest
from .phases import Run
from .timeline import TimelineEntry, relative_dir

_TIMESTAMP_TOKEN = re.compile(r"^(\d{8}-\d{6})(?:-|$)")
_NUMBER_TOKEN = re.compile(r"^(\d{3,})(?:-|$)")


@dataclass(frozen=True)
class Bucket:
    kind: str  # feature | project | unattributed
    feature_dir: str | None


@dataclass
class AttributedRun:
    run: Run
    bucket: Bucket
    attributed_by: str  # timeline | branch | none


def _synthetic(request_id: str) -> bool:
    return request_id.startswith("noreq:")


def dedup_across_sessions(digests: Sequence[SessionDigest]) -> tuple[list[SessionDigest], int]:
    """Drop requests already seen in an earlier session (a forked/copied transcript keeps the original)."""
    seen: set[str] = set()
    dropped = 0
    result: list[SessionDigest] = []
    for digest in sorted(digests, key=lambda d: (d.first_ts or "", d.session_id)):
        requests = [r for r in digest.requests if _synthetic(r.request_id) or r.request_id not in seen]
        subagents = []
        for sub in digest.subagents:
            kept = [r for r in sub.requests if _synthetic(r.request_id) or r.request_id not in seen]
            dropped += len(sub.requests) - len(kept)
            subagents.append(replace(sub, requests=kept))
        dropped += len(digest.requests) - len(requests)
        result.append(replace(digest, requests=requests, subagents=subagents))
        seen.update(r.request_id for r in requests)
        for sub in subagents:
            seen.update(r.request_id for r in sub.requests)
    return result, dropped


def existing_feature_dirs(work: Path, timeline: Sequence[TimelineEntry]) -> list[str]:
    """Feature directories that exist in the work root: ``specs/*`` plus every timeline directory still present."""
    work = Path(work)
    found: set[str] = set()
    specs = work / "specs"
    if specs.is_dir():
        for child in specs.iterdir():
            safe = relative_dir(f"specs/{child.name}", work)
            if safe and child.is_dir():
                found.add(safe)
    for entry in timeline:
        safe = relative_dir(entry.feature_dir, work) if entry.feature_dir else None
        if safe and (work / safe).is_dir():
            found.add(safe)
    return sorted(found)


def _unique(matches: list[str]) -> str | None:
    return matches[0] if len(matches) == 1 else None


def resolve_branch(branch: str | None, known: Sequence[str]) -> str | None:
    """Map a branch name to a known feature directory (spec §3.2 rules 1–3); None when unresolved or ambiguous."""
    if not branch:
        return None
    exact = [d for d in known if d in (f"specs/{branch}", branch)]
    if exact:
        return _unique(exact)
    segment = branch.rsplit("/", 1)[-1]
    by_name = [d for d in known if PurePosixPath(d).name == segment]
    if by_name:
        return _unique(by_name)
    token_match = _TIMESTAMP_TOKEN.match(segment) or _NUMBER_TOKEN.match(segment)
    if not token_match:
        return None
    token = token_match.group(1)
    prefixed = [d for d in known if PurePosixPath(d).name == token or PurePosixPath(d).name.startswith(token + "-")]
    return _unique(prefixed)


def _timeline_feature(run: Run, entries: Sequence[TimelineEntry]) -> str | None:
    if not run.requests:
        return None
    closing = run.requests[-1]
    for entry in entries:
        if (entry.last_request_id == closing.request_id and entry.last_request_ts == closing.ts
                and entry.ts >= closing.ts):
            return entry.feature_dir
    return None


def attribute_runs(runs: Sequence[Run], timeline_by_session: Mapping[str, list[TimelineEntry]],
                   known: Sequence[str]) -> list[AttributedRun]:
    known_set = set(known)
    attributed: list[AttributedRun] = []
    for run in runs:
        if run.phase == "constitution":
            attributed.append(AttributedRun(run, Bucket("project", None), "none"))
            continue
        feature = _timeline_feature(run, timeline_by_session.get(run.session_id, []))
        if feature and feature in known_set:
            attributed.append(AttributedRun(run, Bucket("feature", feature), "timeline"))
            continue
        resolved = resolve_branch(run.last_branch, known)
        if resolved:
            attributed.append(AttributedRun(run, Bucket("feature", resolved), "branch"))
        else:
            attributed.append(AttributedRun(run, Bucket("unattributed", None), "none"))
    return attributed
