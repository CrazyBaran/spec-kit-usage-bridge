import json
import os

from builders import make_repo
from codex_builders import prompt, tokens, turn, write_rollout
from usage_bridge.config import CONFIG_REL
from usage_bridge.pipeline import run_capture


def source(repo):
    return json.loads(next((repo / "specs/001-login/token-usage").glob("*.json")).read_text(encoding="utf-8"))


def test_codex_only_capture_and_repeat(tmp_path):
    repo = make_repo(tmp_path, branch="001-login")
    home = tmp_path / "codex"
    write_rollout(home, repo, events=[turn(), prompt(), tokens(100, 40, 20)])
    env = dict(os.environ, CODEX_HOME=str(home))
    result = run_capture("", repo, env)
    assert result.status == "ok", result.error
    data = source(repo)
    assert data["schema_version"] == 2
    assert data["sessions"][0]["runtime"] == "codex"
    assert data["sessions"][0]["runs"][0]["usage"]["input"] == 60
    assert run_capture("", repo, env).features_written == []


def test_cursor_hook_activity_capture_is_silent_mode(tmp_path):
    repo = make_repo(tmp_path, branch="001-login")
    base = {"conversation_id": "c", "generation_id": "g", "workspace_roots": [str(repo)], "cwd": str(repo)}
    result = run_capture(json.dumps({**base, "hook_event_name": "beforeSubmitPrompt", "prompt": "/speckit.plan"}),
                         repo, dict(os.environ))
    assert result.mode == "hook"
    assert result.status == "ok", result.error
    data = source(repo)
    assert data["sessions"][0]["runtime"] == "cursor"
    assert data["sessions"][0]["runs"][0]["usage"]["input"] is None


def test_cursor_prompt_capture_on_main_uses_active_feature(tmp_path):
    repo = make_repo(tmp_path, branch="main")
    (repo / ".specify/feature.json").write_text('{"feature_directory":"specs/001-login"}', encoding="utf-8")
    payload = {"conversation_id": "c", "generation_id": "g", "cwd": str(repo),
               "workspace_roots": [str(repo)], "hook_event_name": "beforeSubmitPrompt", "prompt": "/speckit.plan"}
    result = run_capture(json.dumps(payload), repo, dict(os.environ))
    assert result.features_written == ["specs/001-login"]


def test_disappeared_source_and_disabled_runtime_preserve_history(tmp_path):
    repo = make_repo(tmp_path, branch="001-login")
    home = tmp_path / "codex"
    path = write_rollout(home, repo, events=[turn(), prompt(), tokens(100, 40, 20)])
    env = dict(os.environ, CODEX_HOME=str(home))
    assert run_capture("", repo, env).status == "ok"
    before = source(repo)
    path.unlink()
    directory = repo / CONFIG_REL
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "usage-bridge-config.yml").write_text("runtimes:\n  enabled: []\n", encoding="utf-8")
    assert run_capture("", repo, env).status in ("ok", "partial")
    assert source(repo)["sessions"] == before["sessions"]


def test_adapter_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    from usage_bridge.adapters.codex import CodexAdapter

    repo = make_repo(tmp_path, branch="001-login")
    home = tmp_path / "codex"
    write_rollout(home, repo, events=[turn(), prompt(), tokens(100, 40, 20)])
    env = dict(os.environ, CODEX_HOME=str(home))
    assert run_capture("", repo, env).status == "ok"
    previous = source(repo)["sessions"]
    monkeypatch.setattr(CodexAdapter, "discover", lambda *args: (_ for _ in ()).throw(OSError("unavailable")))
    assert run_capture("", repo, env).status == "partial"
    assert source(repo)["sessions"] == previous
