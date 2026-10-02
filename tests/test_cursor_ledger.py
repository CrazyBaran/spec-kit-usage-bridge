import json

from codex_builders import context


def test_default_privacy_keeps_only_phase_and_usage(tmp_path):
    from usage_bridge.adapters.cursor_ledger import append_event

    ctx = context(tmp_path, tmp_path)
    append_event({"hook_event_name": "beforeSubmitPrompt", "conversation_id": "c", "generation_id": "g",
                  "workspace_roots": [str(tmp_path)], "prompt": "sensitive ordinary prompt"}, ctx)
    append_event({"hook_event_name": "beforeSubmitPrompt", "conversation_id": "c", "generation_id": "g2",
                  "workspace_roots": [str(tmp_path)], "prompt": "/speckit.plan sensitive arguments"}, ctx)
    text = next((ctx.runtime_dir / "cursor-ledgers").rglob("*.jsonl")).read_text()
    assert "sensitive" not in text
    assert "/speckit.plan" in text


def test_opt_in_limit_and_preview_cleanup(tmp_path):
    from usage_bridge.adapters.cursor_ledger import append_event, remove_previews

    ctx = context(tmp_path, tmp_path)
    ctx.keep_previews = True
    append_event({"hook_event_name": "beforeSubmitPrompt", "conversation_id": "c", "generation_id": "g",
                  "workspace_roots": [str(tmp_path)], "prompt": "secret" * 100}, ctx)
    path = next((ctx.runtime_dir / "cursor-ledgers").rglob("*.jsonl"))
    assert len(json.loads(path.read_text())["prompt"]) == 120
    remove_previews(path.parent)
    assert "secret" not in path.read_text()


def test_ledger_identity_is_path_safe(tmp_path):
    from usage_bridge.adapters.cursor_ledger import append_event

    ctx = context(tmp_path, tmp_path)
    append_event({"hook_event_name": "stop", "conversation_id": "../../escape", "generation_id": "g",
                  "workspace_roots": [str(tmp_path)]}, ctx)
    paths = list((ctx.runtime_dir / "cursor-ledgers").rglob("*.jsonl"))
    assert len(paths) == 1
    assert ".." not in paths[0].name
