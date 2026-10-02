"""Accounting regressions found during release review."""
import os

import pytest

from builders import make_repo
from codex_builders import prompt, tokens, turn, write_rollout
from usage_bridge.pipeline import run_capture


def test_independent_codex_sessions_with_equal_counters_are_both_counted(tmp_path):
    import json

    repo = make_repo(tmp_path, branch="001-login")
    home = tmp_path / "codex"
    events = [turn(), prompt(), tokens(100, 40, 20)]
    write_rollout(home, repo, session="a", events=events)
    write_rollout(home, repo, session="b", events=events)
    assert run_capture("", repo, dict(os.environ, CODEX_HOME=str(home))).status == "ok"
    document = json.loads(next((repo / "specs/001-login/token-usage").glob("*.json")).read_text())
    assert sum(run["usage"]["input"] or 0 for session in document["sessions"] for run in session["runs"]) == 120


def test_codex_run_preserves_partial_counter_quality(tmp_path):
    from codex_builders import context
    from usage_bridge.adapters.codex import CodexAdapter
    from usage_bridge.config import Config
    from usage_bridge.metrics import run_summary
    from usage_bridge.phases import build_runs
    from usage_bridge.tu_compat import load_rates

    ctx = context(tmp_path, tmp_path)
    write_rollout(tmp_path, tmp_path, events=[turn(), prompt(), tokens(100, 40, 20), tokens(10, 0, 2)])
    adapter = CodexAdapter()
    digest = adapter.parse(next(adapter.discover(ctx, Config())), ctx)
    summary = run_summary(build_runs(digest, [])[0], load_rates({}, ctx.runtime_dir))
    assert summary["measurement"] == "partial"
    assert summary["tokens"] is None


def test_codex_reset_does_not_resume_against_old_epoch(tmp_path):
    from usage_bridge.adapters.codex_usage import reconcile_snapshots

    entries = [{"usage": row["payload"]["info"]["total_token_usage"]} for row in
               [tokens(100, 40, 20), tokens(10, 0, 2), tokens(120, 40, 25)]]
    requests, reasons = reconcile_snapshots(entries)
    assert sum(row.input for row in requests) == 60
    assert "counter-reset" in reasons


def test_unavailable_history_is_scrubbed_when_previews_disabled(tmp_path):
    import json

    from usage_bridge.config import CONFIG_REL

    repo = make_repo(tmp_path, branch="001-login")
    home = tmp_path / "codex"
    directory = repo / CONFIG_REL
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "usage-bridge-config.yml"
    config.write_text("privacy:\n  prompt_previews: true\n")
    write_rollout(home, repo, events=[turn(), prompt("private release secret"), tokens(100, 40, 20)])
    env = dict(os.environ, CODEX_HOME=str(home))
    assert run_capture("", repo, env).status == "ok"
    config.write_text("privacy:\n  prompt_previews: false\nruntimes:\n  enabled: []\n")
    assert run_capture("", repo, env).status == "ok"
    document = json.loads(next((repo / "specs/001-login/token-usage").glob("*.json")).read_text())
    assert "private release secret" not in json.dumps(document)


def test_missing_codex_parent_excludes_unproven_inherited_usage(tmp_path):
    import json

    repo = make_repo(tmp_path, branch="001-login")
    home = tmp_path / "codex"
    write_rollout(home, repo, parent="missing", events=[turn(), prompt(), tokens(100, 40, 20)])
    assert run_capture("", repo, dict(os.environ, CODEX_HOME=str(home))).status == "ok"
    document = json.loads(next((repo / "specs/001-login/token-usage").glob("*.json")).read_text())
    assert document["sessions"][0]["measurement"] == "activity_only"
    assert document["sessions"][0]["runs"][0]["tokens"] is None


def test_native_fork_metadata_is_recognized(tmp_path):
    import json

    path = write_rollout(tmp_path / "home", tmp_path / "repo", events=[turn(), prompt(), tokens(100, 40, 20)])
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["payload"]["forked_from_id"] = "parent"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    # Use the same descriptor discovery as a real rollout, without regenerating metadata.
    from codex_builders import context
    from usage_bridge.adapters.codex import CodexAdapter
    from usage_bridge.config import Config

    adapter = CodexAdapter()
    ctx = context(tmp_path / "repo", tmp_path / "home")
    assert adapter.parse(next(adapter.discover(ctx, Config())), ctx).parent_identity == ("codex", "parent")


def test_counter_spanning_phase_boundaries_stays_unassigned(tmp_path):
    from test_codex_accounting import parse

    digest = parse(tmp_path, [turn(), prompt("/speckit.plan"), prompt("/speckit.implement"), tokens(100, 40, 20)])
    assert digest.requests[0].event_index == -1
    assert digest.attribution_confidence == "partial"


@pytest.mark.parametrize("payload", [
    '{"type":"agent-turn-complete","thread-id":"s"}',
    '{"hook_event_name":"stop","conversation_id":"s"}',
])
def test_all_native_hooks_use_hard_supervision(payload, monkeypatch):
    from usage_bridge import cli

    reached = []
    monkeypatch.setattr(cli, "read_stdin", lambda *args: payload)
    monkeypatch.setattr(cli, "_supervised_hook", lambda *args: reached.append(True) or 0)
    assert cli.capture_entry() == 0
    assert reached == [True]


def test_cursor_wal_changes_invalidate_source_fingerprint(tmp_path, monkeypatch):
    import sqlite3

    from codex_builders import context
    from usage_bridge import tu_compat
    from usage_bridge.adapters.cursor import CursorAdapter
    from usage_bridge.config import Config

    database = tmp_path / "state.vscdb"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE test(value)")
        connection.commit()
        native = tu_compat.module().CursorSession("c", "sqlite", db_path=database, project_path=tmp_path)
        monkeypatch.setattr(tu_compat, "cursor_sessions", lambda *args, **kwargs: [native])
        adapter, ctx = CursorAdapter(), context(tmp_path, tmp_path)
        first = next(adapter.discover(ctx, Config())).stamps
        connection.execute("INSERT INTO test VALUES (1)")
        connection.commit()
        assert next(adapter.discover(ctx, Config())).stamps != first


def test_cursor_vendor_operation_is_bounded(tmp_path, monkeypatch):
    import sys
    import time

    from usage_bridge import tu_compat

    monkeypatch.setattr(tu_compat, "_cursor_worker_command",
                        lambda: [sys.executable, "-c", "import time; time.sleep(5)"], raising=False)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        tu_compat.cursor_sessions(tmp_path, tmp_path / "ledger", None, timeout=0.1)
    assert time.monotonic() - started < 1


def test_cursor_worker_uses_installed_bridge_over_project_module(tmp_path, monkeypatch):
    from usage_bridge import tu_compat

    project_module = tmp_path / "usage_bridge"
    project_module.mkdir()
    (project_module / "__init__.py").write_text('raise RuntimeError("project module must not run")')
    monkeypatch.chdir(tmp_path)
    assert tu_compat.cursor_sessions(tmp_path, tmp_path / "ledger", tmp_path / "missing", timeout=2) == []
