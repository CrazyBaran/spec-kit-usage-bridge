"""Isolated install of a built archive. Skips without uvx unless UB_REQUIRE_INTEGRATION=1."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from builders import SessionBuilder, stop_payload
from release_fixtures import build_release_archive, install_archive_project

pytestmark = pytest.mark.integration


@pytest.fixture
def release_archive(tmp_path):
    return build_release_archive(tmp_path)


def test_archive_contains_exact_installed_surface(tmp_path, release_archive):
    project = install_archive_project(tmp_path, release_archive, 'v1.0.12')
    installed = project / '.specify/extensions/usage-bridge'
    assert (installed / 'scripts/python/checkpoint.py').is_file()
    assert (installed / 'scripts/python/usage_bridge/data/openai-pricing.json').is_file()
    assert not (installed / 'tests').exists()
    assert not (installed / 'docs').exists()
    assert not (installed / 'README.md').exists()


def test_installed_runtime_without_repo_pythonpath(tmp_path, release_archive):
    project = install_archive_project(tmp_path, release_archive, os.environ.get('UB_SPEC_KIT_REF', 'v1.0.12'))
    feature = project / 'specs/001-login'
    feature.mkdir(parents=True)
    (project / '.specify/feature.json').write_text(
        '{"feature_directory": "specs/001-login"}', encoding='utf-8')
    session = SessionBuilder('s1', cwd=project)
    session.command('/speckit-specify')
    session.reply('r1', output=10)
    transcript = session.write()
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    env['PYTHONPATH'] = ''
    env['PYTHONIOENCODING'] = 'utf-8'
    root = str(Path(__file__).resolve().parents[2])
    installed = project / '.specify/extensions/usage-bridge/scripts/python'
    for name in ('checkpoint.py', 'capture.py', 'report.py', 'check.py'):
        script = installed / name
        assert script.is_file()
        assert root not in str(script)
    capture = subprocess.run(
        [sys.executable, str(project / '.specify/events.py'), 'speckit.usage-bridge.capture', 'stop', '30'],
        cwd=project, input=stop_payload('s1', transcript, project), capture_output=True, text=True,
        encoding='utf-8', timeout=60, env=env,
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    report = feature / 'token-usage.md'
    assert report.is_file()
    assert 'specify' in report.read_text(encoding='utf-8').lower()
    checkpoint = subprocess.run(
        [sys.executable, str(installed / 'checkpoint.py'), '--runtime', 'claude', '--session-id', 's1',
         '--feature', 'specs/001-login', '--phase', 'specify', '--latest', '--apply'],
        cwd=project, capture_output=True, text=True, encoding='utf-8', timeout=60, env=env,
    )
    assert checkpoint.returncode == 0, checkpoint.stdout + checkpoint.stderr
    assert 'binding' in checkpoint.stdout
    rendered = subprocess.run(
        [sys.executable, str(installed / 'report.py')], cwd=project, capture_output=True, text=True,
        encoding='utf-8', timeout=60, env=env,
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    check = subprocess.run(
        [sys.executable, str(installed / 'check.py')], cwd=project, capture_output=True, text=True,
        encoding='utf-8', timeout=30, env=env,
    )
    assert check.returncode == 0, check.stdout + check.stderr


def test_upgrade_preserves_config_and_reports(tmp_path, release_archive):
    project = install_archive_project(tmp_path, release_archive, os.environ.get('UB_SPEC_KIT_REF', 'v1.0.12'))
    feature = project / 'specs/001-login'
    feature.mkdir(parents=True)
    report = feature / 'token-usage.md'
    report.write_text('kept history\n', encoding='utf-8')
    local = project / '.specify/extensions/usage-bridge/usage-bridge-config.local.yml'
    local.write_text('author:\n  alias: kept-author\n', encoding='utf-8')
    install_archive_project(tmp_path, release_archive, os.environ.get('UB_SPEC_KIT_REF', 'v1.0.12'),
                            project=project, force=True)
    assert report.read_text(encoding='utf-8') == 'kept history\n'
    assert 'kept-author' in local.read_text(encoding='utf-8')


@pytest.mark.parametrize('integration', ['claude', 'codex', 'cursor-agent'])
def test_archive_install_renders_commands(tmp_path, release_archive, integration):
    project = install_archive_project(tmp_path, release_archive, os.environ.get('UB_SPEC_KIT_REF', 'v1.0.12'),
                                      integration=integration)
    folder = {'claude': '.claude', 'codex': '.agents', 'cursor-agent': '.cursor'}[integration]
    skill = project / folder / 'skills/speckit-usage-bridge-report/SKILL.md'
    assert skill.is_file()
    rendered = skill.read_text(encoding='utf-8')
    assert 'speckit-usage-bridge-report' in rendered
    assert 'Token usage audit per feature / phase / session' in rendered
