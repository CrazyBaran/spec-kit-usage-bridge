"""Output formats (spec §4): per-author JSON, the merged Markdown view and the report views.

Everything here is a pure function of its inputs except ``write_if_changed``; the same inputs always
render to the same bytes, whoever renders them.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .timefmt import parse_ts

SCHEMA_FEATURE = "usage-bridge/feature-usage"
SCHEMA_REPORT = "usage-bridge/feature-report"
SCHEMA_REPO = "usage-bridge/repo-report"
SCHEMA_VERSION = 1
RUNTIME = "claude"
EMPTY = "—"


# -- formatting ----------------------------------------------------------------------------------

def fmt_tokens(n: int) -> str:
    """Compact token count: 999, 4.1k, 212k, 17.6M."""
    n = int(n or 0)
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}k"
    thousands = round(n / 1000)
    if thousands < 1000:
        return f"{thousands}k"
    return f"{n / 1_000_000:.1f}M"


def fmt_cost(x: float | None) -> str:
    return EMPTY if x is None else f"${x:.2f}"


def fmt_ts(value: str | None) -> str:
    if not value:
        return EMPTY
    try:
        return parse_ts(value).strftime("%m-%d %H:%M")
    except ValueError:
        return EMPTY


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    return value


def dump_json(obj: Any) -> str:
    """Stable JSON text: key order kept, floats rounded to 6 decimals, UTF-8 characters as-is, LF."""
    return json.dumps(_rounded(obj), indent=2, ensure_ascii=False) + "\n"


# -- per-author source file ----------------------------------------------------------------------

def author_file(feature_id: str, feature_dir: str, author: str, machine: str, generator: dict[str, str],
                sessions: list[dict[str, Any]], completeness: str, partial_reasons: list[str],
                unpriced: list[str]) -> dict[str, Any]:
    ordered = sorted(sessions, key=lambda s: (s.get("first_ts") or "", s.get("session_id") or ""))
    stamps = [s.get("last_ts") for s in ordered if s.get("last_ts")]
    return {
        "schema": SCHEMA_FEATURE,
        "schema_version": SCHEMA_VERSION,
        "feature": {"id": feature_id, "directory": feature_dir},
        "author": {"name": author, "machine": machine},
        "generator": dict(generator),
        "runtime": RUNTIME,
        "completeness": completeness,
        "partial_reasons": list(partial_reasons),
        "data_as_of": max(stamps) if stamps else None,
        "unpriced_models": sorted(unpriced),
        "sessions": ordered,
    }


# -- safe writes ---------------------------------------------------------------------------------

def write_if_changed(path: Path, text: str, log: logging.Logger | None = None) -> bool:
    """Atomically replace ``path`` with ``text`` (LF) unless it already holds the same content.

    The comparison ignores CRLF/LF differences so ``core.autocrlf`` checkouts are not rewritten. A
    failed replace (e.g. a Windows sharing violation) is retried once, then skipped; the original
    file is left untouched and no temp file remains. Returns True only when the file was written.
    """
    path = Path(path)
    wanted = text.replace("\r\n", "\n")
    try:
        if path.read_text(encoding="utf-8").replace("\r\n", "\n") == wanted:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(wanted)
    except OSError as exc:
        _discard(tmp)
        if log:
            log.warning("cannot write %s: %s", path, exc)
        return False
    for attempt in range(2):
        try:
            os.replace(tmp, path)
            return True
        except OSError as exc:
            if attempt == 0:
                time.sleep(0.05)
                continue
            if log:
                log.warning("cannot replace %s: %s", path, exc)
    _discard(tmp)
    return False


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
