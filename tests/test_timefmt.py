import pytest

from usage_bridge.timefmt import norm_ts


@pytest.mark.parametrize("raw,expected", [
    ("2026-09-29T10:40:12Z", "2026-09-29T10:40:12.000Z"),
    ("2026-09-29T10:40:12.345Z", "2026-09-29T10:40:12.345Z"),
    ("2026-09-29T12:40:12.345+02:00", "2026-09-29T10:40:12.345Z"),
    ("2026-09-29T10:40:12.345678+00:00", "2026-09-29T10:40:12.345Z"),
    (1790000000, "2026-09-21T14:13:20.000Z"), (1790000000000, "2026-09-21T14:13:20.000Z"),
    ("garbage", None), (None, None)])
def test_norm_ts(raw, expected):
    assert norm_ts(raw) == expected


def test_normalised_strings_sort_chronologically():
    raw = ["2026-09-29T10:40:12Z", "2026-09-29T10:40:11.999Z", "2026-09-29T10:40:12.345+00:00"]
    assert sorted(map(norm_ts, raw)) == [
        "2026-09-29T10:40:11.999Z", "2026-09-29T10:40:12.000Z", "2026-09-29T10:40:12.345Z"]
