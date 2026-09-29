import itertools
from datetime import datetime, timedelta, timezone

import pytest

from usage_bridge.attribution import AttributedRun, Bucket
from usage_bridge.digest import Event, Request, SessionDigest, SubagentDigest
from usage_bridge.metrics import (
    compactions,
    completeness,
    renumber_runs,
    repriming,
    run_summary,
    session_entry,
    session_facts,
    verdict,
)
from usage_bridge.phases import Run
from usage_bridge.timefmt import iso
from usage_bridge.tu_compat import load_rates

_CLOCK = itertools.count()
_BASE = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def rates(tmp_path):
    return load_rates({"claude-test-1": {"input": 2.0, "output": 10.0}}, tmp_path)


def req(request_id, model="claude-test-1", input=0, output=0, cache_read=0, cache_5m=0, cache_1h=0):
    ts = iso(_BASE + timedelta(seconds=next(_CLOCK)))
    return Request(request_id, ts, model, input, output, cache_read, cache_5m, cache_1h, 0)


def mk_sub(requests, last_ts=None, finished=True):
    return SubagentDigest("agent-x.jsonl", "agent", 1, requests[0].ts, last_ts or requests[-1].ts, requests[0].ts,
                          finished, list(requests))


def mk_digest(requests, first_ts=None, last_ts=None, last_main_ts=None, subagents=(), compact_before_index=None):
    requests = list(requests)
    events = []
    if compact_before_index is not None:
        events = [Event("compact", requests[compact_before_index].ts, trigger="auto", pre_tokens=967128,
                        post_tokens=24252)]
        for i, r in enumerate(requests):
            r.event_index = -1 if i < compact_before_index else 0
    last = last_ts or requests[-1].ts
    return SessionDigest("s1", "s1.jsonl", first_ts or requests[0].ts, last, last_main_ts or last, [], [], events,
                         requests, list(subagents))


def mk_run(main=(), subagents=()):
    main = list(main)
    start = main[0].ts if main else None
    return Run("s1", "core", "plan", "/speckit-plan", start, main[-1].ts if main else None, main, list(subagents))


def test_run_summary_sums_main_and_subagents(rates):
    run = mk_run(main=[req("r1", input=1000, output=500, cache_read=10000, cache_5m=2000)],
                 subagents=[mk_sub([req("ra", input=100, output=50)])])
    s = run_summary(run, rates)
    assert (s["calls"], s["tokens"]) == (2, 13650)
    assert s["usage"] == {"input": 1100, "output": 550, "cache_read": 10000, "cache_write_5m": 2000,
                          "cache_write_1h": 0}
    assert s["subagents"]["count"] == 1 and s["subagents"]["usage"]["input"] == 100
    assert s["cost_usd"] == pytest.approx((1100 * 2 + 550 * 10 + 10000 * 0.2 + 2000 * 2.5) / 1e6)


def test_unpriced_models_listed_and_excluded(rates):
    s = run_summary(mk_run(main=[req("r1", model="mystery", input=5)]), rates)
    assert s["cost_usd"] is None and list(s["models"]) == ["mystery"]


def test_repriming_first_request(rates):
    d = mk_digest([req("r1", input=20, cache_5m=30000)])
    run = mk_run(main=d.requests)
    assert repriming(d, [run], rates) == {"tokens": 30020, "cost_usd": pytest.approx((20 * 2 + 30000 * 2.5) / 1e6)}
    assert repriming(d, [], rates) is None


def test_verdict_within_ttl(rates):
    prev = mk_digest([req("p1", input=1000, cache_read=170000, cache_5m=9000)], last_ts="2026-09-29T10:00:00.000Z")
    cur = mk_digest([req(f"c{i}") for i in range(38)], first_ts="2026-09-29T10:02:00.000Z")
    v = verdict(prev, cur, 0.1, rates)
    assert (v["carried_tokens"], v["calls"], v["gap_seconds"]) == (180000, 38, 120)
    assert v["avoided_cost_usd"] == pytest.approx(180000 * 38 * 0.2 / 1e6)
    assert v["net_usd"] == pytest.approx(v["avoided_cost_usd"] - 0.1)


