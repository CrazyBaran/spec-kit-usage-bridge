import io
import json
import os
from pathlib import Path

import pytest

from builders import SessionBuilder, make_repo
from codex_builders import prompt, tokens, turn, write_rollout
from usage_bridge.bindings import load_bindings
from usage_bridge.paths import runtime_dir


def setup_sources(tmp_path, runtime):
    repo = make_repo(tmp_path, features=('001-login', 'B', 'C'), branch='001-login')
    (repo / '.specify/extensions').mkdir()
    (repo / '.specify/extensions/.registry').write_text('{"extensions":{"superspec":{}}}')
    phases = ['specify', 'clarify', 'superspec.brainstorm', 'clarify']
    if runtime == 'claude':
        builder = SessionBuilder('s', repo, branch='001-login')
        for i, phase in enumerate(phases):
            builder.command('/speckit.' + phase)
            builder.reply('r' + str(i), output=10, skill='superpowers:brainstorming' if i == 1 else None)
        builder.write()
    elif runtime == 'codex':
        events = [turn()]
        for i, phase in enumerate(phases):
            event = prompt('/speckit.' + phase)
            event['timestamp'] = f'2026-10-01T08:0{i}:02Z'
            events += [event, tokens(100 * (i + 1), 0, 10 * (i + 1), stamp=f'2026-10-01T08:0{i}:03Z')]
        write_rollout(Path(os.environ['CODEX_HOME']), repo, events=events)
    else:
        import time

        from usage_bridge.adapters.base import ParseContext
        from usage_bridge.adapters.cursor_ledger import append_event
        ctx = ParseContext((repo,), dict(os.environ), runtime_dir(repo, repo), False, time.monotonic() + 15,
                           time.monotonic)
        for i, phase in enumerate(phases):
            base = {'conversation_id': 's', 'generation_id': str(i), 'workspace_roots': [str(repo)]}
            append_event({**base, 'hook_event_name': 'beforeSubmitPrompt', 'prompt': '/speckit.' + phase}, ctx)
            append_event({**base, 'hook_event_name': 'stop', 'model': 'claude-sonnet-4-6',
                          'input_tokens': 100, 'output_tokens': 10}, ctx)
    return repo


def invoke(repo, runtime='codex', phase='clarify', extra=(), feature='specs/B', env=None):
    from usage_bridge.checkpoint import checkpoint_main
    out = io.StringIO()
    args = ['--runtime', runtime, '--session-id', 's', '--feature', feature, '--phase', phase, *extra]
    code = checkpoint_main(args, out, env or dict(os.environ), repo)
    return code, out.getvalue()


@pytest.mark.parametrize('runtime', ['claude', 'codex', 'cursor'])
def test_preview_apply_and_feature_switch_are_invocation_scoped(tmp_path, runtime):
    repo = setup_sources(tmp_path, runtime)
    state = runtime_dir(repo, repo)
    assert invoke(repo, runtime)[0] == 1  # repeated clarify is ambiguous
    assert invoke(repo, runtime, extra=['--latest'])[0] == 0
    assert load_bindings(state, repo) == []
    assert not list(repo.glob('specs/*/token-usage.md'))
    assert invoke(repo, runtime, extra=['--latest', '--apply'])[0] == 0
    first = (state / 'feature-bindings.json').read_bytes()
    before = {str(p): p.read_bytes() for p in repo.glob('specs/*/token-usage/*')}
    assert invoke(repo, runtime, extra=['--latest', '--apply'])[0] == 0
    assert (state / 'feature-bindings.json').read_bytes() == first
    assert {str(p): p.read_bytes() for p in repo.glob('specs/*/token-usage/*')} == before
    assert invoke(repo, runtime, phase='superspec.brainstorm', feature='specs/C', extra=['--apply'])[0] == 0
    rows = load_bindings(state, repo)
    assert sorted((b.phase, b.feature_dir) for b in rows) == [
        ('clarify', 'specs/B'), ('superspec.brainstorm', 'specs/C')]
    assert (repo / 'specs/B/token-usage.md').exists()
    assert (repo / 'specs/C/token-usage.md').exists()
    assert (repo / 'specs/001-login/token-usage.md').exists()  # specify and unbound clarify retained
    assert invoke(repo, runtime, phase='superpowers.brainstorming', extra=['--apply'])[0] == 1


