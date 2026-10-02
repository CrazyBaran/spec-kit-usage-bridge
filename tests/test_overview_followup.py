"""Regression coverage for Copilot's overview-only findings."""
import json

import pytest

from codex_builders import context, write_rollout
from usage_bridge.adapters.codex import CodexAdapter
from usage_bridge.adapters.cursor import CursorAdapter
from usage_bridge.adapters.cursor_ledger import append_event
from usage_bridge.config import Config
from usage_bridge.pipeline import feature_sources
from usage_bridge.render import merge_feature
from usage_bridge.schema import normalize_source


@pytest.mark.parametrize("setting", ["home", "extra"])
def test_codex_home_relative_discovery(tmp_path, hermetic_env, setting):
    repo = tmp_path / "repo"
    repo.mkdir()
    home = hermetic_env / "rollouts"
    write_rollout(home, repo)
    ctx = context(repo, home)
    cfg = Config()
    if setting == "home":
        ctx.env = {"CODEX_HOME": "~/rollouts"}
    else:
        ctx.env = {"CODEX_HOME": str(tmp_path / "missing")}
        cfg.codex_extra_dirs = ["~/rollouts"]
    assert [s.session_id for s in CodexAdapter().discover(ctx, cfg)] == ["s"]


def test_cursor_data_dir_expands_home(tmp_path, hermetic_env, monkeypatch):
    from usage_bridge import tu_compat

    seen = []
    def discover(project, ledger, data, **kwargs):
        seen.append(data)
        return []
    monkeypatch.setattr(tu_compat, "cursor_sessions", discover)
    list(CursorAdapter().discover(context(tmp_path, tmp_path), Config(cursor_data_dir="~/cursor")))
    assert seen == [hermetic_env / "cursor"]


@pytest.mark.parametrize("cwd,roots,expected", [
    ("a", ["b", "a"], "a"),
    ("a", ["a", "b"], "a"),
    (None, ["a"], "a"),
    (None, ["b", "a"], None),
    ("foreign", ["a"], None),
    (None, ["foreign", "a"], None),
    (None, [], None),
])
def test_cursor_ledger_has_one_proven_owner(tmp_path, monkeypatch, cwd, roots, expected):
    from usage_bridge.adapters import cursor_ledger

    a, b = tmp_path / "a", tmp_path / "longer-worktree"
    a.mkdir()
    b.mkdir()
    paths = {"a": a, "b": b, "foreign": tmp_path / "foreign"}
    ctx = context(a, tmp_path)
    ctx.checkouts = (a, b)
    monkeypatch.setattr(cursor_ledger, "current_branch", lambda owner: owner.name)
    payload = {"hook_event_name": "beforeSubmitPrompt", "conversation_id": "c", "generation_id": "g",
               "workspace_roots": [str(paths[root]) for root in roots], "prompt": "/speckit.plan"}
    if cwd:
        payload["cwd"] = str(paths[cwd] / "src")
    append_event(payload, ctx)
    path = next((ctx.runtime_dir / "cursor-ledgers").rglob("*.jsonl"))
    record = json.loads(path.read_text())
    assert record["workspace_roots"] == ([str(paths[expected])] if expected else [])
    assert record.get("branch") == (paths[expected].name if expected else None)
    sources = list(CursorAdapter().discover(ctx, Config(cursor_data_dir=str(tmp_path / "missing"))))
    assert [source.session_id for source in sources] == (["c"] if expected else [])


def source(runtime):
    return {"schema": "usage-bridge/feature-usage", "schema_version": 2,
            "author": {"name": "review"}, "feature": {"id": "001-review", "directory": "specs/001-review"},
            "sessions": [{"session_id": "s", "runtime": runtime, "runs": []}]}


@pytest.mark.parametrize("runtime", [[], {}, None, 42, True, ""])
def test_malformed_runtime_is_rejected(runtime):
    with pytest.raises(ValueError, match="runtime"):
        normalize_source(source(runtime))


def test_corrupt_runtime_does_not_suppress_healthy_author(tmp_path):
    directory = tmp_path / "specs/001-review/token-usage"
    directory.mkdir(parents=True)
    (directory / "bad.json").write_text(json.dumps(source([])))
    good = source("codex")
    good["author"]["name"] = "healthy"
    (directory / "good.json").write_text(json.dumps(good))
    sources = feature_sources(tmp_path, Config(), "specs/001-review")
    assert len(sources) == 1
    assert merge_feature(sources)["runtimes"] == ["codex"]
