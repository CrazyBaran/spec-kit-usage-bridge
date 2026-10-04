"""Contracts at the workflow/CLI boundary, with actual archive bytes."""
import json
from pathlib import Path

import pytest
import yaml

from release_cli import main

ROOT = Path(__file__).resolve().parents[1]
REPO = 'CrazyBaran/spec-kit-usage-bridge'
SHA = 'a' * 40


def test_build_command_refuses_a_checkout_at_a_different_sha(tmp_path, capsys):
    code = main(['bundle', '--checkout', str(ROOT), '--source-sha', SHA,
                 '--version', '0.2.1', '--tag', 'v0.2.1-rc.1', '--run-id', '7',
                 '--attempt', '1', '--assets-dir', str(tmp_path / 'assets'),
                 '--output', str(tmp_path / 'bundle.json')])
    assert code == 2
    assert 'checkout SHA' in capsys.readouterr().err


def test_reusable_ci_uses_the_supplied_commit_without_event_filter():
    workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
    for job in workflow['jobs'].values():
        checkout = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@'))
        assert checkout['with']['ref'] == '${{ inputs.source_sha || github.sha }}'


def test_privileged_workflows_never_checkout_release_input_as_tools():
    for name in ('prepare-release.yml', 'release-follow-through.yml', 'release-pipeline.yml'):
        workflow = yaml.safe_load((ROOT / '.github/workflows' / name).read_text())
        for job in workflow['jobs'].values():
            if not job.get('environment'):
                continue
            for step in job.get('steps', []):
                if step.get('uses', '').startswith('actions/checkout@'):
                    assert step['with']['ref'] == 'refs/heads/main'


def test_collect_refuses_missing_install_jobs_before_any_publish(tmp_path, capsys):
    evidence = tmp_path / 'input.json'
    evidence.write_text(json.dumps({'repository': REPO, 'source_sha': SHA,
                                   'run_id': 7, 'attempt': 1, 'zip_sha256': 'b' * 64}))

    class API:
        def request(self, method, path, payload=None):
            assert method == 'GET'
            return {'id': 7, 'run_attempt': 1, 'event': 'workflow_dispatch', 'head_branch': 'main',
                    'path': '.github/workflows/release.yml', 'head_repository': {'full_name': REPO}}

        def pages(self, path):
            return []

    code = main(['collect', '--evidence', str(evidence), '--output', str(tmp_path / 'out.json')], api=API())
    assert code == 2
    assert 'install' in capsys.readouterr().err


@pytest.mark.parametrize('version', ['0.2.2', '1.0.0'])
def test_archive_fixture_reads_manifest_version(tmp_path, monkeypatch, version):
    import release_fixtures

    manifest = yaml.safe_load((ROOT / 'extension.yml').read_text(encoding='utf-8'))
    manifest['extension']['version'] = version
    (tmp_path / 'extension.yml').write_text(yaml.safe_dump(manifest))
    monkeypatch.setattr(release_fixtures, 'ROOT', tmp_path)
    # Keep the real builder, intercept only its filesystem boundary.
    import build_release
    from release import artifacts
    monkeypatch.setattr(artifacts, '_commit_stamp', lambda repo: (2026, 10, 4, 0, 0, 0))
    monkeypatch.setattr(build_release, 'runtime_members', lambda repo: ())
    monkeypatch.setattr(build_release, 'write_deterministic_archive',
                        lambda repo, members, archive: archive.write_bytes(b'archive'))
    monkeypatch.setattr(release_fixtures.importlib.util, 'spec_from_file_location',
                        lambda *args: type('Spec', (), {'loader': type('Loader', (), {
                            'exec_module': lambda self, module: None})()})())
    monkeypatch.setattr(release_fixtures.importlib.util, 'module_from_spec', lambda spec: build_release)
    archive = release_fixtures.build_release_archive(tmp_path)
    assert archive.name == f'usage-bridge-v{version}.zip'
