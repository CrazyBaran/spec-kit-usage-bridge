from codex_builders import context, write_rollout
from usage_bridge.config import Config


def adapter():
    from usage_bridge.adapters.codex import CodexAdapter

    return CodexAdapter()


def test_discovers_only_owned_sessions(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    write_rollout(home, repo)
    write_rollout(home, tmp_path / "repo-sibling", "unrelated")
    assert [s.session_id for s in adapter().discover(context(repo, home), Config())] == ["s"]


def test_archive_copy_is_one_identity(tmp_path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    write_rollout(home, repo)
    write_rollout(home, repo, archived=True)
    found = list(adapter().discover(context(repo, home), Config()))
    assert len(found) == 1
    assert len(found[0].native["paths"]) == 2


def test_live_tail_retains_valid_metadata(tmp_path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    path = write_rollout(home, repo)
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"partial":')
    assert len(list(adapter().discover(context(repo, home), Config()))) == 1


def test_deadline_stops_discovery(tmp_path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    write_rollout(home, repo)
    ctx = context(repo, home)
    ctx.deadline = 0
    assert list(adapter().discover(ctx, Config())) == []


def test_index_avoids_reparsing_unchanged_metadata(tmp_path, monkeypatch):
    repo, home = tmp_path / "repo with spaces", tmp_path / "home"
    repo.mkdir()
    write_rollout(home, repo)
    reader = adapter()
    assert len(list(reader.discover(context(repo, home), Config()))) == 1
    monkeypatch.setattr(reader, "_metadata", lambda path: (_ for _ in ()).throw(AssertionError("read twice")))
    assert len(list(reader.discover(context(repo, home), Config()))) == 1


def test_missing_ownership_excluded(tmp_path):
    import json

    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    path = write_rollout(home, repo)
    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": "s"}}), encoding="utf-8")
    assert list(adapter().discover(context(repo, home), Config())) == []
