"""Translate supported vendored Cursor segments without inventing requests."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from .. import tu_compat
from ..config import Config
from ..digest import Event, Request, SessionDigest
from ..timefmt import norm_ts
from .base import Capabilities, ParseContext, SourceDescriptor
from .codex import invocation
from .cursor_ledger import append_event


class CursorAdapter:
    def discover(self, context: ParseContext, config: Config) -> Iterator[SourceDescriptor]:
        candidates = []
        for project in context.checkouts:
            if context.expired():
                break
            data_root = Path(config.cursor_data_dir).expanduser() if config.cursor_data_dir else None
            candidates.extend(tu_compat.cursor_sessions(project, context.runtime_dir / "cursor-ledgers", data_root,
                                                       timeout=context.deadline - context.clock()))
        for folder in config.cursor_extra_dirs:
            for path in Path(folder).expanduser().glob("*.json"):
                if context.expired():
                    break
                try:
                    source = tu_compat.cursor_export(path, timeout=context.deadline - context.clock(),
                                                    checkouts=context.checkouts)
                    if source:
                        candidates.append(source)
                except (OSError, ValueError, AttributeError):
                    continue
        seen = set()
        order = {"hook_ledger": 0, "cloud_export": 1, "sqlite": 2}
        for session in sorted(candidates, key=lambda s: order[s.source]):
            if session.composer_id in seen:
                continue
            seen.add(session.composer_id)
            path = session.ledger_path or session.export_path or session.db_path
            try:
                stat = path.stat()
                stamps = [(str(path), stat.st_size, stat.st_mtime_ns)]
                if session.source == "sqlite":
                    for suffix in ("-wal", "-shm"):
                        sidecar = Path(str(path) + suffix)
                        if sidecar.exists():
                            info = sidecar.stat()
                            stamps.append((str(sidecar), info.st_size, info.st_mtime_ns))
            except OSError:
                continue
            yield SourceDescriptor("cursor", session.composer_id, session.source, session, tuple(stamps))

    def record(self, payload: Mapping[str, Any], context: ParseContext) -> None:
        append_event(payload, context)

    def parse(self, source: SourceDescriptor, context: ParseContext) -> SessionDigest:
        parsed = tu_compat.cursor_parse(source.native, timeout=context.deadline - context.clock())
        quality = parsed.get("measurement", "activity_only")
        events, requests = [], []
        first_ts = last_ts = None
        for index, segment in enumerate(parsed.get("segments", [])):
            ts = norm_ts(segment.get("start_ts"))
            first_ts = first_ts or ts
            last_ts = ts or last_ts
            text = segment.get("prompt") or segment.get("label") or ""
            name = invocation(text)
            events.append(Event("command" if name else "prompt", ts, name=name,
                                prompt=text[:120] if context.keep_previews and not name else None, ordinal=index))
            buckets = segment.get("by_model") or {"unknown": {}}
            for model, bucket in buckets.items():
                keys = ("input", "output", "cache_read", "cache_5m", "cache_1h")
                explicit_zero = model in parsed.get("_measured_zero", {}).get(str(index), [])
                measured = explicit_zero or (quality != "activity_only" and any(bucket.get(k) for k in keys))
                row_quality = "exact" if explicit_zero and quality == "activity_only" else quality
                values = [bucket.get(k, 0) if measured else None for k in
                          ("input", "output", "cache_read", "cache_5m", "cache_1h")]
                requests.append(Request(f"cursor:{source.session_id}:{index}:{model}", ts, model, *values,
                                        index, kind="segment",
                                        measurement=row_quality if measured else "activity_only"))
        reasons = ["source-warning"] if parsed.get("warnings") else []
        if quality == "activity_only" and any(row.measurement != "activity_only" for row in requests):
            quality = "exact"
        if any(row.measurement == "activity_only" for row in requests) and quality != "activity_only":
            quality = "partial"
            reasons.append("missing-segment-usage")
        path = source.native.ledger_path or source.native.export_path or source.native.db_path
        branches = [(norm_ts(ts), branch) for ts, branch in parsed.get("_branches", [])]
        return SessionDigest(source.session_id, str(path), first_ts, last_ts, last_ts,
                             branches=branches, events=events, requests=requests, runtime="cursor", measurement=quality,
                             reasons=reasons, capabilities=Capabilities())
