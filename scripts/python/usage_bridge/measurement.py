"""Known measured subtotals are distinct from complete usage."""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .digest import Request

BUCKETS = ("input", "output", "cache_read", "cache_5m", "cache_1h")
QUALITY = {"exact": 0, "partial": 1, "activity_only": 2}


def summarize(observations: Sequence[Request]) -> dict[str, Any]:
    measured = {key: sum(getattr(row, key) or 0 for row in observations) for key in BUCKETS}
    usage = {key: (None if any(getattr(row, key) is None for row in observations) else measured[key])
             for key in BUCKETS}
    quality = max((row.measurement for row in observations), key=lambda q: QUALITY[q], default="exact")
    return {"usage": usage, "measured_usage": measured, "measurement": quality,
            "reasons": sorted({reason for row in observations for reason in row.reasons})}
