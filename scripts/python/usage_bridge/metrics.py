"""Usage, cost, re-priming, splitting verdict, compactions and completeness (spec §3.3–3.5)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from . import tu_compat
from .attribution import AttributedRun
from .digest import Request, SessionDigest
from .measurement import summarize
from .phases import Run
from .pricing import estimate
from .timefmt import parse_ts
from .tu_compat import Rates

USAGE_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
_VENDOR_KEYS = ("input", "output", "cache_read", "cache_5m", "cache_1h")
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.0
TTL_5M_SECONDS = 300
TTL_1H_SECONDS = 3600


def _usage(requests: Iterable[Request]) -> dict[str, int]:
    total = dict.fromkeys(USAGE_KEYS, 0)
    for r in requests:
        total["input"] += r.input
        total["output"] += r.output
        total["cache_read"] += r.cache_read
        total["cache_write_5m"] += r.cache_5m
        total["cache_write_1h"] += r.cache_1h
    return total


def _by_model(requests: Iterable[Request]) -> dict[str, dict[str, int]]:
    buckets: dict[str, dict[str, int]] = {}
    for r in requests:
        bucket = buckets.setdefault(r.model, dict.fromkeys(_VENDOR_KEYS, 0))
        for key, value in r.flat().items():
            bucket[key] += value
    return buckets


def _cost(requests: Iterable[Request], rates: Rates) -> float | None:
    return tu_compat.cost(_by_model(requests), rates)


def _priming_cost(request: Request, rates: Rates) -> float | None:
    """Cost of a request's uncached input and cache writes only (what re-loading context costs)."""
    bucket = {"input": request.input, "output": 0, "cache_read": 0, "cache_5m": request.cache_5m,
              "cache_1h": request.cache_1h}
    return tu_compat.cost({request.model: bucket}, rates)


def _priming_tokens(request: Request) -> int:
    return request.input + request.cache_5m + request.cache_1h


def _summary(requests: list[Request], rates: Rates) -> dict[str, Any]:
    usage = _usage(requests)
    return {"usage": usage, "tokens": sum(usage.values()), "cost_usd": _cost(requests, rates)}


def run_summary(run: Run, rates: Rates) -> dict[str, Any]:
    sub_requests = [r for sub in run.subagents for r in sub.requests]
    everything = [*run.requests, *sub_requests]
    if run.runtime != "claude":
        summary = summarize(everything)
        usage = dict(zip(USAGE_KEYS, (summary["usage"][key] for key in _VENDOR_KEYS)))
        measured = dict(zip(USAGE_KEYS, (summary["measured_usage"][key] for key in _VENDOR_KEYS)))
        estimates = [estimate(run.runtime, row.model, row.flat(), rates, row.measurement) for row in everything]
        known_costs = [item["known_cost_usd"] for item in estimates if item["known_cost_usd"] is not None]
        complete_costs = [item["cost_usd"] for item in estimates]
        cost = (sum(complete_costs) if complete_costs and all(v is not None for v in complete_costs)
                and run.measurement == "exact" else None)
        if not everything:
            usage = dict.fromkeys(USAGE_KEYS)
            summary["measurement"] = "activity_only"
        elif run.measurement != "exact":
            coverage_reasons = (set(run.reasons) - set(summary["reasons"])
                                - {"phase-interval-ambiguous", "parent-attribution-unresolved"})
            if run.measurement == "activity_only" or summary["measurement"] == "exact" or coverage_reasons:
                # Omitted observations invalidate complete buckets; unsupported
                # fields within measured observations leave their other buckets known.
                usage = dict.fromkeys(USAGE_KEYS)
            summary["measurement"] = run.measurement
        return {"calls": None, "observations": len(everything), "usage": usage,
                "measured_usage": measured, "tokens": None if summary["measurement"] != "exact"
                or any(v is None for v in usage.values())
                else sum(usage.values()), "cost_usd": cost,
                "known_cost_usd": sum(known_costs) if known_costs else None,
                "measurement": summary["measurement"], "reasons": sorted(set(summary["reasons"] + run.reasons)),
                "models": {}, "subagents": {"count": None, "usage": dict.fromkeys(USAGE_KEYS), "cost_usd": None},
                "skills": list(run.skills)}
    base = _summary(everything, rates)
    models: dict[str, Any] = {}
    for model in sorted({r.model for r in everything}):
        of_model = [r for r in everything if r.model == model]
        models[model] = {"calls": len(of_model), "usage": _usage(of_model), "cost_usd": _cost(of_model, rates)}
    sub_summary = _summary(sub_requests, rates)
    return {
        "calls": len(everything),
        "usage": base["usage"],
        "tokens": base["tokens"],
        "cost_usd": base["cost_usd"],
        "models": models,
        "subagents": {"count": sum(1 for sub in run.subagents if sub.requests), "usage": sub_summary["usage"],
                      "cost_usd": sub_summary["cost_usd"]},
        "skills": list(run.skills),
    }


