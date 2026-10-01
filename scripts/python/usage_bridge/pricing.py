"""Runtime-aware API-equivalent costs; unknown prices remain unavailable."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import tu_compat
from .tu_compat import Rates

TABLE = Path(__file__).parent / "data" / "openai-pricing.json"


def provenance() -> dict[str, str]:
    raw = TABLE.read_bytes()
    return {"openai_pricing": json.loads(raw)["retrieved"], "openai_pricing_sha256": hashlib.sha256(raw).hexdigest()}


def estimate(runtime: str, model: str, usage: Mapping[str, int | None], rates: Rates,
             measurement: str = "exact") -> dict[str, Any]:
    if runtime == "codex" or model.startswith("gpt-"):
        table = json.loads(TABLE.read_text(encoding="utf-8"))["models"]
        table.update(rates.table)
        # Bundled OpenAI rates accept exact names; team overrides retain prefix matching.
        rate = table.get(model)
        if rate is None:
            prefixes = [key for key in rates.table if model.startswith(key)]
            rate = table[max(prefixes, key=len)] if prefixes else None
    else:
        rate = tu_compat.rate_of(model, rates)
    if not rate:
        return {"cost_usd": None, "known_cost_usd": None, "reasons": ["unpriced-model"]}
    factors = {"input": rate["input"], "output": rate["output"], "cache_read": rate.get("cache_read"),
               "cache_5m": rate["input"] * 1.25 if runtime != "codex" else None,
               "cache_1h": rate["input"] * 2 if runtime != "codex" else None}
    known = sum(value * factors[key] / 1e6 for key, value in usage.items()
                if key in factors and value is not None and factors[key] is not None)
    complete = measurement == "exact" and all(value is not None and (value == 0 or factors.get(key) is not None)
                                               for key, value in usage.items())
    return {"cost_usd": known if complete else None, "known_cost_usd": known,
            "reasons": [] if complete else ["incomplete-cost-coverage"]}
