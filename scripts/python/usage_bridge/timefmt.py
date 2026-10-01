"""One canonical timestamp form so string comparison is chronological (Review Focus 2).

Transcripts write ``…12.345Z``, upstream helpers return ``…+00:00`` or epoch numbers from
``.meta.json``; comparing those raw strings mis-orders them. Everything is normalised to
``YYYY-MM-DDTHH:MM:SS.mmmZ`` (UTC, milliseconds) before it is stored or compared.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

_ISO = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?"
    r"\s*(Z|[+-]\d{2}(?::?\d{2})?)?",
    re.IGNORECASE,
)


def parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC datetime (naive values count as UTC)."""
    match = _ISO.fullmatch(value.strip())
    if not match:
        raise ValueError(f"not an ISO-8601 timestamp: {value!r}")
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    micro = int((fraction or "0")[:6].ljust(6, "0"))
    dt = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0), micro,
                  tzinfo=timezone.utc)
    if zone and zone.upper() != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
        dt -= sign * offset
    return dt


def iso(dt: datetime) -> str:
    """Canonical form of a datetime (naive values count as UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def norm_ts(value: Any) -> str | None:
    """Canonical timestamp for an ISO string or epoch seconds/milliseconds; None when unparseable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 1e11 else float(value)
        try:
            return iso(datetime.fromtimestamp(seconds, tz=timezone.utc))
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return iso(parse_ts(value))
        except ValueError:
            return None
    return None
