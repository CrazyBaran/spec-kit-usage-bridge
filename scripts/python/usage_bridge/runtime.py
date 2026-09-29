"""Which agent runtime sent the hook payload (spec §2.1).

v0.1 captures Claude Code only; Cursor payloads are recognised so they can be logged and ignored,
and the ``RuntimeAdapter`` shape leaves room for a Cursor implementation later (brief §5.8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

CLAUDE = "claude"
CURSOR = "cursor"
MANUAL = "manual"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Detected:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


def detect(raw: str) -> Detected:
    """Classify stdin: a Claude Stop payload, a Cursor payload, no payload (manual run) or garbage."""
    text = (raw or "").lstrip("﻿").strip()
    if not text:
        return Detected(MANUAL)
    try:
        payload = json.loads(text)
    except ValueError:
        return Detected(UNKNOWN)
    if not isinstance(payload, dict):
        return Detected(UNKNOWN)
    if not payload:
        return Detected(MANUAL)
    if isinstance(payload.get("transcript_path"), str) and isinstance(payload.get("session_id"), str):
        return Detected(CLAUDE, payload)
    if "conversation_id" in payload or "generation_id" in payload:
        return Detected(CURSOR, payload)
    return Detected(UNKNOWN)
