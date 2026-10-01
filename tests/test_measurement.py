from usage_bridge.digest import Request


def observation(**values):
    from usage_bridge.measurement import summarize

    request = Request("r", None, "unknown", 0, 0, 0, 0, 0, 0)
    for key, value in values.items():
        setattr(request, key, value)
    return summarize([request])


def test_mixed_measurement_preserves_known_subtotal():
    from usage_bridge.measurement import summarize

    measured = Request("r", None, "unknown", 100, 20, 0, 0, 0, 0)
    activity = Request("a", None, "unknown", None, None, None, None, None, 0,
                       measurement="activity_only")
    result = summarize([measured, activity])
    assert result["usage"]["input"] is None
    assert result["measured_usage"]["input"] == 100
    assert result["measurement"] == "activity_only"


def test_measured_zero_is_zero():
    assert observation()["usage"]["input"] == 0


def test_partial_unknown_bucket_remains_unknown():
    result = observation(input=50, output=None, measurement="partial", reasons=["missing-output"])
    assert result["usage"]["output"] is None
    assert result["measured_usage"]["input"] == 50
    assert result["reasons"] == ["missing-output"]
