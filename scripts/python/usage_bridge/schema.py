"""In-memory upgrade of feature sources; never rewrite other authors."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


def normalize_source(data: Mapping[str, Any]) -> dict[str, Any]:
    if data.get("schema") != "usage-bridge/feature-usage" or data.get("schema_version") not in (1, 2):
        raise ValueError("unsupported feature source schema")
    result = copy.deepcopy(dict(data))
    result["schema_version"] = 2
    sessions = result.get("sessions", [])
    if not isinstance(sessions, list):
        raise ValueError("invalid sessions collection")
    for session in sessions:
        if (not isinstance(session, dict) or not isinstance(session.get("session_id"), str)
                or not isinstance(session.get("runs", []), list)
                or any(not isinstance(run, dict) for run in session.get("runs", []))):
            raise ValueError("invalid session entry")
        session.setdefault("runtime", "claude")
        session.setdefault("measurement", "exact")
        session.setdefault("reasons", [])
        session.setdefault("capabilities", {"request_counts": session["runtime"] == "claude",
                                             "subagents": session["runtime"] == "claude",
                                             "compaction": session["runtime"] == "claude",
                                             "splitting": session["runtime"] == "claude"})
    return result
