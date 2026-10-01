"""One request-level pass over a session's transcripts (spec §2.5, Approach B).

The pass mirrors upstream ``parse_session``/``sum_transcript`` exactly where usage is concerned —
same prompt detection, same requestId dedup (per-field maxima for streamed duplicates), same
handling of entries without a requestId — but keeps every request with its timestamp and its
position among the session's events, which the phase rules, cross-file dedup, re-priming and
compaction metrics need. ``tests/test_oracle.py`` reconciles the two.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import tu_compat
from .adapters.base import Capabilities
from .discovery import SessionFiles
from .timefmt import norm_ts

DIGEST_VERSION = 1
PREVIEW_CHARS = 120


@dataclass
class Event:
    kind: str  # command | prompt | skill | compact
    ts: str | None
    name: str | None = None
    trigger: str | None = None
    pre_tokens: int | None = None
    post_tokens: int | None = None
    prompt: str | None = None
    ordinal: int | None = None
    native_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Event:
        return cls(**data)


@dataclass
class Request:
    request_id: str
    ts: str | None
    model: str
    input: int | None
    output: int | None
    cache_read: int | None
    cache_5m: int | None
    cache_1h: int | None
    event_index: int
    kind: str = "request"
    measurement: str = "exact"
    reasons: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Request:
        return cls(**data)

    def flat(self) -> dict[str, int | None]:
        return {"input": self.input, "output": self.output, "cache_read": self.cache_read,
                "cache_5m": self.cache_5m, "cache_1h": self.cache_1h}


@dataclass
class SubagentDigest:
    rel_path: str
    agent_type: str
    spawn_depth: int
    first_ts: str | None
    last_ts: str | None
    start_ts: str | None
    finished: bool
    requests: list[Request] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["requests"] = [r.to_json() for r in self.requests]
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SubagentDigest:
        values = dict(data)
        values["requests"] = [Request.from_json(r) for r in data.get("requests", [])]
        return cls(**values)


@dataclass
class SessionDigest:
    session_id: str
    main_path: str
    first_ts: str | None
    last_ts: str | None
    last_main_ts: str | None
    cwds: list[str] = field(default_factory=list)
    branches: list[tuple[str | None, str | None]] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)
    subagents: list[SubagentDigest] = field(default_factory=list)
    runtime: str = "claude"
    measurement: str = "exact"
    reasons: list[str] = field(default_factory=list)
    capabilities: Capabilities = field(default_factory=lambda: Capabilities(True, True, True, True))
    attribution_confidence: str = "exact"
    parent_identity: tuple[str, str] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id, "main_path": self.main_path, "first_ts": self.first_ts,
            "last_ts": self.last_ts, "last_main_ts": self.last_main_ts, "cwds": list(self.cwds),
            "branches": [[ts, branch] for ts, branch in self.branches],
            "events": [e.to_json() for e in self.events],
            "requests": [r.to_json() for r in self.requests],
            "subagents": [s.to_json() for s in self.subagents],
            "runtime": self.runtime, "measurement": self.measurement, "reasons": list(self.reasons),
            "capabilities": asdict(self.capabilities), "attribution_confidence": self.attribution_confidence,
            "parent_identity": self.parent_identity,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SessionDigest:
        return cls(
            data["session_id"], data["main_path"], data.get("first_ts"), data.get("last_ts"),
            data.get("last_main_ts"), list(data.get("cwds", [])),
            [(ts, branch) for ts, branch in data.get("branches", [])],
            [Event.from_json(e) for e in data.get("events", [])],
            [Request.from_json(r) for r in data.get("requests", [])],
            [SubagentDigest.from_json(s) for s in data.get("subagents", [])],
            data.get("runtime", "claude"), data.get("measurement", "exact"), list(data.get("reasons", [])),
            Capabilities(**data.get("capabilities", asdict(Capabilities(True, True, True, True)))),
            data.get("attribution_confidence", "exact"),
            tuple(data["parent_identity"]) if data.get("parent_identity") else None,
        )


class _RequestLog:
    """Upstream request semantics: one record per requestId, streamed duplicates merged by maxima."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self._pending: dict[str, tuple[Request, dict[str, int]]] = {}

    def add(self, entry: dict, message: dict, ts: str | None, ordinal: int, event_index: int) -> None:
        usage = message.get("usage")
        if not usage:
            return
        flat = tu_compat.normalize(usage)
        request_id = entry.get("requestId")
        if request_id and request_id in self._pending:
            record, maxima = self._pending[request_id]
            tu_compat.merge_max(maxima, flat)
            for key, value in maxima.items():
                setattr(record, key, value)
            return
        record = Request(request_id or f"noreq:{ordinal}", ts, message.get("model") or "unknown",
                         flat["input"], flat["output"], flat["cache_read"], flat["cache_5m"], flat["cache_1h"],
                         event_index)
        self.requests.append(record)
        if request_id:
            self._pending[request_id] = (record, dict(flat))


