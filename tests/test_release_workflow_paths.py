import json

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
