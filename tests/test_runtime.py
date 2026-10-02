import pytest

from usage_bridge.runtime import detect

CLAUDE = '{"session_id":"s1","transcript_path":"C:/p/s1.jsonl","cwd":"C:/r","hook_event_name":"Stop"}'


@pytest.mark.parametrize("raw,kind", [
    (CLAUDE, "claude"), ("\ufeff" + CLAUDE, "claude"), ('{"conversation_id":"c","generation_id":"g"}', "cursor"),
    ("", "manual"), ("  \n", "manual"), ("{}", "manual"),
    ("not json", "unknown"), ("[1, 2]", "unknown"), ('{"session_id": 5, "transcript_path": "x"}', "unknown")])
def test_detect(raw, kind):
    assert detect(raw).kind == kind


def test_codex_discriminator_and_hint():
    from usage_bridge.runtime import detect

    assert detect('{"type":"agent-turn-complete","thread-id":"s"}').kind == "codex"
    overlapping = '{"hook_event_name":"Stop","transcript_path":"rollout.jsonl","session_id":"s"}'
    assert detect(overlapping, integration_hint="codex").kind == "codex"
    assert detect(overlapping, integration_hint="unrecognized").kind == "unknown"

