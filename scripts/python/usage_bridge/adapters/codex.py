"""Project-owned local Codex rollout discovery and parsing."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from ..config import Config
from ..digest import Event, SessionDigest
from ..paths import is_inside
from ..timefmt import norm_ts
from .base import Capabilities, ParseContext, SourceDescriptor
from .codex_usage import reconcile_snapshots


class CodexAdapter:
    @staticmethod
    def _metadata(path: Path, context: ParseContext | None = None) -> dict[str, Any]:
        meta, workspaces = {}, set()
        complete = True
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                if context and context.expired():
                    complete = False
                    break
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
                    continue
                payload = entry["payload"]
                if entry.get("type") == "session_meta" and not meta:
                    meta = dict(payload)
                if entry.get("type") in ("session_meta", "turn_context") and isinstance(payload.get("cwd"), str):
                    workspaces.add(payload["cwd"])
        return {**meta, "_workspace_roots": sorted(workspaces), "_indexed_complete": complete, "_index_version": 2}

    def discover(self, context: ParseContext, config: Config) -> Iterator[SourceDescriptor]:
        home = Path(context.env.get("CODEX_HOME") or str(Path.home() / ".codex")).expanduser()
        roots = [home / "sessions", home / "archived_sessions",
                 *(Path(folder).expanduser() for folder in config.codex_extra_dirs)]
        index_path = context.runtime_dir / "codex-index.json"
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(index, dict):
                index = {}
        except (OSError, ValueError):
            index = {}
        found: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for root in roots:
            if not root.is_dir():
                continue
            for directory, _, filenames in os.walk(root):
                if context.expired():
                    break
                for name in filenames:
                    if context.expired():
                        break
                    if not name.endswith(".jsonl"):
                        continue
                    path = Path(directory) / name
                    marker = os.path.normcase(str(path.absolute()))
                    if marker in seen:
                        continue
                    seen.add(marker)
                    try:
                        stat = path.stat()
                        stamp = [str(path), stat.st_size, stat.st_mtime_ns]
                        saved = index.get(marker, {})
                        old_meta = saved.get("meta") or {}
                        valid = (saved.get("stamp") == stamp and old_meta.get("_index_version") == 2
                                 and old_meta.get("_indexed_complete"))
                        meta = old_meta if valid else self._metadata(path, context)
                    except OSError:
                        continue
                    index[marker] = {"stamp": stamp, "meta": meta}
                    if not isinstance(meta, dict):
                        continue
                    if not any(is_inside(root, context.checkouts) for root in meta.get("_workspace_roots", [])):
                        continue
                    session = meta.get("id") or meta.get("session_id")
                    if not isinstance(session, str) or not session:
                        continue
                    record = found.setdefault(session, {"paths": [], "meta": meta, "stamps": []})
                    record["paths"].append(path)
                    record["stamps"].append(tuple(stamp))
        try:
            context.runtime_dir.mkdir(parents=True, exist_ok=True)
            temp = index_path.with_suffix(".tmp")
            temp.write_text(json.dumps(index), encoding="utf-8")
            os.replace(temp, index_path)
        except OSError:
            pass
        for session, native in sorted(found.items()):
            yield SourceDescriptor("codex", session, "rollout", native, tuple(native["stamps"]))

    def parse(self, source: SourceDescriptor, context: ParseContext):
        return parse_rollout(source, context)

    def record(self, payload: Mapping[str, Any], context: ParseContext) -> None:
        pass  # Codex owns its local rollout.


def invocation(text: str) -> str | None:
    match = re.match(r"\s*([/$]speckit[.\-][A-Za-z0-9_.\-]+)(?:\s|$)", text)
    if not match:
        match = re.match(r"\s*\[([/$]speckit[.\-][A-Za-z0-9_.\-]+)\]\(", text)
    return match.group(1) if match else None


def parse_rollout(source: SourceDescriptor, context: ParseContext) -> SessionDigest:
    histories = []
    reasons = set()
    for path in source.native["paths"]:
        entries = []
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                if context.expired():
                    reasons.add("deadline")
                    break
                try:
                    entry = json.loads(line)
                except ValueError:
                    reasons.add("malformed-record")
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
        histories.append(entries)
    histories.sort(key=len, reverse=True)
    entries = histories[0] if histories else []
    if any(entries[:len(other)] != other for other in histories[1:]):
        reasons.add("conflicting-session-copies")
        # Only the prefix agreed by every copy is trustworthy after divergence.
        common_length = min(map(len, histories))
        for index, copies in enumerate(zip(*histories)):
            if any(copy != copies[0] for copy in copies[1:]):
                common_length = index
                break
        entries = entries[:common_length]
    meta = source.native["meta"]
    events, counters, branches = [], [], []
    model, native_turn = "unknown", None
    first_ts = last_ts = None
    counter_event = None
    ambiguous_interval = False
    workspace = meta.get("cwd")
    interval_workspaces = {workspace} if isinstance(workspace, str) else set()
    owned_workspaces = set()
    for ordinal, entry in enumerate(entries):
        ts = norm_ts(entry.get("timestamp"))
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        kind = entry.get("type")
        if kind == "turn_context":
            model = payload.get("model") or "unknown"
            native_turn = payload.get("turn_id")
            if isinstance(payload.get("cwd"), str):
                workspace = payload["cwd"]
            if isinstance(workspace, str):
                interval_workspaces.add(workspace)
        owned = isinstance(workspace, str) and is_inside(workspace, context.checkouts)
        if owned:
            owned_workspaces.add(workspace)
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
        if kind == "session_meta" and owned:
            git = payload.get("git") or {}
            if isinstance(git, dict) and git.get("branch"):
                branches.append((ts, git["branch"]))
        text = None
        if kind == "event_msg" and payload.get("type") == "user_message":
            text = payload.get("message")
        elif kind == "response_item" and payload.get("role") == "user":
            content = payload.get("content") or []
            text = "\n".join(str(block.get("text", "")) for block in content if isinstance(block, dict))
            # Core emits both user_message and response_item; only one boundary.
            if events and events[-1].ts == ts:
                continue
        if isinstance(text, str) and owned:
            name = invocation(text)
            events.append(Event("command" if name else "prompt", ts, name=name,
                                prompt=text.strip()[:120] if context.keep_previews and not name else None,
                                ordinal=ordinal, native_id=native_turn))
        if kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            phase_boundaries = [index for index, event in enumerate(events) if event.kind == "command"]
            uncertain_interval = (len(phase_boundaries) > 1 if counter_event is None
                                  else any(index > counter_event for index in phase_boundaries))
            if uncertain_interval:
                ambiguous_interval = True
                reasons.add("phase-interval-ambiguous")
            mixed_ownership = len(interval_workspaces) > 1
            if mixed_ownership and any(is_inside(root, context.checkouts) for root in interval_workspaces):
                reasons.add("workspace-interval-ambiguous")
            event_index = -2 if not owned or mixed_ownership else (-1 if uncertain_interval else len(events) - 1)
            counters.append({"usage": info.get("total_token_usage") if isinstance(info, dict) else None,
                             "ts": ts, "model": model,
                             "event_index": event_index})
            counter_event = len(events) - 1
            interval_workspaces.clear()
        elif isinstance(workspace, str):
            interval_workspaces.add(workspace)
    requests, counter_reasons = reconcile_snapshots(counters)
    requests = [row for row in requests if row.event_index != -2]
    for row in requests:
        row.request_id = "codex:" + source.session_id + ":" + row.request_id.rsplit(":", 1)[-1]
    reasons.update(counter_reasons)
    parent = meta.get("forked_from_id") or meta.get("parent_thread_id")
    uncertain = ambiguous_interval or any(row.event_index < 0 for row in requests) or bool(parent)
    if parent:
        reasons.add("parent-attribution-unresolved")
    coverage_reasons = reasons - {"phase-interval-ambiguous", "parent-attribution-unresolved"}
    return SessionDigest(source.session_id, str(source.native["paths"][0]), first_ts, last_ts, last_ts,
                         sorted(owned_workspaces), branches, events, requests, runtime="codex",
                         measurement=("partial" if coverage_reasons else "exact") if requests else "activity_only",
                         reasons=sorted(reasons), capabilities=Capabilities(),
                         attribution_confidence="partial" if uncertain else "exact",
                         parent_identity=("codex", parent) if isinstance(parent, str) else None)
