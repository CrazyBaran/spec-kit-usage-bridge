import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def wf(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text(encoding='utf-8'))


def test_ci_matrix_and_jobs():
    ci = wf('ci.yml')
    jobs = ci['jobs']
    assert ci['permissions'] == {'contents': 'read'} and 'workflow_call' in ci[True]
    assert jobs['test']['strategy']['matrix'] == {
        'os': ['ubuntu-latest', 'windows-latest'], 'python': ['3.9', '3.x']}
    assert jobs['integration']['strategy']['matrix']['os'] == ['ubuntu-latest', 'windows-latest']
    steps = json.dumps(jobs)
    assert all(text in steps for text in ('ruff check', '-m contract', 'UB_REQUIRE_INTEGRATION', 'setup-uv'))


def test_tag_push_cannot_publish():
    release = wf('release.yml')
    triggers = release.get('on', release.get(True))
    assert 'workflow_dispatch' in triggers
    assert 'push' not in triggers


def test_setup_uv_uses_existing_release_tag():
    uses = [step['uses'] for step in wf('ci.yml')['jobs']['integration']['steps'] if 'uses' in step]
    assert 'astral-sh/setup-uv@v10.2.0' in uses
