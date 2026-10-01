import pytest


def test_v1_normalization_preserves_partial_capture():
    from usage_bridge.schema import normalize_source

    result = normalize_source({"schema": "usage-bridge/feature-usage", "schema_version": 1,
                               "completeness": "partial", "partial_reasons": ["deadline"],
                               "sessions": [{"session_id": "s", "runs": []}]})
    assert result["schema_version"] == 2
    assert result["sessions"][0]["runtime"] == "claude"
    assert result["partial_reasons"] == ["deadline"]


def test_unknown_schema_rejected():
    from usage_bridge.schema import normalize_source

    with pytest.raises(ValueError, match="schema"):
        normalize_source({"schema_version": 999})


def test_mixed_report_preserves_nulls_and_runtime_identity():
    from usage_bridge.render import author_file, merge_feature, render_feature_md

    bucket = {"input": 100, "output": 20, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
    run = {"phase": "plan", "kind": "core", "label": "/speckit.plan", "usage": bucket,
           "calls": 1, "cost_usd": 1.0}
    exact = {"session_id": "same", "runtime": "claude", "measurement": "exact", "runs": [run]}
    unknown_run = {**run, "calls": None, "usage": dict.fromkeys(bucket), "cost_usd": None}
    unknown = {"session_id": "same", "runtime": "cursor", "measurement": "activity_only", "runs": [unknown_run]}
    source = author_file("001-login", "specs/001-login", "a", "m", {}, [exact, unknown], "complete", [], [])
    report = merge_feature([source])
    assert report["totals"]["sessions"] == 2
    assert report["totals"]["usage"]["input"] is None
    assert report["totals"]["measured_usage"]["input"] == 100
    assert report["totals"]["cost_usd"] is None
    assert report["totals"]["known_cost_usd"] == 1.0
    assert report["measurement_counts"] == {"exact": 1, "partial": 0, "activity_only": 1}
    text = render_feature_md([source])
    assert "cursor" in text
    assert "unavailable" in text

