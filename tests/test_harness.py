import json
import os
from pathlib import Path

from builders import SessionBuilder, make_repo, projects_root, slug


def test_home_is_isolated(hermetic_env):
    assert Path.home() == hermetic_env


def test_token_usage_env_points_into_tmp(tmp_path):
    for var in ("TOKEN_USAGE_PROJECTS_DIR", "TOKEN_USAGE_LEDGER_DIR", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR"):
        assert Path(os.environ[var]).is_relative_to(tmp_path)


def test_package_version():
    import yaml

    import usage_bridge

    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / 'extension.yml').read_text(encoding='utf-8'))
    assert usage_bridge.__version__ == manifest['extension']['version']


def test_builder_writes_claude_shaped_session(tmp_path):
    repo = make_repo(tmp_path)
    s = SessionBuilder("s1", cwd=repo, branch="001-login")
    s.command("/speckit-plan")
    s.reply("req_1", input=10, output=5, cache_read=100, cache_5m=20)
    path = s.write()
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert path.parent == projects_root() / slug(repo) and path.name == "s1.jsonl"
    assert "<command-name>/speckit-plan</command-name>" in lines[0]["message"]["content"]
    usage = lines[1]["message"]["usage"]
    assert lines[1]["requestId"] == "req_1" and usage["cache_creation"]["ephemeral_5m_input_tokens"] == 20
    assert usage["cache_creation_input_tokens"] == 20 and usage["input_tokens"] == 10
    assert all(x["gitBranch"] == "001-login" and x["cwd"] == str(repo) and x["sessionId"] == "s1" for x in lines)


def test_builder_streamed_chunks_share_request_id(tmp_path):
    s = SessionBuilder("s1", cwd=make_repo(tmp_path))
    s.reply("r1", output=50, chunks=3)
    lines = [json.loads(x) for x in s.write().read_text(encoding="utf-8").splitlines()]
    assert [x["requestId"] for x in lines] == ["r1"] * 3
    assert [x["message"]["usage"]["output_tokens"] for x in lines][-1] == 50


def test_builder_subagent_layout(tmp_path):
    s = SessionBuilder("s1", cwd=make_repo(tmp_path))
    child = s.subagent("workflows/w1/agent-b2", agent_type="Explore", spawn_depth=2)
    child.reply("rb", output=7, stop_reason="tool_use")
    main = s.write()
    agent = main.parent / "s1" / "subagents" / "workflows" / "w1" / "agent-b2.jsonl"
    meta = json.loads(agent.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert agent.exists() and meta["agentType"] == "Explore" and meta["spawnDepth"] == 2
    assert all(json.loads(x)["isSidechain"] is True for x in agent.read_text(encoding="utf-8").splitlines())
