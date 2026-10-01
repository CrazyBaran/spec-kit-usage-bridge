import codecs
import json
from datetime import datetime, timezone

import pytest

from usage_bridge.timeline import TimelineEntry, active_feature, append, by_session, make_entry, read


def test_active_feature_prefers_env(tmp_path):
    (tmp_path / ".specify").mkdir()
    (tmp_path / ".specify" / "feature.json").write_text('{"feature_directory": "specs/001-a"}', encoding="utf-8")
    env = {"SPECIFY_FEATURE_DIRECTORY": str(tmp_path / "specs" / "002-b")}
    assert active_feature(tmp_path, env) == ("specs/002-b", "env")


def test_active_feature_reads_feature_json_with_bom_and_backslashes(tmp_path):
    (tmp_path / ".specify").mkdir()
    (tmp_path / ".specify" / "feature.json").write_bytes(codecs.BOM_UTF8 + b'{"feature_directory": "specs\\\\003-c"}')
    assert active_feature(tmp_path, {}) == ("specs/003-c", "feature.json")


def test_active_feature_absolute_inside_work_and_none(tmp_path):
    (tmp_path / ".specify").mkdir()
    feature = json.dumps({"feature_directory": str(tmp_path / "specs" / "004-d")})
    (tmp_path / ".specify" / "feature.json").write_text(feature, encoding="utf-8")
    assert active_feature(tmp_path, {}) == ("specs/004-d", "feature.json")
    assert active_feature(tmp_path / "empty", {}) == (None, "none")


def test_append_read_roundtrip_skips_garbage(tmp_path):
    now = datetime(2026, 9, 29, 10, 40, 12, 345000, tzinfo=timezone.utc)
    e = make_entry("s1", tmp_path, {}, "001-login", now)
    append(tmp_path, e)
    with (tmp_path / "timeline.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{garbage\n")
    append(tmp_path, make_entry("s2", tmp_path, {}, None, now))
    assert [x.session_id for x in read(tmp_path)] == ["s1", "s2"] and e.ts == "2026-09-29T10:40:12.345Z"


def test_by_session_sorts(tmp_path):
    a = TimelineEntry("2026-09-29T10:05:00.000Z", "s1", "w", None, "none", None)
    b = TimelineEntry("2026-09-29T10:01:00.000Z", "s1", "w", None, "none", None)
    assert by_session([a, b])["s1"] == [b, a]


@pytest.mark.parametrize('value', ['specs/../../outside', r'specs\..\..\outside', '../outside', 'C:outside'])
def test_feature_paths_cannot_escape_checkout(value, tmp_path):
    from usage_bridge.timeline import relative_dir
    assert relative_dir(value, tmp_path / 'repo') is None
