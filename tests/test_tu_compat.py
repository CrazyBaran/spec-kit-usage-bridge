import hashlib
import os
import shutil
from pathlib import Path

import pytest
from builders import SessionBuilder, make_repo
from usage_bridge import tu_compat

pytestmark = pytest.mark.contract


def test_vendored_hashes_match_vendor_json():
    info = tu_compat.vendored_info()
    assert info["commit"] == "f4078277e79c007993e0cb595bb95f924a2a8777"
    for rel, digest in info["files"].items():
        assert digest == "sha256:" + hashlib.sha256((tu_compat.VENDOR_DIR / rel).read_bytes()).hexdigest()


def test_tampered_vendor_raises(tmp_path, monkeypatch):
    fake = tmp_path / "vendor"
    shutil.copytree(tu_compat.VENDOR_DIR, fake)
    (fake / "data" / "pricing.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(tu_compat, "VENDOR_DIR", fake)
    monkeypatch.setattr(tu_compat, "_MODULE", None)
    with pytest.raises(tu_compat.VendorError):
        tu_compat.module()


def test_iter_entries_skips_bad_lines(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('{"a": 1}\n{bad\n{"b": 2}\n', encoding="utf-8")
    assert list(tu_compat.iter_entries(p)) == [{"a": 1}, {"b": 2}]


def test_undecodable_bytes_never_reach_stderr(tmp_path, capfd):
    p = tmp_path / "t.jsonl"
    p.write_bytes(b'{"a": 1}\n\xff\xfe\n')
    assert list(tu_compat.iter_entries(p)) == [{"a": 1}]
    assert capfd.readouterr().err == ""
    assert any("undecodable" in w for w in tu_compat.drain_warnings())


def test_normalize_splits_cache_ttl_and_legacy_total():
    u = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 50,
         "cache_creation": {"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 30}}
    assert tu_compat.normalize(u) == {"input": 10, "output": 5, "cache_read": 100, "cache_5m": 20, "cache_1h": 30}
    assert tu_compat.normalize({"cache_creation_input_tokens": 40})["cache_5m"] == 40


def test_prompt_detection_and_command_name(tmp_path):
    s = SessionBuilder("s1", cwd=make_repo(tmp_path))
    s.command("/speckit-plan")
    s.prompt("more please")
    first, second = tu_compat.iter_entries(s.write())
    assert tu_compat.is_prompt(first) and tu_compat.command_name(tu_compat.prompt_text(first)) == "/speckit-plan"
    assert tu_compat.command_name(tu_compat.prompt_text(second)) is None
    assert not tu_compat.is_prompt({**first, "isMeta": True})


def test_merge_max_keeps_field_maxima():
    a = {"input": 1, "output": 5, "cache_read": 0, "cache_5m": 0, "cache_1h": 0}
    tu_compat.merge_max(a, {"input": 1, "output": 9, "cache_read": 3, "cache_5m": 0, "cache_1h": 0})
    assert a["output"] == 9 and a["cache_read"] == 3


def test_agent_start_prefers_first_ts_then_meta(tmp_path):
    f = tmp_path / "agent-a.jsonl"
    f.write_text("", encoding="utf-8")
    assert tu_compat.agent_start(f, "2026-09-29T10:00:00.000Z", None) == "2026-09-29T10:00:00.000Z"
    assert tu_compat.agent_start(f, None, {"timestamp": 1790000000000}).startswith("2026-09-21T14:13:20")


def test_load_rates_ignores_personal_overlay(tmp_path):
    overlay = Path(os.environ["XDG_CONFIG_HOME"]) / "token-usage" / "pricing.json"
    overlay.parent.mkdir(parents=True)
    overlay.write_text('{"claude-opus-5-5": {"input": 999, "output": 999}}', encoding="utf-8")
    rates = tu_compat.load_rates({}, tmp_path / "rt")
    assert rates.label == "bundled" and tu_compat.rate_of("claude-opus-5-5", rates)["input"] != 999


def test_load_rates_applies_team_overrides(tmp_path):
    base = tu_compat.load_rates({}, tmp_path)
    rates = tu_compat.load_rates({"claude-test-1": {"input": 2.0, "output": 10.0}}, tmp_path)
    assert rates.label == "bundled+overrides" and rates.sha256 != base.sha256
    assert tu_compat.rate_of("claude-test-1", rates) == {"input": 2.0, "output": 10.0, "cache_read": pytest.approx(0.2)}


def test_invalid_override_is_skipped_with_warning(tmp_path):
    rates = tu_compat.load_rates({"claude-test-1": {"input": "cheap"}}, tmp_path)
    assert tu_compat.rate_of("claude-test-1", rates) is None and rates.warnings


def test_cost_matches_upstream_formula(tmp_path):
    rates = tu_compat.load_rates({"claude-test-1": {"input": 2.0, "output": 10.0}}, tmp_path)
    bucket = {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_5m": 1_000_000, "cache_1h": 1_000_000,
              "requests": 1}
    assert tu_compat.cost({"claude-test-1": bucket}, rates) == pytest.approx(2.0 + 2.5 + 4.0)
    assert tu_compat.cost({"mystery": bucket}, rates) is None
    assert tu_compat.unpriced({"mystery": bucket}, rates) == ["mystery"]


def test_projects_root_honours_env():
    assert tu_compat.projects_root() == Path(os.environ["TOKEN_USAGE_PROJECTS_DIR"])


def test_oracle_segments_labels(tmp_path):
    s = SessionBuilder("s1", cwd=make_repo(tmp_path))
    s.command("/speckit-plan")
    s.reply("r1", output=3)
    assert [seg["label"] for seg in tu_compat.oracle_segments(s.write())] == ["/speckit-plan"]


def test_vendored_calls_write_nothing(tmp_path):
    tu_compat.load_rates({}, tmp_path / "rt")
    assert not Path(os.environ["TOKEN_USAGE_LEDGER_DIR"]).exists() and not (Path.home() / ".cache").exists()