def session_facts(digest: SessionDigest) -> dict[str, Any]:
    calls: dict[str, int] = {}
    last_seen: dict[str, int] = {}
    for index, r in enumerate(digest.requests):
        calls[r.model] = calls.get(r.model, 0) + 1
        last_seen[r.model] = index
    dominant = max(calls, key=lambda m: (calls[m], last_seen[m])) if calls else None
    last = digest.requests[-1] if digest.requests else None
    final = last.input + last.cache_read + last.cache_5m + last.cache_1h if last else 0
    return {
        "dominant_model": dominant,
        "main_calls": len(digest.requests),
        "final_context_tokens": final,
        "used_1h_cache": any(r.cache_1h > 0 for r in digest.requests),
    }


def repriming(digest: SessionDigest, feature_runs: Sequence[Run], rates: Rates) -> dict[str, Any] | None:
    """What the session's first request re-loaded — only when that request belongs to these runs."""
    if not digest.capabilities.splitting or not digest.requests:
        return None
    first = digest.requests[0]
    if not any(r.request_id == first.request_id for run in feature_runs for r in run.requests):
        return None
    return {"tokens": _priming_tokens(first), "cost_usd": _priming_cost(first, rates)}


def _gap_seconds(earlier: str | None, later: str | None) -> int | None:
    if not earlier or not later:
        return None
    try:
        return int((parse_ts(later) - parse_ts(earlier)).total_seconds())
    except ValueError:
        return None


def verdict(prev: SessionDigest, cur: SessionDigest, repriming_cost: float | None, rates: Rates) -> dict[str, Any]:
    """Cost the split avoided (carrying prev's context through cur's calls) against cur's re-priming."""
    prev_facts = session_facts(prev)
    cur_facts = session_facts(cur)
    carried = prev_facts["final_context_tokens"]
    calls = cur_facts["main_calls"]
    gap = _gap_seconds(prev.last_ts, cur.first_ts)
    model_rates = tu_compat.rate_of(cur_facts["dominant_model"], rates) if cur_facts["dominant_model"] else None
    avoided = None
    if model_rates is not None:
        avoided = carried * calls * model_rates["cache_read"] / 1e6
        uses_1h = prev_facts["used_1h_cache"]
        ttl = TTL_1H_SECONDS if uses_1h else TTL_5M_SECONDS
        if gap is not None and gap > ttl:
            multiplier = CACHE_WRITE_1H_MULT if uses_1h else CACHE_WRITE_5M_MULT
            avoided += carried * model_rates["input"] * multiplier / 1e6
    net = avoided - repriming_cost if avoided is not None and repriming_cost is not None else None
    return {"previous_session_id": prev.session_id, "carried_tokens": carried, "calls": calls, "gap_seconds": gap,
            "avoided_cost_usd": avoided, "net_usd": net}


def compactions(digest: SessionDigest, rates: Rates) -> list[dict[str, Any]]:
    """Each compaction and the cost of re-loading context in the first request after it."""
    if not digest.capabilities.compaction:
        return []
    found: list[dict[str, Any]] = []
    for index, event in enumerate(digest.events):
        if event.kind != "compact":
            continue
        reload = next((r for r in digest.requests if r.event_index >= index), None)
        found.append({
            "ts": event.ts, "trigger": event.trigger, "pre_tokens": event.pre_tokens, "post_tokens": event.post_tokens,
            "reload_tokens": _priming_tokens(reload) if reload else None,
            "reload_cost_usd": _priming_cost(reload, rates) if reload else None,
        })
    return found


