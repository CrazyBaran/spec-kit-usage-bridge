import io
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from builders import SessionBuilder, make_repo, projects_root, slug
from usage_bridge.checks import CheckResult, format_results, run_checks
from usage_bridge.cli import check_main
from usage_bridge.tu_compat import VendorError

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
STOP_COMMAND = '"python" "${CLAUDE_PROJECT_DIR}/.specify/events.py" speckit.usage-bridge.capture stop 30'
IDS = ["python", "integration", "stop-hook", "dispatcher", "git", "transcripts", "runtime-dir", "last-capture",
       "config"]


def healthy(tmp_path):
    """Claude installed with runtime events, one transcript, a capture 12 minutes before NOW."""
    repo = make_repo(tmp_path)
    integration = {"installed_integrations": ["claude"], "default_integration": "claude"}
    (repo / ".specify/integration.json").write_text(json.dumps(integration), encoding="utf-8")
    (repo / ".specify/events.py").write_text("# dispatcher\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    hook = {"type": "command", "command": STOP_COMMAND, "__speckit_event__": True}
    (repo / ".claude/settings.json").write_text(json.dumps({"hooks": {"Stop": [{"matcher": "*", "hooks": [hook]}]}}),
                                                encoding="utf-8")
    b = SessionBuilder("s1", cwd=repo, branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", output=5)
    earlier = (NOW - timedelta(minutes=30)).timestamp()        # before the capture, whatever today's date is
    os.utime(b.write(), (earlier, earlier))
    runtime = repo / ".git" / "usage-bridge"
    runtime.mkdir()
    (runtime / "last-capture.json").write_text(json.dumps({"ts": "2026-09-29T11:48:00.000Z", "status": "ok"}),
                                               encoding="utf-8")
    return repo


def by_id(results, check_id):
    (result,) = [r for r in results if r.id == check_id]
    return result


def test_healthy_prints_ok_line(tmp_path):
    p = healthy(tmp_path)
    out = io.StringIO()
    assert check_main([], out, dict(os.environ), p, now=NOW) == 0
    assert out.getvalue() == "Usage Bridge: ok (last capture 12 min ago)\n"


@pytest.mark.parametrize("break_it,check_id", [
    (lambda p: (p / ".specify/integration.json").write_text('{"installed_integrations": ["cursor-agent"]}'),
     "integration"),
    (lambda p: (p / ".claude/settings.json").write_text('{"hooks": {}}'), "stop-hook"),
    (lambda p: (p / ".specify/events.py").unlink(), "dispatcher")], ids=["integration", "stop-hook", "dispatcher"])
def test_failures_exit_1_with_remediation(break_it, check_id, tmp_path):
    p = healthy(tmp_path)
    break_it(p)
    out = io.StringIO()
    assert check_main([], out, dict(os.environ), p, now=NOW) == 1 and f"FAIL {check_id}:" in out.getvalue()


def test_events_disabled_remediation_text(tmp_path):
    p = healthy(tmp_path)
    (p / ".claude/settings.json").write_text('{"hooks": {}}')
    r = by_id(run_checks(p, dict(os.environ), NOW), "stop-hook")
    assert r.remediation == ('Runtime events are disabled or were removed. '
                             'Run: specify integration upgrade claude --integration-options="--events true"')


def test_stop_hook_with_windows_separators_counts(tmp_path):
    p = healthy(tmp_path)
    settings = (p / ".claude/settings.json").read_text(encoding="utf-8").replace("/.specify/", "\\\\.specify\\\\")
    (p / ".claude/settings.json").write_text(settings, encoding="utf-8")
    assert by_id(run_checks(p, dict(os.environ), NOW), "stop-hook").ok


def test_cursor_only_also_warns(tmp_path):
    p = healthy(tmp_path)
    (p / ".specify/integration.json").write_text('{"installed_integrations": ["cursor-agent"]}')
    assert any(r.level == "WARN" and "Cursor capture is not supported in v0.1" in r.message
               for r in run_checks(p, dict(os.environ), NOW))


@pytest.mark.parametrize("doc", [{"default_integration": "claude"}, {"integration": "claude"}])
def test_claude_counts_as_default_or_legacy_integration(doc, tmp_path):
    p = healthy(tmp_path)
    (p / ".specify/integration.json").write_text(json.dumps(doc), encoding="utf-8")
    assert by_id(run_checks(p, dict(os.environ), NOW), "integration").ok


def test_old_python_fails(tmp_path):
    r = by_id(run_checks(healthy(tmp_path), dict(os.environ), NOW, python_version=(3, 8)), "python")
    assert not r.ok and r.level == "FAIL"


def test_warnings_do_not_fail(tmp_path, monkeypatch):
    p = healthy(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    out = io.StringIO()
    assert check_main([], out, dict(os.environ), p, now=NOW) == 0 and "WARN git:" in out.getvalue()


def test_last_capture_error_warns(tmp_path):
    p = healthy(tmp_path)
    (p / ".git/usage-bridge/last-capture.json").write_text(
        json.dumps({"ts": "2026-09-29T11:00:00.000Z", "status": "error", "error": "boom"}))
    r = by_id(run_checks(p, dict(os.environ), NOW), "last-capture")
    assert r.level == "WARN" and not r.ok and "boom" in r.remediation
    assert r.remediation.startswith("Last capture failed at 2026-09-29 11:00 UTC: boom — see ")
    assert r.remediation.endswith("usage-bridge.log")


def test_captures_not_running_warns(tmp_path):
    p = healthy(tmp_path)
    status = {"ts": "2026-09-27T12:00:00.000Z", "status": "ok"}
    (p / ".git/usage-bridge/last-capture.json").write_text(json.dumps(status))
    for t in (projects_root() / slug(p)).glob("*.jsonl"):
        os.utime(t, (NOW.timestamp(), NOW.timestamp()))
    r = by_id(run_checks(p, dict(os.environ), NOW), "last-capture")
    assert r.level == "WARN" and not r.ok and "check the Stop hook" in r.remediation


def test_no_capture_yet_is_ok(tmp_path):
    p = healthy(tmp_path)
    (p / ".git/usage-bridge/last-capture.json").unlink()
    out = io.StringIO()
    assert check_main([], out, dict(os.environ), p, now=NOW) == 0
    assert out.getvalue() == "Usage Bridge: ok (no capture yet)\n"


def test_no_transcripts_yet_warns(tmp_path):
    p = healthy(tmp_path)
    shutil.rmtree(projects_root() / slug(p))
    r = by_id(run_checks(p, dict(os.environ), NOW), "transcripts")
    assert r.level == "WARN" and not r.ok
    assert r.remediation == "No Claude Code transcripts for this repository yet — run one agent turn, then check again."


def test_missing_projects_directory_warns(tmp_path, monkeypatch):
    p = healthy(tmp_path)
    monkeypatch.setenv("TOKEN_USAGE_PROJECTS_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "missing-too"))
    r = by_id(run_checks(p, dict(os.environ), NOW), "transcripts")
    assert r.remediation == "No Claude projects directory found — set TOKEN_USAGE_PROJECTS_DIR or CLAUDE_CONFIG_DIR."


def test_transcript_lookup_failure_is_reported(tmp_path, monkeypatch):
    p = healthy(tmp_path)

    def broken(*_args):
        raise VendorError("vendored token_usage.py does not match VENDOR.json")

    monkeypatch.setattr("usage_bridge.checks.projects_roots", broken)
    out = io.StringIO()
    assert check_main([], out, dict(os.environ), p, now=NOW) == 0
    assert "WARN transcripts: cannot look for transcripts: VendorError: vendored" in out.getvalue()


def test_unwritable_runtime_dir_fails(tmp_path):
    p = healthy(tmp_path)
    runtime = p / ".git" / "usage-bridge"
    shutil.rmtree(runtime)
    runtime.write_text("not a directory", encoding="utf-8")
    out = io.StringIO()
    assert check_main([], out, dict(os.environ), p, now=NOW) == 1
    assert "FAIL runtime-dir: Cannot write " in out.getvalue() and "usage-bridge" in out.getvalue()


def test_alias_in_committed_config_warns(tmp_path):
    p = healthy(tmp_path)
    d = p / ".specify/extensions/usage-bridge"
    d.mkdir(parents=True, exist_ok=True)
    (d / "usage-bridge-config.yml").write_text("author:\n  alias: team\n", encoding="utf-8")
    r = by_id(run_checks(p, dict(os.environ), NOW), "config")
    assert r.level == "WARN" and not r.ok and "usage-bridge-config.local.yml" in r.remediation


def test_json_and_verbose(tmp_path):
    p = healthy(tmp_path)
    out = io.StringIO()
    check_main(["--json"], out, dict(os.environ), p, now=NOW)
    doc = json.loads(out.getvalue())
    assert doc["ok"] is True and [c["id"] for c in doc["checks"]] == IDS
    assert set(doc["checks"][0]) == {"id", "level", "status", "message", "remediation"}
    assert {c["status"] for c in doc["checks"]} == {"ok"}
    out = io.StringIO()
    check_main(["--verbose"], out, dict(os.environ), p, now=NOW)
    assert out.getvalue().count("\n") == 9 and out.getvalue().startswith("ok python: Python ")


def test_json_reports_failures(tmp_path):
    p = healthy(tmp_path)
    (p / ".specify/events.py").unlink()
    out = io.StringIO()
    assert check_main(["--json"], out, dict(os.environ), p, now=NOW) == 1
    doc = json.loads(out.getvalue())
    assert doc["ok"] is False and [c["status"] for c in doc["checks"] if c["id"] == "dispatcher"] == ["fail"]


def test_unknown_flag_prints_usage(tmp_path):
    out = io.StringIO()
    assert check_main(["--nope"], out, dict(os.environ), healthy(tmp_path), now=NOW) == 1
    assert out.getvalue() == "usage: check [--verbose] [--json]\n"


@pytest.mark.parametrize("ago,text", [(timedelta(minutes=59), "59 min ago"), (timedelta(hours=3), "3 h ago"),
                                      (timedelta(days=3), "3 days ago"), (timedelta(minutes=-5), "0 min ago")])
def test_capture_age_units(ago, text):
    ok = [CheckResult("python", "FAIL", True, "Python 3.9", "")]
    stamp = (NOW - ago).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert format_results(ok, False, NOW, stamp) == f"Usage Bridge: ok (last capture {text})\n"
