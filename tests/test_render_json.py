import os

import pytest

from usage_bridge.render import author_file, dump_json, fmt_cost, fmt_tokens, fmt_ts, write_if_changed


@pytest.mark.parametrize("n,s", [(0, "0"), (999, "999"), (1000, "1.0k"), (4149, "4.1k"), (5000, "5.0k"),
                                 (10000, "10k"), (212044, "212k"), (1_000_000, "1.0M"), (17_062_000, "17.1M")])
def test_fmt_tokens(n, s):
    assert fmt_tokens(n) == s


def test_fmt_cost_and_ts():
    assert (fmt_cost(3.9), fmt_cost(None), fmt_cost(0.004)) == ("$3.90", "—", "$0.00")
    assert fmt_ts("2026-10-01T13:00:02.000Z") == "10-01 13:00"


def test_dump_json_is_stable_lf_and_rounded():
    assert dump_json({"b": 1.23456789, "a": "ł"}) == '{\n  "b": 1.234568,\n  "a": "ł"\n}\n'


def test_author_file_shape_and_sorting():
    s1 = {"session_id": "b", "first_ts": "2026-09-30T08:00:00.000Z", "last_ts": "2026-09-30T09:00:00.000Z"}
    s0 = {"session_id": "a", "first_ts": "2026-09-29T08:00:00.000Z", "last_ts": "2026-09-29T09:00:00.000Z"}
    f = author_file("001-a", "specs/001-a", "jakub", "a1b2c3", {"usage_bridge": "0.1.0"}, [s1, s0], "complete", [], [])
    assert list(f) == ["schema", "schema_version", "feature", "author", "generator", "runtime", "completeness",
                       "partial_reasons", "data_as_of", "unpriced_models", "sessions"]
    assert (f["schema"], f["schema_version"], f["runtime"]) == ("usage-bridge/feature-usage", 1, "claude")
    assert [s["session_id"] for s in f["sessions"]] == ["a", "b"] and f["data_as_of"] == "2026-09-30T09:00:00.000Z"
    assert f["feature"] == {"id": "001-a", "directory": "specs/001-a"} and f["author"] == {"name": "jakub",
                                                                                           "machine": "a1b2c3"}


def test_write_if_changed(tmp_path):
    p = tmp_path / "d" / "f.md"
    assert write_if_changed(p, "a\nb\n") is True and p.read_bytes() == b"a\nb\n"
    assert write_if_changed(p, "a\nb\n") is False
    p.write_bytes(b"a\r\nb\r\n")
    before = p.stat().st_mtime_ns
    assert write_if_changed(p, "a\nb\n") is False and p.stat().st_mtime_ns == before
    assert write_if_changed(p, "c\n") is True


def test_write_if_changed_keeps_original_on_failure(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    p = out / "f.md"
    p.write_text("old\n", encoding="utf-8")

    def locked(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", locked)
    assert write_if_changed(p, "new\n") is False
    assert p.read_text(encoding="utf-8") == "old\n" and list(out.iterdir()) == [p]
