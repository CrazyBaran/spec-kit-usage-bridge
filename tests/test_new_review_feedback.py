import json
import os

import pytest

from builders import SessionBuilder, make_repo
from codex_builders import context, prompt, tokens, turn, write_rollout
from usage_bridge.adapters.codex import CodexAdapter
from usage_bridge.adapters.cursor_ledger import remove_previews
from usage_bridge.config import Config
from usage_bridge.digest import Request
from usage_bridge.metrics import run_summary
from usage_bridge.phases import Run
from usage_bridge.pipeline import feature_sources, run_capture
from usage_bridge.render import author_file, render_feature_md
from usage_bridge.schema import normalize_source
from usage_bridge.tu_compat import Rates


def test_conflicting_codex_copies_count_only_common_prefix(tmp_path):
    home = tmp_path / 'codex'
    shared = [turn(), prompt(), tokens(100, 0, 20)]
    write_rollout(home, tmp_path, events=[*shared, tokens(150, 0, 30)])
    write_rollout(home, tmp_path, archived=True,
                  events=[*shared, tokens(900, 0, 180), tokens(1000, 0, 200)])
    reader = CodexAdapter()
    ctx = context(tmp_path, home)
    digest = reader.parse(next(reader.discover(ctx, Config())), ctx)
    assert sum(row.input for row in digest.requests) == 100
    assert sum(row.output for row in digest.requests) == 20
    assert digest.measurement == 'partial'
    assert 'conflicting-session-copies' in digest.reasons


def test_codex_prefix_copy_keeps_proven_extension(tmp_path):
    home = tmp_path / 'codex'
    shared = [turn(), prompt(), tokens(100, 0, 20)]
    write_rollout(home, tmp_path, events=shared)
    write_rollout(home, tmp_path, archived=True, events=[*shared, tokens(150, 0, 30)])
    reader = CodexAdapter()
    ctx = context(tmp_path, home)
    digest = reader.parse(next(reader.discover(ctx, Config())), ctx)
    assert sum(row.input for row in digest.requests) == 150
    assert digest.measurement == 'exact'


def test_short_copy_cannot_hide_divergence_between_longer_copies(tmp_path):
    home = tmp_path / 'codex'
    shared = [turn(), prompt(), tokens(100, 0, 20)]
    write_rollout(home, tmp_path, events=shared)
    write_rollout(home, tmp_path, archived=True, events=[*shared, tokens(200, 0, 40)])
    extra = tmp_path / 'extra'
    write_rollout(extra, tmp_path, events=[*shared, tokens(900, 0, 180), tokens(1000, 0, 200)])
    reader = CodexAdapter()
    ctx = context(tmp_path, home)
    digest = reader.parse(next(reader.discover(ctx, Config(codex_extra_dirs=[str(extra)]))), ctx)
    assert sum(row.input for row in digest.requests) == 100
    assert digest.measurement == 'partial'


@pytest.mark.parametrize('field', ['author', 'feature'])
def test_source_metadata_is_required(field):
    source = author_file('001-login', 'specs/001-login', 'a', 'm', {}, [], 'complete', [], [])
    source.pop(field)
    with pytest.raises(ValueError, match=field):
        normalize_source(source)


@pytest.mark.parametrize('location', ['session', 'run'])
def test_unknown_measurement_is_rejected(location):
    session = {'session_id':'s', 'runs':[{'phase':'plan'}]}
    target = session if location == 'session' else session['runs'][0]
    target['measurement'] = 'unsupported'
    source = author_file('001-login', 'specs/001-login', 'a', 'm', {}, [session], 'complete', [], [])
    with pytest.raises(ValueError, match='measurement'):
        normalize_source(source)


def test_invalid_metadata_source_is_isolated_during_capture(tmp_path):
    repo = make_repo(tmp_path, branch='001-login')
    directory = repo / 'specs/001-login/token-usage'
    directory.mkdir()
    bad = directory / 'other.machine.json'
    original = '{"schema":"usage-bridge/feature-usage","schema_version":2,"sessions":[]}'
    bad.write_text(original)
    home = tmp_path / 'codex'
    write_rollout(home, repo, events=[turn(), prompt(), tokens(100, 0, 20)])
    result = run_capture('', repo, dict(os.environ, CODEX_HOME=str(home)))
    assert result.status == 'ok', result.error
    assert bad.read_text() == original
    assert len(feature_sources(repo, Config(), 'specs/001-login')) == 1


def test_unpriced_subagent_model_is_in_capture_diagnostics(tmp_path):
    repo = make_repo(tmp_path, branch='001-login')
    parent = SessionBuilder('s', repo, branch='001-login')
    parent.command('/speckit.plan')
    parent.reply('parent', output=10)
    child = parent.subagent('agent-child')
    child.reply('child', model='unpriced-child-model', output=20)
    parent.write()
    result = run_capture('', repo, dict(os.environ))
    assert result.status == 'ok', result.error
    data = json.loads(next((repo / 'specs/001-login/token-usage').glob('*.json')).read_text())
    assert 'unpriced-child-model' in data['unpriced_models']


@pytest.mark.parametrize('original', [
    '{"hook":"stop","generation_id":"g"}\n',
    '{"hook":"beforeSubmitPrompt","prompt":"/speckit.plan","label":"/speckit.plan","model":"gpt-5"}\n',
])
def test_preview_cleanup_preserves_unchanged_ledger_mtime(tmp_path, original):
    ledger = tmp_path / 'clean.jsonl'
    ledger.write_text(original)
    os.utime(ledger, ns=(1_000_000_000, 1_000_000_000))
    before = ledger.stat().st_mtime_ns
    remove_previews(tmp_path)
    assert ledger.stat().st_mtime_ns == before
    assert ledger.read_text() == original


def test_partial_run_retains_individually_known_buckets():
    row = Request('r', None, 'gpt-5.2-codex', 10, 20, 5, None, None, 0, measurement='partial')
    run = Run('s', 'core', 'plan', 'plan', None, None, requests=[row], runtime='codex', measurement='partial')
    summary = run_summary(run, Rates({}, 'test', 'hash'))
    assert summary['usage']['input'] == 10
    assert summary['usage']['output'] == 20
    assert summary['usage']['cache_read'] == 5
    assert summary['usage']['cache_write_5m'] is None
    assert summary['tokens'] is None
    assert summary['cost_usd'] is None


@pytest.mark.parametrize('coverage_reason', ['missing-usage', 'counter-reset', 'conflicting-session-copies'])
def test_partial_bucket_evidence_does_not_complete_missing_observations(coverage_reason):
    row = Request('r', None, 'gpt-5.2-codex', 10, 20, 5, None, None, 0, measurement='partial',
                  reasons=['cache-write-duration-unknown'])
    run = Run('s', 'core', 'plan', 'plan', None, None, requests=[row], runtime='codex',
              measurement='partial', reasons=['cache-write-duration-unknown', coverage_reason])
    summary = run_summary(run, Rates({}, 'test', 'hash'))
    assert summary['usage']['input'] is None
    assert summary['usage']['output'] is None
    assert summary['measured_usage']['input'] == 10
    assert summary['measured_usage']['output'] == 20
    assert summary['tokens'] is None
    assert summary['cost_usd'] is None


def test_mixed_markdown_explains_unpriced_models():
    session = {'session_id':'s', 'runtime':'codex', 'measurement':'exact', 'runs':[]}
    source = author_file('001-login', 'specs/001-login', 'a', 'm', {}, [session], 'complete', [],
                         ['unpriced-model-witness'])
    text = render_feature_md([source])
    assert 'Unpriced models' in text
    assert 'unpriced-model-witness' in text
