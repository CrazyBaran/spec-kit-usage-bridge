"""Exercise installation and runtime dispatch using the pinned real Spec Kit CLI."""
import functools
import http.server
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from builders import SessionBuilder, stop_payload

ROOT = Path(__file__).resolve().parents[2]
SPECIFY = ['uvx', '--from', 'git+https://github.com/github/spec-kit.git@v1.0.12', 'specify']
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_uvx():
    if not shutil.which('uvx'):
        if os.environ.get('UB_REQUIRE_INTEGRATION') == '1':
            pytest.fail('uvx is required for integration tests')
        pytest.skip('uvx is unavailable')


def run(cmd, cwd=None, **kwargs):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=240, env=dict(os.environ, PYTHONIOENCODING='utf-8'), **kwargs)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def init(tmp_path, *extra):
    proj = tmp_path / 'proj'
    run(SPECIFY + ['init', str(proj), '--integration', 'claude', '--ignore-agent-tools', '--non-interactive', *extra])
    if not (proj / '.git').exists():
        run(['git', 'init', '-b', 'main', str(proj)])
    return proj


def install(proj):
    run(SPECIFY + ['extension', 'add', str(ROOT), '--dev'], cwd=proj)


def stop_commands(proj):
    path = proj / '.claude/settings.json'
    settings = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return [h['command'] for e in settings.get('hooks', {}).get('Stop', []) for h in e['hooks']]


def check(proj):
    return subprocess.run([sys.executable, str(proj / '.specify/extensions/usage-bridge/scripts/python/check.py')],
                          cwd=proj, capture_output=True, text=True, encoding='utf-8', timeout=30)


def test_add_info_capture_remove(tmp_path):
    proj = init(tmp_path)
    install(proj)
    assert not (proj / '.specify/extensions/usage-bridge/.git').exists()
    assert any('.specify/events.py' in c and 'speckit.usage-bridge.capture' in c for c in stop_commands(proj))
    info = run(SPECIFY + ['extension', 'info', 'usage-bridge'], cwd=proj).stdout
    assert 'speckit.usage-bridge.report' in info
    manifest = yaml.safe_load((proj / '.specify/extensions/usage-bridge/extension.yml').read_text(encoding='utf-8'))
    assert manifest['events']['stop'] == {'command': 'speckit.usage-bridge.capture', 'timeout': 30}
    (proj / 'specs/001-login').mkdir(parents=True)
    (proj / '.specify/feature.json').write_text('{"feature_directory": "specs/001-login"}', encoding='utf-8')
    b = SessionBuilder('s1', cwd=proj)
    b.command('/speckit-specify')
    b.reply('r1', output=10)
    main = b.write()
    p = run([sys.executable, str(proj / '.specify/events.py'), 'speckit.usage-bridge.capture', 'stop', '30'],
            cwd=proj, input=stop_payload('s1', main, proj))
    assert p.stdout == '' and p.stderr == ''
    assert (proj / 'specs/001-login/token-usage.md').exists()
    run(SPECIFY + ['extension', 'remove', 'usage-bridge', '--force'], cwd=proj)
    assert not any('usage-bridge' in c for c in stop_commands(proj))
    assert not (proj / '.claude/skills/speckit-usage-bridge-report').exists()


def test_check_flags_disabled_events_and_remediation_restores(tmp_path):
    proj = init(tmp_path, '--integration-options=--events false')
    install(proj)
    p = check(proj)
    assert p.returncode == 1 and 'FAIL stop-hook:' in p.stdout, p.stdout + p.stderr
    remedy = p.stdout.split('Run: ', 1)[1].splitlines()[0]
    run(SPECIFY[:-1] + shlex.split(remedy), cwd=proj)
    p = check(proj)
    assert p.returncode == 0, p.stdout + p.stderr


def test_check_flags_missing_claude_integration(tmp_path):
    proj = init(tmp_path)
    install(proj)
    run(SPECIFY + ['integration', 'uninstall', 'claude'], cwd=proj)
    p = check(proj)
    assert p.returncode == 1 and 'FAIL integration:' in p.stdout, p.stdout + p.stderr


@contextmanager
def serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_install_from_release_zip(tmp_path):
    spec = importlib.util.spec_from_file_location('build_release', ROOT / 'tools/build_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive, _ = module.build(ROOT, '0.1.0', tmp_path / 'dist', 'https://example.invalid')
    with serve(archive.parent) as base:
        proj = init(tmp_path)
        run(SPECIFY + ['extension', 'add', 'usage-bridge', '--from', base + '/' + archive.name], cwd=proj, input='y\n')
    assert (proj / '.specify/extensions/usage-bridge/extension.yml').exists()
