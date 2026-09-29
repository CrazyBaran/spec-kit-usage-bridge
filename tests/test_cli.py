import io
import json
import os
import sys

import pytest

from builders import SessionBuilder, make_repo, single_session, stop_payload
from usage_bridge import pipeline
from usage_bridge.cli import MAX_STDIN_BYTES, capture_entry, capture_main, read_stdin, report_entry, report_main


class _Terminal(io.BytesIO):
    def isatty(self):
        return True


def _ansi_stdout(monkeypatch):
    """sys.stdout as a Windows pipe sees it: cp1250 has neither → nor ≈, which the report prints."""
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1250"))
    return raw


def test_read_stdin_decodes_and_strips_bom():
    assert read_stdin(io.BytesIO(b'\xef\xbb\xbf{"a": "\xc5\x81"}')) == '{"a": "Ł"}'
    assert read_stdin(io.BytesIO(b"\xff{")) == "�{"


def test_read_stdin_from_a_terminal_or_nothing_is_empty():
    assert read_stdin(_Terminal(b'{"session_id": "s"}')) == "" and read_stdin(None) == ""


def test_read_stdin_over_the_cap_is_not_empty():
    text = read_stdin(io.BytesIO(b"x" * (MAX_STDIN_BYTES + 10)))
    assert len(text) == MAX_STDIN_BYTES + 1      # truncated garbage, never "" (which would mean a manual run)


def test_capture_main_hook_is_silent(tmp_path):
    repo, raw = single_session(tmp_path)
    out = io.StringIO()
    assert capture_main([], io.BytesIO(raw.encode()), out, dict(os.environ), repo) == 0 and out.getvalue() == ""
    assert (repo / "specs/001-login/token-usage.md").exists()


def test_capture_main_manual_prints_one_line(tmp_path):
    repo, _ = single_session(tmp_path)
    out = io.StringIO()
    assert capture_main([], io.BytesIO(b""), out, dict(os.environ), repo) == 0
    assert out.getvalue().startswith("Usage Bridge: ") and out.getvalue().count("\n") == 1


@pytest.mark.parametrize("raw", [b"x" * (2 << 20), b"\xff\xfe{"], ids=["oversized", "utf16-bom"])
def test_capture_main_bad_stdin(raw, tmp_path):
    repo = make_repo(tmp_path)
    out = io.StringIO()
    assert capture_main([], io.BytesIO(raw), out, dict(os.environ), repo) == 0 and out.getvalue() == ""


def test_capture_main_manual_failure_still_prints_one_line(tmp_path, monkeypatch):
    repo, _ = single_session(tmp_path)
    monkeypatch.setattr(pipeline, "digest_session", lambda *a, **k: 1 / 0)
    out = io.StringIO()
    assert capture_main([], io.BytesIO(b""), out, dict(os.environ), repo) == 0
    line = out.getvalue()
    assert line.startswith("Usage Bridge: capture failed (ZeroDivisionError") and line.count("\n") == 1


def test_capture_main_manual_when_disabled(tmp_path):
    repo, _ = single_session(tmp_path)
    cfg = repo / ".specify/extensions/usage-bridge"
    cfg.mkdir(parents=True)
    (cfg / "usage-bridge-config.yml").write_text("enabled: false\n", encoding="utf-8")
    out = io.StringIO()
    assert capture_main([], io.BytesIO(b""), out, dict(os.environ), repo) == 0
    assert out.getvalue() == "Usage Bridge: disabled (enabled: false in the configuration)\n"


def test_capture_main_never_raises(tmp_path, monkeypatch):
    repo, _ = single_session(tmp_path)
    monkeypatch.setattr("usage_bridge.cli.run_capture", lambda *a, **k: 1 / 0)
    assert capture_main([], io.BytesIO(b""), io.StringIO(), dict(os.environ), repo) == 0


def test_report_default_feature_prints_md(tmp_path):
    repo, raw = single_session(tmp_path)
    capture_main([], io.BytesIO(raw.encode()), io.StringIO(), dict(os.environ), repo)
    out = io.StringIO()
    assert report_main([], out, dict(os.environ), repo) == 0
    assert out.getvalue() == (repo / "specs/001-login/token-usage.md").read_text(encoding="utf-8")


def test_report_named_feature_json(tmp_path):
    repo, _ = single_session(tmp_path)
    out = io.StringIO()
    assert report_main(["001-login", "--json"], out, dict(os.environ), repo) == 0
    assert json.loads(out.getvalue())["schema"] == "usage-bridge/feature-report"


@pytest.mark.parametrize("arg", ["specs/001-login", "specs\\001-login\\", "./specs/001-login/"])
def test_report_feature_by_path(arg, tmp_path):
    repo, _ = single_session(tmp_path)
    out = io.StringIO()
    assert report_main([arg], out, dict(os.environ), repo) == 0 and "| plan |" in out.getvalue()


def test_report_all(tmp_path):
    repo, _ = single_session(tmp_path)
    out = io.StringIO()
    assert report_main(["--all"], out, dict(os.environ), repo) == 0 and "001-login" in out.getvalue()


