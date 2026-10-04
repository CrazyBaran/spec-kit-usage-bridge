"""Install a built Usage Bridge archive into a Spec Kit project at an explicit host ref."""
from __future__ import annotations

import functools
import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIN_HOST = 'v1.0.12'
MOVING_REFS = {'main', 'master', 'HEAD'}


def host_ref() -> str:
    return os.environ.get('UB_SPEC_KIT_REF', MIN_HOST)


def specify_command(ref: str) -> list[str]:
    if ref in MOVING_REFS:
        raise AssertionError('host ref must be an explicit tag or SHA, not a moving branch')
    return ['uvx', '--from', f'git+https://github.com/github/spec-kit.git@{ref}', 'specify']


def _require_uvx() -> None:
    if shutil.which('uvx'):
        return
    if os.environ.get('UB_REQUIRE_INTEGRATION') == '1':
        pytest.fail('uvx is required for integration tests')
    pytest.skip('uvx is unavailable')


def _run(cmd: list[str], cwd: Path | None = None, **kwargs) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=240, env=dict(os.environ, PYTHONIOENCODING='utf-8'), **kwargs,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@contextmanager
def _serve(directory: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def build_release_archive(tmp_path: Path) -> Path:
    spec = importlib.util.spec_from_file_location('build_release_archive', ROOT / 'tools/build_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive, _catalog = module.build(ROOT, '0.2.1', tmp_path / 'dist', 'https://example.invalid')
    return archive


def install_archive_project(tmp_path: Path, archive: Path, host: str, *,
                            integration: str = 'claude', project: Path | None = None,
                            force: bool = False) -> Path:
    """Install ``archive`` into a Spec Kit project pinned to ``host``. Returns the project path."""
    _require_uvx()
    command = specify_command(host)
    project = project or (tmp_path / 'proj')
    if not (project / '.specify').exists():
        _run(command + ['init', str(project), '--integration', integration,
                        '--ignore-agent-tools', '--non-interactive'])
        if not (project / '.git').exists():
            _run(['git', 'init', '-b', 'main', str(project)])
    with _serve(archive.parent) as base:
        add = command + ['extension', 'add', 'usage-bridge', '--from', f'{base}/{archive.name}']
        if force:
            add.append('--force')
        _run(add, cwd=project, input='y\n')
    evidence = tmp_path / 'release-verification.json'
    evidence.write_text(json.dumps({'host_ref': host, 'archive': archive.name}, indent=2) + '\n', encoding='utf-8')
    return project
