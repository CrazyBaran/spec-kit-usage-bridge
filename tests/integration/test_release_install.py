"""Isolated install of a built archive. Skips without uvx unless UB_REQUIRE_INTEGRATION=1."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from builders import SessionBuilder, stop_payload
from release_fixtures import (
    _require_uvx,
    _run,
    _serve,
    build_release_archive,
    host_ref,
    install_archive_project,
    specify_command,
)

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
    project = install_archive_project(tmp_path, release_archive, host_ref())
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


def test_forced_reinstall_preserves_config_and_reports(tmp_path, release_archive):
    project = install_archive_project(tmp_path, release_archive, host_ref())
    feature = project / 'specs/001-login'
    feature.mkdir(parents=True)
    report = feature / 'token-usage.md'
    report.write_text('kept history\n', encoding='utf-8')
    local = project / '.specify/extensions/usage-bridge/usage-bridge-config.local.yml'
    local.write_text('author:\n  alias: kept-author\n', encoding='utf-8')
    install_archive_project(tmp_path, release_archive, host_ref(),
                            project=project, force=True)
    assert report.read_text(encoding='utf-8') == 'kept history\n'
    assert 'kept-author' in local.read_text(encoding='utf-8')


def _archive_with_manifest(archive: Path, output: Path, manifest: dict) -> Path:
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(output, 'w') as target:
        for member in source.infolist():
            data = (yaml.safe_dump(manifest).encode('utf-8')
                    if member.filename == 'usage-bridge/extension.yml' else source.read(member))
            target.writestr(member, data)
    return output


def test_native_install_rejects_unsupported_manifest_schema(tmp_path, release_archive):
    _require_uvx()
    with zipfile.ZipFile(release_archive) as archive:
        manifest = yaml.safe_load(archive.read('usage-bridge/extension.yml'))
    manifest['schema_version'] = 'unsupported-test-schema'
    invalid = _archive_with_manifest(release_archive, tmp_path / 'invalid.zip', manifest)
    project = tmp_path / 'invalid-project'
    command = specify_command(host_ref())
    _run(command + ['init', str(project), '--integration', 'claude',
                    '--ignore-agent-tools', '--non-interactive'])
    with _serve(invalid.parent) as base:
        result = subprocess.run(
            command + ['extension', 'add', 'usage-bridge', '--from', f'{base}/{invalid.name}'],
            cwd=project, input='y\n', capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=240, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    assert result.returncode != 0, result.stdout + result.stderr
    assert 'Unsupported schema version' in result.stdout + result.stderr
    assert not (project / '.specify/extensions/usage-bridge/extension.yml').exists()
    listed = _run(command + ['extension', 'list', '--json'], cwd=project)
    assert not any(item['id'] == 'usage-bridge' for item in json.loads(listed.stdout))


def test_native_update_preserves_config_and_reports(tmp_path, release_archive):
    target_digest = hashlib.sha256(release_archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(release_archive) as archive:
        target_manifest_bytes = archive.read('usage-bridge/extension.yml')
    manifest = yaml.safe_load(target_manifest_bytes)
    version = manifest['extension']['version']
    assert tuple(map(int, version.split('.'))) > (0, 0, 0)
    older_manifest = {**manifest, 'extension': {**manifest['extension'], 'version': '0.0.0'}}
    older = _archive_with_manifest(release_archive, tmp_path / 'older.zip', older_manifest)
    project = install_archive_project(tmp_path, older, host_ref())
    installed = project / '.specify/extensions/usage-bridge'
    assert yaml.safe_load((installed / 'extension.yml').read_text(encoding='utf-8'))['extension']['version'] == '0.0.0'
    report = project / 'specs/001-login/token-usage.md'
    report.parent.mkdir(parents=True)
    report.write_text('kept history\n', encoding='utf-8')
    local = installed / 'usage-bridge-config.local.yml'
    local.write_text('author:\n  alias: kept-author\n', encoding='utf-8')
    serving = tmp_path / 'update-server'
    serving.mkdir()
    target = serving / release_archive.name
    shutil.copyfile(release_archive, target)
    with _serve(serving) as base:
        catalog_url = f'{base}/catalog.json'
        entry = {**manifest['extension'], 'download_url': f'{base}/{target.name}',
                 'sha256': target_digest, 'requires': manifest['requires'],
                 'provides': {'commands': len(manifest['provides']['commands']),
                              'hooks': len(manifest['hooks'])}, 'tags': manifest['tags']}
        (serving / 'catalog.json').write_text(json.dumps({
            'schema_version': '1.0', 'catalog_url': catalog_url,
            'extensions': {'usage-bridge': entry}}), encoding='utf-8')
        _run(specify_command(host_ref()) + ['extension', 'update', 'usage-bridge'],
             cwd=project, input='y\n', env={'SPECKIT_CATALOG_URL': catalog_url})
    assert (installed / 'extension.yml').read_bytes() == target_manifest_bytes
    assert yaml.safe_load((installed / 'extension.yml').read_text(encoding='utf-8'))['extension']['version'] == version
    assert report.read_text(encoding='utf-8') == 'kept history\n'
    assert 'kept-author' in local.read_text(encoding='utf-8')
    assert hashlib.sha256(release_archive.read_bytes()).hexdigest() == target_digest


@pytest.mark.parametrize('integration', ['claude', 'codex', 'cursor-agent'])
def test_archive_install_renders_commands(tmp_path, release_archive, integration):
    project = install_archive_project(tmp_path, release_archive, host_ref(),
                                      integration=integration)
    folder = {'claude': '.claude', 'codex': '.agents', 'cursor-agent': '.cursor'}[integration]
    skill = project / folder / 'skills/speckit-usage-bridge-report/SKILL.md'
    assert skill.is_file()
    rendered = skill.read_text(encoding='utf-8')
    assert 'speckit-usage-bridge-report' in rendered
    assert 'Token usage audit per feature / phase / session' in rendered
