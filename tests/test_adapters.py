import time

from usage_bridge.digest import Request, SessionDigest


def test_runtime_identity_is_distinct():
    from usage_bridge.adapters.base import SourceDescriptor

    assert SourceDescriptor("claude", "same", "jsonl", None, ()).identity != (
        SourceDescriptor("codex", "same", "jsonl", None, ()).identity)


def test_legacy_digest_defaults_and_metadata_round_trip():
    from usage_bridge.adapters.base import Capabilities

    legacy = SessionDigest("s", "path", None, None, None)
    assert legacy.runtime == "claude"
    legacy.runtime = "codex"
    legacy.measurement = "partial"
    legacy.reasons = ["counter-reset"]
    legacy.capabilities = Capabilities()
    legacy.requests = [Request("r", None, "unknown", None, 1, 0, 0, 0, 0, kind="counter_delta")]
    restored = SessionDigest.from_json(legacy.to_json())
    assert restored.runtime == "codex"
    assert restored.reasons == ["counter-reset"]
    assert restored.requests[0].input is None
    assert not restored.capabilities.request_counts


def test_parse_context_deadline(tmp_path):
    from usage_bridge.adapters.base import ParseContext

    context = ParseContext((tmp_path,), {}, tmp_path, False, 1.0, lambda: 2.0)
    assert context.expired()
    context.deadline = time.monotonic() + 5
    context.clock = time.monotonic
    assert not context.expired()


def test_claude_adapter_matches_existing_digest(tmp_path):
    import os

    from builders import single_session
    from usage_bridge.adapters import get_adapter
    from usage_bridge.adapters.base import ParseContext
    from usage_bridge.config import Config
    from usage_bridge.digest import digest_session
    from usage_bridge.discovery import discover, projects_roots

    repo, _ = single_session(tmp_path)
    context = ParseContext((repo,), dict(os.environ), tmp_path / "runtime", False,
                           time.monotonic() + 15, time.monotonic)
    adapter = get_adapter("claude")
    sources = list(adapter.discover(context, Config()))
    expected = digest_session(discover([repo], projects_roots({}, os.environ), [])[0])
    assert adapter.parse(sources[0], context).to_json() == expected.to_json()
