from usage_bridge.adapters.base import Capabilities
from usage_bridge.digest import Event, Request, SessionDigest
from usage_bridge.phases import build_runs
from usage_bridge.tu_compat import Rates


def session(runtime, requests=()):
    return SessionDigest("same", "local", None, None, None,
                         events=[Event("command", "2026-10-01T08:00:00Z", name="/speckit.plan")],
                         requests=list(requests), runtime=runtime, capabilities=Capabilities())


def test_activity_only_phase_is_retained():
    digest = session("codex")
    digest.measurement = "activity_only"
    runs = build_runs(digest, [])
    assert len(runs) == 1
    assert runs[0].phase == "plan"
    assert runs[0].runtime == "codex"


def test_dedup_is_runtime_qualified():
    from usage_bridge.attribution import dedup_across_sessions

    row = Request("same-request", None, "unknown", 10, 20, 0, 0, 0, 0)
    kept, dropped = dedup_across_sessions([session("claude", [row]), session("codex", [row])])
    assert len(kept[0].requests) + len(kept[1].requests) == 2
    assert dropped == 0


def test_segment_is_not_api_call_and_metrics_are_unavailable():
    from usage_bridge.metrics import run_summary

    row = Request("r", None, "unknown", None, None, None, None, None, 0,
                  kind="segment", measurement="activity_only")
    digest = session("cursor", [row])
    result = run_summary(build_runs(digest, [])[0], Rates({}, "test", "hash"))
    assert result["calls"] is None
    assert result["usage"]["input"] is None
    assert result["cost_usd"] is None


def test_timeline_cannot_cross_runtime(tmp_path):
    from usage_bridge.attribution import attribute_runs
    from usage_bridge.timeline import TimelineEntry, by_session

    row = Request("r", "2026-10-01T08:00:00.000Z", "unknown", 1, 2, 0, 0, 0, 0)
    run = build_runs(session("codex", [row]), [])[0]
    entry = TimelineEntry("2026-10-01T08:00:01.000Z", "same", str(tmp_path), "specs/001-login",
                          "env", None, last_request_id="r", last_request_ts=row.ts)
    result = attribute_runs([run], by_session([entry]), ["specs/001-login"])
    assert result[0].bucket.kind == "unattributed"
