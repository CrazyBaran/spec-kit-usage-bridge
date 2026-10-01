import pytest

from usage_bridge.tu_compat import Rates


def test_codex_rate_and_unknown_model():
    from usage_bridge.pricing import estimate

    usage = {"input": 100, "output": 20, "cache_read": 40, "cache_5m": 0, "cache_1h": 0}
    result = estimate("codex", "gpt-5.2-codex", usage, Rates({}, "test", "hash"))
    assert result["cost_usd"] == pytest.approx((100 * 1.75 + 20 * 14 + 40 * .175) / 1e6)
    assert estimate("codex", "unknown", usage, Rates({}, "test", "hash"))["cost_usd"] is None


def test_partial_cost_is_only_subtotal():
    from usage_bridge.pricing import estimate

    result = estimate("codex", "custom", {"input": 100, "output": None, "cache_read": 0,
                                          "cache_5m": 0, "cache_1h": 0},
                      Rates({"custom": {"input": 2, "output": 10, "cache_read": 1}}, "test", "hash"), "partial")
    assert result["cost_usd"] is None
    assert result["known_cost_usd"] == .0002
