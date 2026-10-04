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
    for name in ('release.yml', 'promote-release.yml'):
        wrapper = wf(name)
        pipeline = wrapper['jobs']['pipeline']
        assert pipeline['uses'] == './.github/workflows/release-pipeline.yml'
        assert "github.ref == 'refs/heads/main'" in pipeline['if']
        assert "github.repository == 'CrazyBaran/spec-kit-usage-bridge'" in pipeline['if']
        assert pipeline['with']['source_sha'] == '${{ inputs.source_sha }}'
        assert wrapper['concurrency'] == {'group': 'usage-bridge-release', 'cancel-in-progress': False}
    assert promote['jobs']['pipeline']['with']['candidate_tag'] == '${{ inputs.candidate_tag }}'
    assert wf('release-pipeline.yml')['jobs']['publish']['environment'] == 'release-publish'
    assert 'gh release create' not in json.dumps(wf('release.yml'))


def test_release_install_matrix_precedes_publication():
    release = wf('release-pipeline.yml')
    jobs = release['jobs']
    install = jobs['install']
    assert install['timeout-minutes'] == 45
    assert install['strategy']['matrix']['os'] == ['ubuntu-latest', 'windows-latest']
    assert install['strategy']['matrix']['host'] == ['minimum', 'current']
    assert '3.12' in json.dumps(install)
    assert jobs['evaluate']['if'].startswith('always()')
    assert jobs['ci']['with']['source_sha'] == '${{ inputs.source_sha }}'
    assert install['needs'] == 'build'
    assert set(jobs['evaluate']['needs']) == {'build', 'ci', 'install', 'override'}
    assert set(jobs['publish']['needs']) == {'context', 'evaluate'}
    assert jobs['override']['if'].startswith('always()')
    assert "needs.install.result == 'success'" in jobs['override']['if']
    assert "needs.install.result == 'success'" in jobs['evaluate']['if']
    assert jobs['override']['environment'] == 'release-override'
    assert 'approved' not in json.dumps(release.get('on', release.get(True)))
    text = json.dumps(release)
    assert 'gh release create' not in text
    assert 'release_cli.py publish' in text
    assert wf('ci.yml')['jobs']['test']['timeout-minutes'] == 30
    assert wf('ci.yml')['jobs']['lint']['timeout-minutes'] == 20


def test_release_host_refs_match_collected_evidence():
    expected = {'minimum': 'v1.0.12', 'current': 'v1.1.0'}
    expression = "${{ matrix.host == 'minimum' && 'v1.0.12' || 'v1.1.0' }}"
    for name, job_name in (('release-pipeline.yml', 'install'), ('verify-release.yml', 'verify-install')):
        job = wf(name)['jobs'][job_name]
        assert job['strategy']['matrix'] == {
            'os': ['ubuntu-latest', 'windows-latest'], 'host': ['minimum', 'current']}
        step = next(step for step in job['steps'] if 'UB_SPEC_KIT_REF' in step.get('env', {}))
        assert step['env']['UB_SPEC_KIT_REF'] == expression
    from release.policy import HOST_REFS

    assert HOST_REFS == expected
    assert wf('ci.yml')['jobs']['integration']['env']['UB_SPEC_KIT_REF'] == expected['current']


def test_ci_uses_nonempty_release_sha_without_assuming_a_workflow_call_event():
    for job in wf('ci.yml')['jobs'].values():
        checkout = next(step for step in job['steps'] if 'actions/checkout@' in step.get('uses', ''))
        assert checkout['with']['ref'] == '${{ inputs.source_sha || github.sha }}'


def test_release_assets_are_produced_transferred_and_runtime_tested():
    jobs = wf('release-pipeline.yml')['jobs']
    build_text = json.dumps(jobs['build'])
    assert 'release_cli.py bundle' in build_text
    assert 'actions/attest@' in build_text
    assert 'release-source/v1' in build_text
    assert 'actions/upload-artifact@' in build_text
    for name in ('install', 'evaluate', 'publish'):
        text = json.dumps(jobs[name])
        assert 'actions/download-artifact@' in text
        assert 'release-assets' in text
    install_text = json.dumps(jobs['install'])
    assert 'UB_RELEASE_ARCHIVE' in install_text
    assert 'UB_REQUIRE_INTEGRATION' in install_text
    assert 'setup-uv@' in install_text
    assert 'RELEASE_APP_PRIVATE_KEY' not in install_text
    assert 'SPEC_KIT_SUBMISSION_TOKEN' not in install_text
    assert 'release_cli.py collect' in json.dumps(jobs['evaluate'])
    assert '--prerelease' in json.dumps(jobs['publish'])


def test_authority_code_and_dependencies_come_from_protected_main():
    authority = [wf('prepare-release.yml')['jobs']['prepare'],
                 wf('release-pipeline.yml')['jobs']['publish']]
    follow = wf('release-follow-through.yml')['jobs']
    authority.extend(follow[name] for name in ('mergeback', 'submit'))
    for job in authority:
        checkouts = [step for step in job['steps'] if 'actions/checkout@' in step.get('uses', '')]
        assert checkouts and all(step['with']['ref'] == 'refs/heads/main' for step in checkouts)
        assert all(step['with']['persist-credentials'] is False for step in checkouts)
    for job in authority[:3]:
        assert 'actions/create-github-app-token@' in json.dumps(job)


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
    assert document['jobs']['verify']['uses'] == './.github/workflows/verify-release.yml'
    assert document['jobs']['detect']['needs'] == 'verify'
    assert 'release_cli.py check-verification' in json.dumps(document['jobs']['detect'])
    submit = document['jobs']['submit']['if']
    assert "inputs.real_project != ''" in submit
    assert 'documentation_review' in submit
    assert 'security_review' in submit
    assert document['jobs']['submit']['concurrency']['cancel-in-progress'] is False
    steps = document['jobs']['submit']['steps']
    token_step = next(step for step in steps if 'release_cli.py submit ' in step.get('run', ''))
    assert token_step['env']['GH_TOKEN'] == '${{ secrets.SPEC_KIT_SUBMISSION_TOKEN }}'
    assert 'submission-evidence' in text


def test_publication_explicitly_invokes_verification_and_stable_follow_through():
    jobs = wf('release-pipeline.yml')['jobs']
    assert jobs['verify']['uses'] == './.github/workflows/verify-release.yml'
    assert 'publish' in jobs['verify']['needs']
    assert jobs['follow-through']['uses'] == './.github/workflows/release-follow-through.yml'
    assert 'verify' in jobs['follow-through']['needs']
    assert jobs['follow-through']['if'] == "inputs.candidate_tag != ''"
    assert jobs['follow-through']['with']['digest'] == '${{ needs.verify.outputs.digest }}'
    verify = wf('verify-release.yml')['jobs']
    assert 'release_cli.py verify ' in json.dumps(verify['download'])
    assert 'verify-tag.txt' not in json.dumps(verify)
    assert '--archive ' not in json.dumps(verify)
    assert set(verify['complete']['needs']) == {'download', 'verify-install'}
    assert 'complete-verification' in json.dumps(verify['complete'])
    assert 'UB_RELEASE_ARCHIVE' in json.dumps(verify['verify-install'])


def test_workflow_linters_are_pinned():
    text = (Path(__file__).resolve().parents[1] / '.github/workflows/workflow-checks.yml').read_text(encoding='utf-8')
    assert 'curl | bash' not in text
    assert 'curl | sh' not in text
    assert '8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8' in text
    assert 'cc914d7f3750a2d13d75c7f184a1060aa0e9d482' in text
    assert 'v1.30.1' in text
    assert 'min-severity: high' in text
