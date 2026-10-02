"""Which agent runtime sent the hook payload (spec §2.1).

Native discriminators and verified integration hints keep overlapping payloads separate.
"""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CLAUDE = "claude"
CURSOR = "cursor"
CODEX = "codex"
MANUAL = "manual"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Detected:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


def detect(raw: str, integration_hint: str | None = None, *, probe: bool = True) -> Detected:
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
    hint = integration_hint or payload.get("integration") or payload.get("runtime")
    if hint is not None:
        return Detected(hint, payload) if hint in (CLAUDE, CURSOR, CODEX) else Detected(UNKNOWN)
    if payload.get("type") == "agent-turn-complete" and isinstance(payload.get("thread-id"), str):
        return Detected(CODEX, payload)
    if isinstance(payload.get("transcript_path"), str) and isinstance(payload.get("session_id"), str):
        if probe:
            try:
                path = Path(payload["transcript_path"])
                if stat.S_ISREG(path.stat().st_mode):
                    with path.open(encoding="utf-8-sig") as stream:
                        entry = json.loads(stream.readline(65536))
                    if isinstance(entry, dict) and entry.get("type") == "session_meta":
                        return Detected(CODEX, payload)
            except (OSError, ValueError):
                pass
        return Detected(CLAUDE, payload)
    if "conversation_id" in payload or "generation_id" in payload:
        return Detected(CURSOR, payload)
    return Detected(UNKNOWN)
