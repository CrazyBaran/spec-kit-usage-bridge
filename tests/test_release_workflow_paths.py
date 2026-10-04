import json
from pathlib import Path

from test_workflows import wf


def test_prepare_and_promote_dispatch_from_main_contracts():
    prepare = wf('prepare-release.yml')
    promote = wf('promote-release.yml')
    verify = wf('verify-release.yml')
    for document in (prepare, promote, verify):
        triggers = document.get('on', document.get(True))
        assert 'workflow_dispatch' in triggers
        assert 'push' not in triggers
    ci = wf('ci.yml')
    call = ci.get('on', ci.get(True))['workflow_call']
    assert 'source_sha' in call['inputs']
    text = json.dumps(promote)
    assert 'source_sha' in text
    assert 'release-publish' in text
    assert 'gh release create' not in json.dumps(wf('release.yml'))


def test_release_install_matrix_precedes_publication():
    release = wf('release.yml')
    jobs = release['jobs']
    install = jobs['install']
    assert install['timeout-minutes'] == 45
    assert install['strategy']['matrix']['os'] == ['ubuntu-latest', 'windows-latest']
    assert install['strategy']['matrix']['host'] == ['minimum', 'current']
    assert '3.12' in json.dumps(install)
    assert jobs['evaluate']['if'].startswith('always()')
    assert jobs['publish']['needs'] == ['ci', 'install', 'evaluate']
    assert jobs['override']['environment'] == 'release-override'
    assert 'approved' not in json.dumps(release.get('on', release.get(True)))
    text = json.dumps(release)
    assert 'gh release create' not in text
    assert 'release_cli.py publish' in text
    assert wf('ci.yml')['jobs']['test']['timeout-minutes'] == 30
    assert wf('ci.yml')['jobs']['lint']['timeout-minutes'] == 20


def test_follow_through_does_not_execute_release_bytes():
    document = wf('release-follow-through.yml')
    triggers = document.get('on', document.get(True))
    assert 'workflow_call' in triggers
    assert 'workflow_dispatch' in triggers
    assert 'release' in triggers
    text = json.dumps(document)
    assert 'catalog-submit' in text
    assert 'unzip' not in text
    assert 'python ' not in text or 'release_cli.py' in text
    assert 'candidate-tag' in text
    submit = document['jobs']['submit']['if']
    assert "inputs.real_project != ''" in submit
    assert 'documentation_review' in submit
    assert 'security_review' in submit


def test_workflow_linters_are_pinned():
    text = (Path(__file__).resolve().parents[1] / '.github/workflows/workflow-checks.yml').read_text(encoding='utf-8')
    assert 'curl | bash' not in text
    assert 'curl | sh' not in text
    assert '8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8' in text
    assert 'cc914d7f3750a2d13d75c7f184a1060aa0e9d482' in text
    assert 'v1.30.1' in text
    assert 'min-severity: high' in text