def test_verdict_rewrite_after_5_minute_ttl(rates):
    prev = mk_digest([req("p1", cache_read=180000)], last_ts="2026-09-29T10:00:00.000Z")
    cur = mk_digest([req("c1")], first_ts="2026-10-01T12:20:00.000Z")
    expected = 180000 * 1 * 0.2 / 1e6 + 180000 * 2.5 / 1e6
    assert verdict(prev, cur, 0.0, rates)["avoided_cost_usd"] == pytest.approx(expected)


def test_verdict_1_hour_rules(rates):
    prev = mk_digest([req("p1", cache_read=100000, cache_1h=1)], last_ts="2026-09-29T10:00:00.000Z")
    near = mk_digest([req("c1")], first_ts="2026-09-29T10:50:00.000Z")
    far = mk_digest([req("c1")], first_ts="2026-09-29T11:10:00.000Z")
    assert verdict(prev, near, 0.0, rates)["avoided_cost_usd"] == pytest.approx(100001 * 0.2 / 1e6)
    assert verdict(prev, far, 0.0, rates)["avoided_cost_usd"] == pytest.approx(100001 * 0.2 / 1e6 + 100001 * 4.0 / 1e6)


def test_verdict_unpriced_model_has_no_costs(rates):
    prev = mk_digest([req("p1", cache_read=1000)], last_ts="2026-09-29T10:00:00.000Z")
    cur = mk_digest([req("c1", model="mystery")], first_ts="2026-09-29T10:01:00.000Z")
    v = verdict(prev, cur, None, rates)
    assert v["carried_tokens"] == 1000 and v["avoided_cost_usd"] is None and v["net_usd"] is None


def test_dominant_model_and_final_context(rates):
    d = mk_digest([req("a", model="m1"), req("b", model="m2"),
                   req("c", model="m2", input=5, cache_read=7, cache_5m=11)])
    f = session_facts(d)
    assert (f["dominant_model"], f["main_calls"], f["final_context_tokens"]) == ("m2", 3, 23)


def test_compaction_reload(rates):
    d = mk_digest([req("a"), req("b", input=100, cache_5m=43842)], compact_before_index=1)
    (c,) = compactions(d, rates)
    assert (c["trigger"], c["pre_tokens"], c["post_tokens"], c["reload_tokens"]) == ("auto", 967128, 24252, 43942)
    assert c["reload_cost_usd"] == pytest.approx((100 * 2 + 43842 * 2.5) / 1e6)


def test_completeness_reasons():
    running = mk_digest([req("a")], last_main_ts="2026-09-29T10:00:00.000Z",
                        subagents=[mk_sub([req("s")], last_ts="2026-09-29T10:09:00.000Z", finished=False)])
    assert completeness([running], False) == ("partial", ["subagent-in-progress"])
    assert completeness([mk_digest([req("a")])], True) == ("partial", ["deadline"])
    assert completeness([mk_digest([req("a")])], False) == ("complete", [])


def test_session_entry_shape(rates):
    d = mk_digest([req("a", input=5)])
    ar = AttributedRun(mk_run(main=d.requests), Bucket("feature", "specs/001-a"), "timeline")
    e = session_entry(d, [ar], rates, None, keep_previews=False)
    assert list(e) == ["session_id", "first_ts", "last_ts", "after_clear", "dominant_model", "main_calls",
                       "final_context_tokens", "repriming", "splitting", "compactions", "runs"]
    assert e["splitting"] is None and e["runs"][0]["run"] == 1 and "prompt_preview" not in e["runs"][0]
    assert list(e["runs"][0]) == ["phase", "kind", "label", "run", "start_ts", "end_ts", "attributed_by", "calls",
                                  "usage", "cost_usd", "models", "subagents", "skills"]


def test_renumber_runs_across_sessions():
    sessions = [{"runs": [{"phase": "plan", "start_ts": "2026-09-30T10:00:00.000Z", "run": 1}]},
                {"runs": [{"phase": "plan", "start_ts": "2026-09-29T10:00:00.000Z", "run": 1},
                          {"phase": "tasks", "start_ts": "2026-09-29T11:00:00.000Z", "run": 1}]}]
    renumber_runs(sessions)
    assert [r["run"] for s in sessions for r in s["runs"]] == [2, 1, 1]
