from codex_builders import context, prompt, tokens, turn, write_rollout
from usage_bridge.config import Config


def test_malformed_tail_retains_usage_and_discloses_gap(tmp_path):
    from usage_bridge.adapters.codex import CodexAdapter

    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    path = write_rollout(home, repo, events=[turn(), prompt(), tokens(100, 40, 20)])
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"partial":')
    reader, ctx = CodexAdapter(), context(repo, home)
    digest = reader.parse(next(reader.discover(ctx, Config())), ctx)
    assert sum(r.output for r in digest.requests) == 20
    assert digest.measurement == "partial"
    assert "malformed-record" in digest.reasons


def test_assistant_mentions_do_not_start_phase(tmp_path):
    from test_codex_accounting import parse

    entry = {"type": "response_item", "payload": {"role": "assistant", "type": "message",
                                                      "content": [{"text": "/speckit.implement"}]}}
    digest = parse(tmp_path, [turn(), prompt(), entry, tokens(100, 40, 20)])
    assert [event.name for event in digest.events] == ["/speckit.plan"]
