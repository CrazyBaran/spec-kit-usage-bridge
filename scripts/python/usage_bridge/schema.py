"""In-memory upgrade of feature sources; never rewrite other authors."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .measurement import QUALITY


def normalize_source(data: Mapping[str, Any], *, require_metadata: bool = True) -> dict[str, Any]:
    if data.get("schema") != "usage-bridge/feature-usage" or data.get("schema_version") not in (1, 2):
        raise ValueError("unsupported feature source schema")
    if require_metadata:
        for field, keys in (("author", ("name",)), ("feature", ("id", "directory"))):
            metadata = data.get(field)
            if (not isinstance(metadata, Mapping)
                    or any(not isinstance(metadata.get(key), str) or not metadata[key] for key in keys)):
                raise ValueError(f"invalid {field} metadata")
        if "machine" in data["author"] and not isinstance(data["author"]["machine"], str):
            raise ValueError("invalid author machine metadata")
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
        for row in [session, *session.get("runs", [])]:
            quality = row.get("measurement", session["measurement"])
            if not isinstance(quality, str) or quality not in QUALITY:
                raise ValueError("invalid measurement value")
        session.setdefault("reasons", [])
        session.setdefault("capabilities", {"request_counts": session["runtime"] == "claude",
                                             "subagents": session["runtime"] == "claude",
                                             "compaction": session["runtime"] == "claude",
                                             "splitting": session["runtime"] == "claude"})
    return result
