import json
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from builders import make_repo
from codex_builders import context, prompt, tokens, turn, write_rollout
from usage_bridge.adapters.base import ParseContext
from usage_bridge.adapters.codex import CodexAdapter
from usage_bridge.adapters.codex_usage import exclude_inherited_prefix
from usage_bridge.adapters.cursor import CursorAdapter
from usage_bridge.adapters.cursor_ledger import append_event
from usage_bridge.config import Config
from usage_bridge.paths import runtime_dir
from usage_bridge.pipeline import run_capture


def ledger_context(repo):
    return ParseContext((repo,), dict(os.environ), runtime_dir(repo, repo), False,
                        time.monotonic() + 15, time.monotonic)


def cursor_events(ctx, model='unknown', zero=False):
    base = {'conversation_id': 'c', 'generation_id': 'g', 'workspace_roots': [str(ctx.checkouts[0])]}
    append_event({**base, 'hook_event_name': 'beforeSubmitPrompt', 'prompt': '/speckit.plan'}, ctx)
    payload = {**base, 'hook_event_name': 'stop', 'model': model}
    if zero:
        payload.update(input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0)
    append_event(payload, ctx)


def test_inherited_only_child_has_activity_coverage(tmp_path):
    repo = make_repo(tmp_path)
    home = Path(os.environ['CODEX_HOME'])
    write_rollout(home, repo, events=[turn(), prompt(), tokens(100, 0, 10)])
    ctx = context(repo, home)
    adapter = CodexAdapter()
    parent = adapter.parse(next(adapter.discover(ctx, Config())), ctx)
    child = replace(parent, session_id='child', parent_identity=('codex', 's'))
    result = exclude_inherited_prefix(child, parent)
    assert result.requests == []
    assert result.measurement == 'activity_only'


def test_all_zero_cursor_is_measured(tmp_path):
    repo = make_repo(tmp_path)
    ctx = ledger_context(repo)
    cursor_events(ctx, 'claude-sonnet-4-6', zero=True)
    adapter = CursorAdapter()
    digest = adapter.parse(next(adapter.discover(ctx, Config())), ctx)
    assert digest.measurement == 'exact'
    assert digest.requests[0].flat() == dict(input=0, output=0, cache_read=0, cache_5m=0, cache_1h=0)
    assert digest.requests[0].measurement == 'exact'


def test_legacy_cursor_cache_is_reparsed(tmp_path):
    repo = make_repo(tmp_path, branch='001-login')
    ctx = ledger_context(repo)
    cursor_events(ctx, 'claude-sonnet-4-6', zero=True)
    assert run_capture('', repo, dict(os.environ)).status == 'ok'
    cache_path = next((ctx.runtime_dir / 'adapter-cache').glob('*.json'))
    cached = json.loads(cache_path.read_text())
    cached['key']['v'] = 5
    cached['digest']['measurement'] = 'activity_only'
    for row in cached['digest']['requests']:
        row['measurement'] = 'activity_only'
        for key in ['input', 'output', 'cache_read', 'cache_5m', 'cache_1h']:
            row[key] = None
    cache_path.write_text(json.dumps(cached))
    assert run_capture('', repo, dict(os.environ)).status == 'ok'
    source = next((repo / 'specs/001-login/token-usage').glob('*.json'))
    assert json.loads(source.read_text())['sessions'][0]['measurement'] == 'exact'


def test_ledger_write_survives_permission_hardening_failure(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    ctx = ledger_context(repo)
    ctx.keep_previews = True
    def denied(*args):
        raise OSError('permissions unavailable')
    monkeypatch.setattr(os, 'chmod', denied)
    cursor_events(ctx)
    assert next((ctx.runtime_dir / 'cursor-ledgers').rglob('*.jsonl')).read_text()


@pytest.mark.parametrize('zero', [False, True])
def test_unmeasured_or_zero_unknown_model_is_not_unpriced_usage(tmp_path, zero):
    repo = make_repo(tmp_path, branch='001-login')
    cursor_events(ledger_context(repo), zero=zero)
    assert run_capture('', repo, dict(os.environ)).status == 'ok'
    data = json.loads(next((repo / 'specs/001-login/token-usage').glob('*.json')).read_text())
    assert data['unpriced_models'] == []


def test_retained_sessions_keep_unpriced_diagnostics(tmp_path):
    repo = make_repo(tmp_path)
    home = Path(os.environ['CODEX_HOME'])
    write_rollout(home, repo, events=[turn('gpt-mystery'), prompt(), tokens(100, 0, 10)])
    assert run_capture('', repo, dict(os.environ)).status == 'ok'
    path = next((repo / 'specs/001-login/token-usage').glob('*.json'))
    assert json.loads(path.read_text())['unpriced_models'] == ['gpt-mystery']
    assert run_capture('', repo, dict(os.environ, SPECKIT_USAGE_BRIDGE_RUNTIMES_ENABLED='claude')).status == 'ok'
    data = json.loads(path.read_text())
    assert data['sessions'][0]['session_id'] == 's'
    assert data['unpriced_models'] == ['gpt-mystery']


@pytest.mark.skipif(os.name != 'posix', reason='POSIX directory ownership permissions')
def test_preview_ledger_directory_is_owner_only(tmp_path):
    repo = make_repo(tmp_path)
    ctx = ledger_context(repo)
    ctx.keep_previews = True
    old_umask = os.umask(0o022)
    try:
        cursor_events(ctx)
    finally:
        os.umask(old_umask)
    directory = ctx.runtime_dir / 'cursor-ledgers/cursor'
    assert directory.stat().st_mode & 0o077 == 0