def _message(entry: dict) -> dict:
    message = entry.get("message")
    return message if isinstance(message, dict) else {}


def _read_meta(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _digest_subagent(sub_path: Path, meta_path: Path | None, subagents_dir: Path) -> SubagentDigest:
    log = _RequestLog()
    first_raw = None
    first_ts = last_ts = None
    finished = False
    for ordinal, entry in enumerate(tu_compat.iter_entries(sub_path)):
        raw = entry.get("timestamp")
        ts = norm_ts(raw)
        if raw and first_raw is None:
            first_raw = raw
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        if entry.get("type") == "assistant":
            message = _message(entry)
            finished = message.get("stop_reason") == "end_turn"
            log.add(entry, message, ts, ordinal, -1)
    meta = _read_meta(meta_path)
    start_ts = norm_ts(tu_compat.agent_start(sub_path, first_raw, meta))
    try:
        rel = sub_path.relative_to(subagents_dir).as_posix()
    except ValueError:
        rel = sub_path.name
    depth = meta.get("spawnDepth")
    return SubagentDigest(
        rel, str(meta.get("agentType") or "agent"), depth if isinstance(depth, int) else 1,
        first_ts, last_ts, start_ts, finished, log.requests,
    )


def digest_session(files: SessionFiles, keep_previews: bool = False) -> SessionDigest:
    events: list[Event] = []
    log = _RequestLog()
    cwds: list[str] = []
    branches: list[tuple[str | None, str | None]] = []
    seen_skills: set[str] = set()
    first_ts = last_ts = None
    for ordinal, entry in enumerate(tu_compat.iter_entries(files.main)):
        ts = norm_ts(entry.get("timestamp"))
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        cwd = entry.get("cwd")
        if isinstance(cwd, str) and cwd and cwd not in cwds:
            cwds.append(cwd)
        if "gitBranch" in entry:
            branch = entry.get("gitBranch") or None
            if not branches or branches[-1][1] != branch:
                branches.append((ts, branch))
        if tu_compat.is_prompt(entry):
            text = tu_compat.prompt_text(entry)
            name = tu_compat.command_name(text)
            if name:
                events.append(Event("command", ts, name=name))
            else:
                preview = None
                if keep_previews and not entry.get("isCompactSummary"):
                    preview = text.strip()[:PREVIEW_CHARS]
                events.append(Event("prompt", ts, prompt=preview))
            continue
        if entry.get("type") == "system" and entry.get("subtype") == "compact_boundary":
            meta = entry.get("compactMetadata") if isinstance(entry.get("compactMetadata"), dict) else {}
            events.append(Event("compact", ts, trigger=meta.get("trigger"), pre_tokens=meta.get("preTokens"),
                                post_tokens=meta.get("postTokens")))
            continue
        if entry.get("type") != "assistant":
            continue
        message = _message(entry)
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
                    skill = (block.get("input") or {}).get("skill")
                    use_id = block.get("id") or f"{entry.get('requestId')}:{skill}"
                    if skill and use_id not in seen_skills:
                        seen_skills.add(use_id)
                        events.append(Event("skill", ts, name=str(skill)))
        log.add(entry, message, ts, ordinal, len(events) - 1)
    subagents_dir = files.main.parent / files.main.stem / "subagents"
    subagents = [_digest_subagent(s.path, s.meta, subagents_dir) for s in files.subagents]
    session_last = max([t for t in [last_ts, *(s.last_ts for s in subagents)] if t], default=None)
    return SessionDigest(files.session_id, str(files.main), first_ts, session_last, last_ts, cwds, branches,
                         events, log.requests, subagents)


class DigestCache:
    """One JSON file per session under ``runtime/cache``; stale on any change of files, format or vendor."""

    def __init__(self, runtime: Path, vendored_sha: str) -> None:
        self.directory = Path(runtime) / "cache"
        self.vendored_sha = vendored_sha

    def _path(self, files: SessionFiles) -> Path:
        return self.directory / (hashlib.sha1(str(files.main).encode("utf-8")).hexdigest() + ".json")

    def _key(self, files: SessionFiles) -> list[list[Any]]:
        return [list(stamp) for stamp in files.key()]

    def load(self, files: SessionFiles, keep_previews: bool) -> SessionDigest | None:
        try:
            data = json.loads(self._path(files).read_text(encoding="utf-8"))
            if (data.get("v") != DIGEST_VERSION or data.get("vendored_sha") != self.vendored_sha
                    or data.get("keep_previews") != keep_previews or data.get("key") != self._key(files)):
                return None
            return SessionDigest.from_json(data["digest"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def store(self, files: SessionFiles, keep_previews: bool, digest: SessionDigest) -> None:
        payload = {"v": DIGEST_VERSION, "vendored_sha": self.vendored_sha, "keep_previews": keep_previews,
                   "key": self._key(files), "digest": digest.to_json()}
        path = self._path(files)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
