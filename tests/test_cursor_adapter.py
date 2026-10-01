import os

from codex_builders import context
from usage_bridge.config import Config


def captured(ctx, with_tokens=True):
    from usage_bridge.adapters.cursor_ledger import append_event

    base = {"conversation_id": "c", "generation_id": "g", "workspace_roots": [str(ctx.checkouts[0])]}
    append_event({**base, "hook_event_name": "beforeSubmitPrompt", "prompt": "/speckit.plan"}, ctx)
    completion = {**base, "hook_event_name": "stop", "model": "claude-sonnet-4-6"}
    if with_tokens:
        completion.update(input_tokens=100, output_tokens=20, cache_read_tokens=40, cache_write_tokens=0)
    append_event(completion, ctx)
    append_event(completion, ctx)


def test_duplicate_generation_is_counted_once(tmp_path):
    from usage_bridge.adapters.cursor import CursorAdapter

    ctx = context(tmp_path, tmp_path)
    captured(ctx)
    reader = CursorAdapter()
    source = next(reader.discover(ctx, Config(cursor_data_dir=str(tmp_path / "missing"))))
    digest = reader.parse(source, ctx)
    assert sum(r.input for r in digest.requests) == 60
    assert sum(r.output for r in digest.requests) == 20
    assert digest.requests[0].kind == "segment"
    assert not digest.capabilities.request_counts
    assert digest.measurement == "exact"


def test_activity_only_usage_is_null(tmp_path):
    from usage_bridge.adapters.cursor import CursorAdapter

    ctx = context(tmp_path, tmp_path)
    captured(ctx, False)
    reader = CursorAdapter()
    digest = reader.parse(next(reader.discover(ctx, Config(cursor_data_dir=str(tmp_path / "missing")))), ctx)
    assert digest.measurement == "activity_only"
    assert digest.requests[0].input is None
    assert digest.events[0].name == "/speckit.plan"


def test_scoped_environment_is_restored_on_error(tmp_path, monkeypatch):
    from usage_bridge import tu_compat

    old = dict(os.environ)
    adapter = tu_compat.module().get_runtime_adapter("cursor")
    monkeypatch.setattr(adapter, "iter_sessions", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("broken")))
    import pytest

    with pytest.raises(RuntimeError):
        tu_compat.cursor_sessions(tmp_path, tmp_path / "cursor-ledgers", tmp_path)
    assert dict(os.environ) == old


def test_ledger_precedes_export_and_unrelated_export_is_rejected(tmp_path):
    import json

    from usage_bridge.adapters.cursor import CursorAdapter

    ctx = context(tmp_path, tmp_path)
    captured(ctx)
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "same.json").write_text(json.dumps({"id": "c", "workspace_roots": [str(tmp_path)],
                                                  "messages": []}), encoding="utf-8")
    (exports / "unrelated.json").write_text(json.dumps({"id": "other", "workspace_roots": [str(tmp_path) + "-other"],
                                                       "messages": []}), encoding="utf-8")
    sources = list(CursorAdapter().discover(ctx, Config(cursor_extra_dirs=[str(exports)],
                                                       cursor_data_dir=str(tmp_path / "missing"))))
    assert len(sources) == 1
    assert sources[0].source_kind == "hook_ledger"