def test_report_all_json(tmp_path):
    repo, _ = single_session(tmp_path)
    out = io.StringIO()
    assert report_main(["--all", "--json"], out, dict(os.environ), repo) == 0
    data = json.loads(out.getvalue())
    assert data["schema"] == "usage-bridge/repo-report" and [f["id"] for f in data["features"]] == ["001-login"]


def test_report_unknown_feature(tmp_path):
    repo, _ = single_session(tmp_path)
    out = io.StringIO()
    assert report_main(["nope"], out, dict(os.environ), repo) == 1 and "Features: 001-login" in out.getvalue()


def test_report_feature_without_usage(tmp_path):
    repo, _ = single_session(tmp_path)
    (repo / "specs" / "002-empty").mkdir()
    out = io.StringIO()
    assert report_main(["002-empty"], out, dict(os.environ), repo) == 1
    assert out.getvalue() == "No token usage recorded for '002-empty' yet. Features: 001-login\n"


def test_report_without_any_usage(tmp_path):
    repo = make_repo(tmp_path)
    out = io.StringIO()
    assert report_main([], out, dict(os.environ), repo) == 1
    assert out.getvalue() == "No token usage recorded yet.\n"


@pytest.mark.parametrize("argv", [["--verbose"], ["a", "b"], ["001-login", "--all"]])
def test_report_usage_error(argv, tmp_path):
    repo, _ = single_session(tmp_path)
    out = io.StringIO()
    assert report_main(argv, out, dict(os.environ), repo) == 1
    assert out.getvalue().startswith("usage: ") and not (repo / "specs/001-login/token-usage.md").exists()


def two_features(tmp_path):
    """002-cart worked on first (s1, 09:00), 001-login most recently (s2, 10:00); returns (repo, s1 payload)."""
    repo = make_repo(tmp_path, features=("001-login", "002-cart"))
    payloads = {}
    for sid, branch, start in (("s1", "002-cart", "2026-09-29T09:00:00.000Z"),
                               ("s2", "001-login", "2026-09-29T10:00:00.000Z")):
        b = SessionBuilder(sid, cwd=repo, branch=branch, start=start)
        b.command("/speckit-plan")
        b.reply(f"r-{sid}", output=5)
        payloads[sid] = stop_payload(sid, b.write(), repo)
    return repo, payloads["s1"]


def test_report_default_prefers_the_active_feature(tmp_path):
    repo, _ = two_features(tmp_path)
    out = io.StringIO()
    report_main([], out, dict(os.environ), repo)
    assert out.getvalue().splitlines()[1] == "# Token usage — 001-login"     # most recently active
    (repo / ".specify" / "feature.json").write_text('{"feature_directory": "specs/002-cart"}', encoding="utf-8")
    out = io.StringIO()
    report_main([], out, dict(os.environ), repo)
    assert out.getvalue().splitlines()[1] == "# Token usage — 002-cart"      # the active feature wins


def test_report_default_uses_the_latest_timeline_feature(tmp_path):
    repo, s1 = two_features(tmp_path)
    env = {**os.environ, "SPECIFY_FEATURE_DIRECTORY": "specs/002-cart"}
    capture_main([], io.BytesIO(s1.encode()), io.StringIO(), env, repo)     # the Stop of s1 saw 002-cart
    out = io.StringIO()
    report_main([], out, dict(os.environ), repo)
    assert out.getvalue().splitlines()[1] == "# Token usage — 002-cart"


def test_report_refreshes_first(tmp_path):
    repo, _ = single_session(tmp_path)
    report_main([], io.StringIO(), dict(os.environ), repo)
    more = SessionBuilder("s2", cwd=repo, branch="001-login")
    more.command("/speckit-tasks")
    more.reply("r9", output=5)
    more.write()
    out = io.StringIO()
    report_main([], out, dict(os.environ), repo)
    assert "| tasks |" in out.getvalue()


def test_report_entry_writes_utf8_on_an_ansi_pipe(tmp_path, monkeypatch):
    repo, _ = single_session(tmp_path)
    raw = _ansi_stdout(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["report.py"])
    monkeypatch.chdir(repo)
    assert report_entry() == 0
    sys.stdout.flush()
    assert "Start → end (UTC)".encode() in raw.getvalue()


def test_capture_entry_reads_the_hook_payload(tmp_path, monkeypatch):
    repo, payload = single_session(tmp_path)
    raw = _ansi_stdout(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload.encode())))
    monkeypatch.chdir(repo)
    assert capture_entry() == 0
    sys.stdout.flush()
    assert raw.getvalue() == b"" and (repo / "specs/001-login/token-usage.md").exists()


def test_capture_entry_without_stdin_is_a_manual_run(tmp_path, monkeypatch):
    repo, _ = single_session(tmp_path)
    raw = _ansi_stdout(monkeypatch)
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.chdir(repo)
    assert capture_entry() == 0
    sys.stdout.flush()
    assert raw.getvalue().decode("utf-8").startswith("Usage Bridge: 1 feature updated — 001-login")