def test_missing_identity_warns_only_in_workflow_mode(tmp_path):
    from usage_bridge.checkpoint import checkpoint_main
    repo = make_repo(tmp_path)
    args = ['--feature', 'specs/001-login', '--phase', 'specify', '--apply']
    env = {k: v for k, v in os.environ.items() if k != 'CODEX_THREAD_ID'}
    for extra, expected in [((), 1), (('--workflow',), 0)]:
        out = io.StringIO()
        assert checkpoint_main([*args, *extra], out, env, repo) == expected
        assert 'identity' in out.getvalue()
    assert load_bindings(runtime_dir(repo, repo), repo) == []


def test_explicit_identity_and_feature_override_shared_state(tmp_path):
    repo = setup_sources(tmp_path, 'codex')
    (repo / '.specify/feature.json').write_text('{"feature_directory":"specs/C"}')
    env = dict(os.environ, CODEX_THREAD_ID='wrong-session')
    assert invoke(repo, extra=['--latest', '--apply'], env=env)[0] == 0
    assert load_bindings(runtime_dir(repo, repo), repo)[0].feature_dir == 'specs/B'


@pytest.mark.parametrize('feature', ['../outside', 'specs/missing'])
def test_invalid_feature_preserves_state(tmp_path, feature):
    repo = setup_sources(tmp_path, 'codex')
    assert invoke(repo, feature=feature, extra=['--latest', '--apply'])[0] == 1
    assert load_bindings(runtime_dir(repo, repo), repo) == []


def test_binding_survives_delayed_usage_and_failed_refresh(tmp_path, monkeypatch):
    import usage_bridge.checkpoint as checkpoint
    from usage_bridge.pipeline import CaptureResult, run_capture
    repo = setup_sources(tmp_path, 'codex')
    monkeypatch.setattr(checkpoint, 'run_capture', lambda *args: CaptureResult('manual', 'error', error='unavailable'))
    code, message = invoke(repo, extra=['--latest', '--apply'])
    assert code == 1 and 'saved' in message and 'refresh' in message
    assert len(load_bindings(runtime_dir(repo, repo), repo)) == 1
    home = Path(os.environ['CODEX_HOME'])
    path = next(home.rglob('rollout-s.jsonl'))
    with path.open('a') as stream:
        stream.write(json.dumps(tokens(500, 0, 50, stamp='2026-10-01T08:05:03Z')) + '\n')
    assert run_capture('', repo, dict(os.environ)).status == 'ok'
    assert (repo / 'specs/B/token-usage.md').exists()


def test_environment_identity_is_codex_only(tmp_path):
    from usage_bridge.checkpoint import checkpoint_main
    repo = setup_sources(tmp_path, 'codex')
    env = dict(os.environ, CODEX_THREAD_ID='s')
    args = ['--feature', 'specs/B', '--phase', 'clarify', '--latest']
    assert checkpoint_main(args, io.StringIO(), env, repo) == 0
    for runtime in ['claude', 'cursor']:
        out = io.StringIO()
        assert checkpoint_main([*args, '--runtime', runtime], out, env, repo) == 1
        assert 'identity' in out.getvalue()


def test_selection_deadline_and_corrupt_state_preserve_history(tmp_path):
    repo = setup_sources(tmp_path, 'codex')
    env = dict(os.environ, SPECKIT_USAGE_BRIDGE_CAPTURE_DEADLINE_SECONDS='0.001')
    # Config's exact override name is tested below through the normal config file.
    config_dir = repo / '.specify/extensions/usage-bridge'
    config_dir.mkdir()
    (config_dir / 'usage-bridge-config.local.yml').write_text('capture:\n  deadline_seconds: 0.001\n')
    assert invoke(repo, extra=['--latest', '--apply'], env=env)[0] == 1
    state = runtime_dir(repo, repo)
    assert load_bindings(state, repo) == []
    (config_dir / 'usage-bridge-config.local.yml').write_text('')
    path = state / 'feature-bindings.json'
    path.write_text('{broken')
    assert invoke(repo, extra=['--latest', '--apply'])[0] == 1
    assert path.read_text() == '{broken'


