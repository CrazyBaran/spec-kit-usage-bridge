"""Regression coverage for the v0.2 and Copilot review findings."""
import json
import os
from contextlib import contextmanager

import pytest

from builders import _git, make_repo
from codex_builders import context, prompt, tokens, turn, write_rollout
from usage_bridge import tu_compat
from usage_bridge.adapters.codex import CodexAdapter
from usage_bridge.adapters.cursor import CursorAdapter
from usage_bridge.config import Config
from usage_bridge.pipeline import run_capture


def test_previous_codex_cross_project_finding(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    switched = turn()
    switched['payload']['cwd'] = str(b)
    write_rollout(tmp_path / 'home', a, events=[turn(), prompt(), tokens(100, 0, 20),
                                               switched, tokens(200, 0, 40)])
    reader = CodexAdapter()
    ctx = context(a, tmp_path / 'home')
    digest = reader.parse(next(reader.discover(ctx, Config())), ctx)
    assert sum(row.input for row in digest.requests) == 100
    assert digest.measurement == 'exact'
    ctx_b = context(b, tmp_path / 'home')
    owned_b = reader.parse(next(reader.discover(ctx_b, Config())), ctx_b)
    assert sum(row.input for row in owned_b.requests) == 100


def test_previous_cursor_worktree_finding(tmp_path):
    main = make_repo(tmp_path, features=('001-login', '002-search'), branch='001-login')
    work = tmp_path / 'work'
    _git(main, 'worktree', 'add', '-b', '002-search', str(work))
    payload = {'conversation_id':'c', 'generation_id':'g', 'workspace_roots':[str(work)],
               'cwd':str(work), 'hook_event_name':'beforeSubmitPrompt', 'prompt':'/speckit.plan'}
    result = run_capture(json.dumps(payload), work, dict(os.environ))
    assert result.status == 'ok'
    assert not (work / 'specs/001-login/token-usage.md').exists()
    assert (work / 'specs/002-search/token-usage.md').exists()


def test_previous_cursor_mixed_zero_finding(tmp_path):
    ctx = context(tmp_path, tmp_path)
    reader = CursorAdapter()
    for generation, amount in [('zero', 0), ('nonzero', 10)]:
        base = {'conversation_id':'c', 'generation_id':generation, 'workspace_roots':[str(tmp_path)]}
        reader.record({**base, 'hook_event_name':'beforeSubmitPrompt', 'prompt':'/speckit.plan'}, ctx)
        reader.record({**base, 'hook_event_name':'stop', 'model':'claude-sonnet-4-6',
                       'input_tokens':amount, 'output_tokens':amount, 'cache_read_tokens':0,
                       'cache_write_tokens':0}, ctx)
    source = next(reader.discover(ctx, Config(cursor_data_dir=str(tmp_path / 'missing'))))
    assert tu_compat.cursor_parse(source.native, timeout=2)['measurement'] == 'exact'
    digest = reader.parse(source, ctx)
    assert digest.measurement == 'exact'
    assert digest.requests[0].input == 0


def test_copilot_export_runs_in_parent(tmp_path, monkeypatch):
    exports = tmp_path / 'exports'
    exports.mkdir()
    path = exports / 'owned.json'
    path.write_text(json.dumps({'id': 'c', 'messages': [], 'cwd':str(tmp_path)}))
    observed = []
    original = tu_compat.cursor_export
    def locate(export, **kwargs):
        if kwargs.get('timeout') is None:
            observed.append(os.getpid())
        return original(export, **kwargs)
    monkeypatch.setattr(tu_compat, 'cursor_export', locate)
    list(CursorAdapter().discover(context(tmp_path, tmp_path),
         Config(cursor_data_dir=str(tmp_path / 'missing'), cursor_extra_dirs=[str(exports)])))
    assert observed == []


def test_copilot_probe_happens_before_supervision(tmp_path, monkeypatch):
    from pathlib import Path

    from usage_bridge import cli
    observed = []
    class Stream:
        def readline(self, *args):
            observed.append(('probe', args))
            return '{}'
    @contextmanager
    def opened(*args, **kwargs):
        yield Stream()
    monkeypatch.setattr(Path, 'open', opened)
    monkeypatch.setattr(cli, 'read_stdin', lambda *args: json.dumps({'session_id':'s',
                        'transcript_path':str(tmp_path / 'arbitrary')}))
    monkeypatch.setattr(cli, '_supervised_hook', lambda *args: observed.append(('supervised',)) or 0)
    assert cli.capture_entry() == 0
    assert observed == [('supervised',)]


def test_copilot_attribution_downgrades_measurement(tmp_path):
    write_rollout(tmp_path / 'home', tmp_path, events=[turn(), prompt('/speckit.plan'),
                  prompt('/speckit.implement'), tokens(100, 0, 20)])
    ctx = context(tmp_path, tmp_path / 'home')
    reader = CodexAdapter()
    digest = reader.parse(next(reader.discover(ctx, Config())), ctx)
    assert digest.attribution_confidence == 'partial'
    assert digest.measurement == 'exact'
    assert all(row.measurement == 'exact' for row in digest.requests)


def test_copilot_none_call_rendering():
    from usage_bridge.render import render_all_md
    report = {'features':[{'id':'001-login', 'sessions':1, 'calls':None, 'tokens':None,
                          'cost_usd':None, 'phases':['plan']}], 'phase_averages':[],
              'project':{'calls':None}, 'unattributed':{'calls':None}}
    assert 'None' not in render_all_md(report)


def test_copilot_activity_only_not_attributed(tmp_path):
    repo = make_repo(tmp_path, branch='main')
    (repo / '.specify/feature.json').write_text('{"feature_directory":"specs/001-login"}')
    path = write_rollout(tmp_path / 'codex', repo, events=[turn(), prompt()])
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['payload']['git']['branch'] = 'main'
    path.write_text('\n'.join(json.dumps(row) for row in rows))
    result = run_capture(json.dumps({'type':'agent-turn-complete', 'thread-id':'s', 'cwd':str(repo)}),
                         repo, dict(os.environ, CODEX_HOME=str(tmp_path / 'codex')))
    assert result.status == 'ok'
    assert (repo / 'specs/001-login/token-usage.md').exists()


def test_copilot_priced_model_labeled_unpriced(tmp_path):
    repo = make_repo(tmp_path, branch='001-login')
    write_rollout(tmp_path / 'codex', repo, events=[turn(), prompt(),
                  tokens(100, 0, 20, cache_write_input_tokens=10)])
    result = run_capture('', repo, dict(os.environ, CODEX_HOME=str(tmp_path / 'codex')))
    assert result.status == 'ok'
    data = json.loads(next((repo / 'specs/001-login/token-usage').glob('*.json')).read_text())
    assert data['unpriced_models'] == []


def test_copilot_malformed_session_crashes_normalizer():
    from usage_bridge.schema import normalize_source
    with pytest.raises(ValueError):
        normalize_source({'schema':'usage-bridge/feature-usage', 'schema_version':2, 'sessions':[None]})


def test_corrupt_author_source_is_skipped_without_rewriting_it(tmp_path):
    repo = make_repo(tmp_path, branch='001-login')
    directory = repo / 'specs/001-login/token-usage'
    directory.mkdir()
    broken = directory / 'other.machine.json'
    original = '{"schema":"usage-bridge/feature-usage","schema_version":2,"sessions":[null]}'
    broken.write_text(original)
    write_rollout(tmp_path / 'codex', repo, events=[turn(), prompt(), tokens(100, 0, 20)])
    result = run_capture('', repo, dict(os.environ, CODEX_HOME=str(tmp_path / 'codex')))
    assert result.status == 'ok'
    assert broken.read_text() == original
    assert (repo / 'specs/001-login/token-usage.md').exists()


def test_cross_project_interval_without_boundary_counter_is_not_assigned(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    switched = turn()
    switched['payload']['cwd'] = str(b)
    write_rollout(tmp_path / 'home', a, events=[turn(), prompt(), switched, tokens(200, 0, 40),
                  tokens(250, 0, 50, stamp='2026-10-01T08:00:04Z')])
    reader = CodexAdapter()
    ctx = context(b, tmp_path / 'home')
    digest = reader.parse(next(reader.discover(ctx, Config())), ctx)
    assert sum(row.input for row in digest.requests) == 50
    assert digest.measurement == 'partial'
    assert 'workspace-interval-ambiguous' in digest.reasons


def test_cursor_missing_generation_usage_stays_missing(tmp_path):
    ctx = context(tmp_path, tmp_path)
    reader = CursorAdapter()
    for generation in ['missing', 'measured']:
        base = {'conversation_id':'c', 'generation_id':generation, 'workspace_roots':[str(tmp_path)]}
        reader.record({**base, 'hook_event_name':'beforeSubmitPrompt', 'prompt':'/speckit.plan'}, ctx)
        completion = {**base, 'hook_event_name':'stop', 'model':'claude-sonnet-4-6'}
        if generation == 'measured':
            completion.update(input_tokens=10, output_tokens=10, cache_read_tokens=0, cache_write_tokens=0)
        reader.record(completion, ctx)
    digest = reader.parse(next(reader.discover(ctx, Config(cursor_data_dir=str(tmp_path / 'missing')))), ctx)
    assert digest.measurement == 'partial'
    assert digest.requests[0].input is None


def test_export_operation_uses_remaining_timeout(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(tu_compat, '_cursor_worker_command',
                        lambda: [sys.executable, '-c', 'import time; time.sleep(5)'])
    with pytest.raises(TimeoutError):
        tu_compat.cursor_export(tmp_path / 'export.json', timeout=0.1, checkouts=[tmp_path])
