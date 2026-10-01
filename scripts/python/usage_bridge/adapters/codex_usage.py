"""Conservative accounting of cumulative Codex counters."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from ..digest import Request, SessionDigest


def reconcile_snapshots(entries: Sequence[Mapping[str, Any]]) -> tuple[list[Request], list[str]]:
    previous = (0, 0, 0)
    observations: list[Request] = []
    reasons: set[str] = set()
    for entry in entries:
        usage = entry.get("usage")
        if not isinstance(usage, dict):
            reasons.add("missing-usage")
            continue
        values = tuple(usage.get(key) for key in ("input_tokens", "cached_input_tokens", "output_tokens"))
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in values):
            reasons.add("invalid-token-buckets")
            continue
        inp, cached, out = values
        reasoning = usage.get("reasoning_output_tokens", 0)
        if cached > inp or not isinstance(reasoning, int) or reasoning < 0 or reasoning > out:
            reasons.add("invalid-token-buckets")
            continue
        if any(current < old for current, old in zip(values, previous)):
            reasons.add("counter-reset")
            continue
        delta = tuple(current - old for current, old in zip(values, previous))
        if delta[1] > delta[0]:
            reasons.add("invalid-cache-delta")
            continue
        if not any(delta):
            continue
        row_reasons = []
        if usage.get("cache_write_input_tokens", 0):
            row_reasons.append("cache-write-duration-unknown")
        if usage.get("total_tokens", inp + out) != inp + out:
            row_reasons.append("synthetic-total")
        reasons.update(row_reasons)
        identity = hashlib.sha256(json.dumps([entry.get("ts"), values], separators=(",", ":")).encode()).hexdigest()
        observations.append(Request(
            "codex:" + identity, entry.get("ts"), entry.get("model") or "unknown",
            delta[0] - delta[1], delta[2], delta[1], None if row_reasons else 0, None if row_reasons else 0,
            entry.get("event_index", -1), kind="counter_delta",
            measurement="partial" if row_reasons else "exact", reasons=row_reasons,
        ))
        previous = values
    return observations, sorted(reasons)


def exclude_inherited_prefix(child: SessionDigest, parent: SessionDigest) -> SessionDigest:
    if child.parent_identity != (parent.runtime, parent.session_id):
        return child
    prefix = 0
    for child_row, parent_row in zip(child.requests, parent.requests):
        if child_row.request_id != parent_row.request_id:
            break
        prefix += 1
    if not prefix:
        return replace(child, requests=[], measurement="activity_only",
                       reasons=sorted(set(child.reasons + ["inherited-usage-ambiguous"])))
    return replace(child, requests=child.requests[prefix:])
