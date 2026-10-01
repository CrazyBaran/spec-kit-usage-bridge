"""From a session's events to runs (spec §3.1), plus the upstream-mode walk used by the oracle.

Spec Kit rules: core-phase commands and core-phase skills open a run of that phase, user-typed
extension commands open an extension run, built-in session commands are transparent, any other
command opens an "other" run, plain prompts stick to the current run and every other skill folds
into it. ``upstream_segments`` replays token-usage's own rules (every command and every skill opens
a segment) so ``tests/test_oracle.py`` can prove the digest reproduces ``parse_session`` exactly.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters.base import Capabilities
from .digest import Request, SessionDigest, SubagentDigest

CORE_PHASES = ("constitution", "specify", "clarify", "plan", "checklist", "tasks", "analyze", "implement",
               "taskstoissues")
BUILTIN_COMMANDS = frozenset((
    "/add-dir", "/agents", "/bug", "/clear", "/compact", "/config", "/context", "/cost", "/doctor", "/effort",
    "/exit", "/export", "/fast", "/help", "/hooks", "/ide", "/login", "/logout", "/mcp", "/memory", "/model",
    "/permissions", "/release-notes", "/resume", "/rewind", "/status", "/statusline", "/terminal-setup", "/theme",
    "/upgrade", "/usage", "/vim",
))
NO_COMMAND = "(no command)"
_BUCKET_KEYS = ("input", "output", "cache_read", "cache_5m", "cache_1h")


@dataclass(frozen=True)
class Invocation:
    kind: str  # core | extension | builtin | other
    phase: str


@dataclass
class Run:
    session_id: str
    kind: str
    phase: str
    label: str
    start_ts: str | None
    end_ts: str | None
    requests: list[Request] = field(default_factory=list)
    subagents: list[SubagentDigest] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    last_branch: str | None = None
    prompt_preview: str | None = None
    after_clear: bool = False
    runtime: str = "claude"
    measurement: str = "exact"
    reasons: list[str] = field(default_factory=list)
    capabilities: Capabilities = field(default_factory=lambda: Capabilities(True, True, True, True))
    attribution_confidence: str = "exact"


def _lead(name: str) -> str:
    """The invocation without its leading ``/`` or ``$`` and without a ``<namespace>:`` prefix."""
    lead = name.strip().lstrip("/$")
    return lead.split(":", 1)[1] if ":" in lead else lead


def classify_command(name: str, extension_ids: Sequence[str]) -> Invocation:
    raw = name.strip()
    lead = _lead(raw)
    if lead.startswith("speckit."):
        parts = lead[len("speckit."):].split(".")
        if len(parts) == 1 and parts[0] in CORE_PHASES:
            return Invocation("core", parts[0])
        if len(parts) >= 2 and parts[0]:
            return Invocation("extension", f"{parts[0]}.{'.'.join(parts[1:])}")
        return Invocation("extension", lead)
    if lead.startswith("speckit-"):
        rest = lead[len("speckit-"):]
        if rest in CORE_PHASES:
            return Invocation("core", rest)
        matches = [e for e in extension_ids if e and rest.startswith(e + "-") and len(rest) > len(e) + 1]
        if matches:
            ext = max(matches, key=len)
            return Invocation("extension", f"{ext}.{rest[len(ext) + 1:]}")
        return Invocation("extension", lead)
    if raw in BUILTIN_COMMANDS:
        return Invocation("builtin", raw)
    return Invocation("other", "other")


def skill_phase(skill: str) -> str | None:
    """The core phase a Skill tool use starts, or None for every other skill."""
    lead = _lead(skill)
    for prefix in ("speckit-", "speckit."):
        if lead.startswith(prefix) and lead[len(prefix):] in CORE_PHASES:
            return lead[len(prefix):]
    return None


def installed_extension_ids(project: Path) -> list[str]:
    """Extension ids from ``.specify/extensions/.registry`` (used to split ``/speckit-<ext>-<cmd>``)."""
    try:
        data = json.loads((Path(project) / ".specify" / "extensions" / ".registry").read_text(encoding="utf-8"))
        return sorted(str(key) for key in data["extensions"])
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _requests_by_event(digest: SessionDigest) -> dict[int, list[Request]]:
    grouped: dict[int, list[Request]] = {}
    for request in digest.requests:
        grouped.setdefault(request.event_index, []).append(request)
    return grouped


def _latest_start_index(starts: list[tuple[str, int]], ts: str | None) -> int | None:
    """Index of the latest-starting unit with start <= ts (upstream's subagent assignment rule)."""
    found = None
    if ts:
        for start, index in sorted(starts):
            if start <= ts:
                found = index
    return found


def _branch_at(digest: SessionDigest, ts: str | None) -> str | None:
    branch = None
    for changed_at, value in digest.branches:
        if ts is None or changed_at is None or changed_at <= ts:
            branch = value
        else:
            break
    return branch


def build_runs(digest: SessionDigest, extension_ids: Sequence[str], *, include_empty: bool = False) -> list[Run]:
    runs: list[Run] = []
    current: Run | None = None
    first_request_event = digest.requests[0].event_index if digest.requests else None
    after_clear = False

    def open_run(kind: str, phase: str, label: str, ts: str | None, preview: str | None = None) -> Run:
        run = Run(digest.session_id, kind, phase, label, ts, None, prompt_preview=preview,
                  runtime=digest.runtime, measurement=digest.measurement, reasons=list(digest.reasons),
                  capabilities=digest.capabilities, attribution_confidence=digest.attribution_confidence)
        runs.append(run)
        return run

    def attach(request: Request) -> None:
        nonlocal current
        if current is None:
            current = open_run("other", "other", NO_COMMAND, request.ts)
        current.requests.append(request)

    by_event = _requests_by_event(digest)
    for request in by_event.get(-1, []):
        attach(request)
    for index, event in enumerate(digest.events):
        if event.kind == "command" and event.name:
            invocation = classify_command(event.name, extension_ids)
            if invocation.kind in ("core", "extension"):
                current = open_run(invocation.kind, invocation.phase, event.name, event.ts)
            elif invocation.kind == "builtin":
                if event.name == "/clear" and (first_request_event is None or index <= first_request_event):
                    after_clear = True
            else:
                current = open_run("other", "other", event.name, event.ts)
        elif event.kind == "prompt":
            if current is None:
                current = open_run("other", "other", NO_COMMAND, event.ts, event.prompt)
            elif current.prompt_preview is None and event.prompt:
                current.prompt_preview = event.prompt
        elif event.kind == "skill" and event.name:
            phase = skill_phase(event.name)
            if phase:
                current = open_run("core", phase, "/" + event.name, event.ts)
            else:
                if current is None:
                    current = open_run("other", "other", "/" + event.name, event.ts)
                if event.name not in current.skills:
                    current.skills.append(event.name)
        for request in by_event.get(index, []):
            attach(request)
        if current and event.ts:
            current.end_ts = event.ts

    starts = [(run.start_ts, i) for i, run in enumerate(runs) if run.start_ts]
    for sub in digest.subagents:
        if not sub.requests:
            continue
        index = _latest_start_index(starts, sub.start_ts)
        if index is None:
            index = len(runs) - 1 if runs else None
        if index is None:
            open_run("other", "other", NO_COMMAND, sub.start_ts)
            index = 0
        runs[index].subagents.append(sub)

    kept: list[Run] = []
    for run in runs:
        if (not include_empty and digest.runtime == "claude" and not run.requests
                and not any(sub.requests for sub in run.subagents)):
            continue
        stamps = [r.ts for r in run.requests if r.ts] + [s.last_ts for s in run.subagents if s.last_ts]
        run.end_ts = max(stamps) if stamps else (run.end_ts or run.start_ts)
        last_main = run.requests[-1].ts if run.requests else run.end_ts
        run.last_branch = _branch_at(digest, last_main)
        run.after_clear = after_clear
        kept.append(run)
    return kept


def _add(bucket_owner: dict[str, dict[str, int]], model: str, flat: dict[str, int], requests: int = 1) -> None:
    bucket = bucket_owner.setdefault(model, {key: 0 for key in (*_BUCKET_KEYS, "requests")})
    for key in _BUCKET_KEYS:
        bucket[key] += flat[key]
    bucket["requests"] += requests


def upstream_segments(digest: SessionDigest) -> list[dict[str, Any]]:
    """token-usage's segmentation replayed on the digest: [{"label", "by_model"}] like parse_session."""
    segments: list[dict[str, Any]] = []

    def open_segment(label: str, ts: str | None) -> None:
        segments.append({"label": label, "start_ts": ts, "by_model": {}})

    def attach(request: Request) -> None:
        if not segments:
            open_segment(NO_COMMAND, request.ts)
        _add(segments[-1]["by_model"], request.model, request.flat())

    by_event = _requests_by_event(digest)
    for request in by_event.get(-1, []):
        attach(request)
    for index, event in enumerate(digest.events):
        if event.kind == "command" and event.name:
            open_segment(event.name, event.ts)
        elif event.kind == "prompt" and not segments:
            open_segment(NO_COMMAND, event.ts)
        elif event.kind == "skill" and event.name:
            open_segment("/" + event.name, event.ts)
        for request in by_event.get(index, []):
            attach(request)

    starts = [(seg["start_ts"], i) for i, seg in enumerate(segments) if seg["start_ts"]]
    for sub in digest.subagents:
        if not sub.requests:
            continue
        index = _latest_start_index(starts, sub.start_ts)
        if index is None:
            index = len(segments) - 1 if segments else None
        if index is None:
            open_segment(NO_COMMAND, sub.start_ts)
            index = 0
        for request in sub.requests:
            _add(segments[index]["by_model"], request.model, request.flat())
    return [{"label": seg["label"], "by_model": seg["by_model"]} for seg in segments]