def test_unknown_or_disabled_session_cannot_bind(tmp_path):
    from usage_bridge.checkpoint import checkpoint_main
    repo = setup_sources(tmp_path, 'codex')
    args = ['--runtime', 'codex', '--session-id', 'unknown', '--feature', 'specs/B', '--phase', 'clarify', '--apply']
    assert checkpoint_main(args, io.StringIO(), dict(os.environ), repo) == 1
    env = dict(os.environ, SPECKIT_USAGE_BRIDGE_RUNTIMES_ENABLED='claude')
    code, output = invoke(repo, extra=['--latest', '--apply'], env=env)
    assert code == 1 and 'disabled' in output
    assert load_bindings(runtime_dir(repo, repo), repo) == []


def test_latest_claude_invocation_waits_for_its_reply(tmp_path):
    repo = make_repo(tmp_path, features=('001-login', 'B'))
    builder = SessionBuilder('s', repo, branch='001-login')
    builder.command('/speckit-clarify')
    builder.reply('earlier', output=10)
    builder.command('/speckit-clarify')
    builder.write()
    code, output = invoke(repo, runtime='claude', extra=['--latest', '--apply'])
    assert code == 0, output
    binding = load_bindings(runtime_dir(repo, repo), repo)[0]
    assert binding.invocation_ts == '2026-09-29T09:00:03.000Z'
    assert not (repo / 'specs/B/token-usage.md').exists()
    assert (repo / 'specs/001-login/token-usage.md').exists()
    builder.reply('delayed', output=20)
    builder.write()
    from usage_bridge.pipeline import run_capture
    assert run_capture('', repo, dict(os.environ)).status == 'ok'
    assert (repo / 'specs/B/token-usage.md').exists()


@pytest.mark.parametrize('selector', [['--latest'], ['--invocation-ts', '2026-10-01T08:00:02.000Z']])
@pytest.mark.parametrize('workflow', [False, True])
def test_conflicting_codex_copies_cannot_bind_shared_prefix(tmp_path, selector, workflow):
    from usage_bridge.pipeline import run_capture
    repo = make_repo(tmp_path, features=('001-login', 'B'))
    home = Path(os.environ['CODEX_HOME'])
    prefix = [turn(), prompt('/speckit.clarify'), tokens(100, 0, 10)]
    for archived, suffix in [(False, 'first'), (True, 'second')]:
        later = prompt('/speckit.clarify ' + suffix)
        later['timestamp'] = '2026-10-01T09:00:02Z'
        write_rollout(home, repo, events=[*prefix, later], archived=archived)
    # Existing reports must remain unchanged, as well as any private binding file.
    assert run_capture('', repo, dict(os.environ)).status in ('ok', 'partial')
    before = {str(path): path.read_bytes() for path in repo.glob('specs/**/token-usage*') if path.is_file()}
    before.update({str(path): path.read_bytes() for path in repo.glob('specs/*/token-usage/*.json')})
    extra = [*selector, '--apply', *(['--workflow'] if workflow else [])]
    code, output = invoke(repo, extra=extra)
    assert code == (0 if workflow else 1), output
    assert 'conflicting-session-copies' in output
    assert load_bindings(runtime_dir(repo, repo), repo) == []
    after = {str(path): path.read_bytes() for path in repo.glob('specs/**/token-usage*') if path.is_file()}
    after.update({str(path): path.read_bytes() for path in repo.glob('specs/*/token-usage/*.json')})
    assert after == before


def test_consistent_codex_copies_still_select_latest(tmp_path):
    repo = make_repo(tmp_path, features=('001-login', 'B'))
    home = Path(os.environ['CODEX_HOME'])
    prefix = [turn(), prompt('/speckit.clarify'), tokens(100, 0, 10)]
    write_rollout(home, repo, events=prefix, archived=True)
    later = prompt('/speckit.clarify')
    later['timestamp'] = '2026-10-01T09:00:02Z'
    write_rollout(home, repo, events=[*prefix, later])
    code, output = invoke(repo, extra=['--latest', '--apply'])
    assert code == 0, output
    assert load_bindings(runtime_dir(repo, repo), repo)[0].invocation_ts == '2026-10-01T09:00:02.000Z'
