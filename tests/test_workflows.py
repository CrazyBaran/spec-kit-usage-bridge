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


def test_release_builds_and_publishes():
    rel = wf('release.yml')
    assert rel[True]['push']['tags'] == ['v*'] and rel['jobs']['release']['needs'] == 'ci'
    assert rel['jobs']['release']['permissions'] == {'contents': 'write'}
    assert 'tools/build_release.py' in json.dumps(rel) and 'gh release create' in json.dumps(rel)