def completeness(digests: Sequence[SessionDigest], deadline_hit: bool) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if deadline_hit:
        reasons.append("deadline")
    for digest in digests:
        if any(sub.requests and not sub.finished and sub.last_ts and digest.last_main_ts
               and sub.last_ts > digest.last_main_ts for sub in digest.subagents):
            reasons.append("subagent-in-progress")
            break
    return ("partial" if reasons else "complete"), reasons


def session_entry(digest: SessionDigest, runs: Sequence[AttributedRun], rates: Rates, prev: SessionDigest | None,
                  keep_previews: bool) -> dict[str, Any]:
    """One per-author-file session object (spec §4.2); runs numbered per phase within the session."""
    if digest.runtime != "claude":
        counters: dict[str, int] = {}
        run_objects = []
        for attributed in sorted(runs, key=lambda a: (a.run.start_ts or "", a.run.label)):
            run = attributed.run
            counters[run.phase] = counters.get(run.phase, 0) + 1
            obj = {"phase": run.phase, "kind": run.kind, "label": run.label, "run": counters[run.phase],
                   "start_ts": run.start_ts, "end_ts": run.end_ts, "attributed_by": attributed.attributed_by,
                   **run_summary(run, rates)}
            if keep_previews:
                obj["prompt_preview"] = run.prompt_preview
            run_objects.append(obj)
        from dataclasses import asdict

        return {"session_id": digest.session_id, "runtime": digest.runtime, "measurement": digest.measurement,
                "reasons": digest.reasons, "capabilities": asdict(digest.capabilities),
                "attribution_confidence": digest.attribution_confidence, "first_ts": digest.first_ts,
                "last_ts": digest.last_ts, "after_clear": False, "dominant_model": None, "main_calls": None,
                "final_context_tokens": None, "repriming": None, "splitting": None, "compactions": [],
                "runs": run_objects}
    facts = session_facts(digest)
    ordered = sorted(runs, key=lambda a: (a.run.start_ts or "", a.run.label))
    primed = repriming(digest, [a.run for a in ordered], rates)
    splitting = verdict(prev, digest, primed["cost_usd"], rates) if prev is not None and primed is not None else None
    counters: dict[str, int] = {}
    run_objects = []
    for attributed in ordered:
        run = attributed.run
        counters[run.phase] = counters.get(run.phase, 0) + 1
        summary = run_summary(run, rates)
        obj = {
            "phase": run.phase, "kind": run.kind, "label": run.label, "run": counters[run.phase],
            "start_ts": run.start_ts, "end_ts": run.end_ts, "attributed_by": attributed.attributed_by,
            "calls": summary["calls"], "usage": summary["usage"], "cost_usd": summary["cost_usd"],
            "models": summary["models"], "subagents": summary["subagents"], "skills": summary["skills"],
        }
        if keep_previews:
            obj["prompt_preview"] = run.prompt_preview
        run_objects.append(obj)
    return {
        "session_id": digest.session_id,
        "first_ts": digest.first_ts,
        "last_ts": digest.last_ts,
        "after_clear": any(a.run.after_clear for a in ordered),
        "dominant_model": facts["dominant_model"],
        "main_calls": facts["main_calls"],
        "final_context_tokens": facts["final_context_tokens"],
        "repriming": primed,
        "splitting": splitting,
        "compactions": compactions(digest, rates),
        "runs": run_objects,
    }


def renumber_runs(sessions: list[dict[str, Any]]) -> None:
    """Number runs per phase across all sessions of one author file, in start order (in place)."""
    runs = [run for session in sessions for run in session["runs"]]
    counters: dict[str, int] = {}
    for run in sorted(runs, key=lambda r: (r.get("start_ts") or "", r.get("label") or "")):
        counters[run["phase"]] = counters.get(run["phase"], 0) + 1
        run["run"] = counters[run["phase"]]
