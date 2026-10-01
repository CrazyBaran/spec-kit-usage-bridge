#!/usr/bin/env python3
"""Compare Usage Bridge transcript totals with the vendored token-usage CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/python"))

from usage_bridge.digest import digest_session  # noqa: E402
from usage_bridge.discovery import discover  # noqa: E402

VENDOR_SCRIPT = ROOT / "scripts/python/vendor/token_usage/scripts/token_usage.py"
USAGE_KEYS = ("input", "output", "cache_read", "cache_5m", "cache_1h")


def _sum_ours(path: Path) -> dict[str, int]:
    sessions = discover([], [], [path.parent])
    files = next((item for item in sessions if item.main == path), None)
    if files is None:
        raise ValueError(f"cannot discover transcript: {path}")
    digest = digest_session(files)
    totals = {key: 0 for key in USAGE_KEYS}
    requests = [*digest.requests, *(request for agent in digest.subagents for request in agent.requests)]
    for request in requests:
        for key in USAGE_KEYS:
            totals[key] += getattr(request, key)
    return totals


def upstream_usage(path: Path) -> dict[str, int]:
    """Read the vendor's authoritative total for one transcript without a persistent ledger."""
    with tempfile.TemporaryDirectory(prefix="usage-bridge-reconcile-") as runtime:
        env = dict(os.environ)
        env["TOKEN_USAGE_LEDGER_DIR"] = runtime
        env["XDG_CONFIG_HOME"] = str(Path(runtime) / "no-overlay")
        result = subprocess.run(
            [sys.executable, str(VENDOR_SCRIPT), "json", str(path)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    data = json.loads(result.stdout)
    usage = data["total"]["usage"]
    return {key: int(usage[key]) for key in USAGE_KEYS}


def reconcile(transcripts: Sequence[Path]) -> list[dict[str, Any]]:
    rows = []
    for transcript in transcripts:
        path = Path(transcript)
        ours = _sum_ours(path)
        upstream = upstream_usage(path)
        rows.append({"transcript": str(path), "ours": ours, "upstream": upstream, "equal": ours == upstream})
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    rows = reconcile([Path(arg) for arg in (argv if argv is not None else sys.argv[1:])])
    print(f"{'TRANSCRIPT':60} {'EQUAL':5} USAGE (input/output/cache_read/cache_5m/cache_1h)")
    for row in rows:
        print(f"{row['transcript'][:60]:60} {str(row['equal']):5} {row['ours']}")
    return 0 if all(row["equal"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
