import base64
import json
from pathlib import Path

import pytest

from github_api import GitHubAPIError
from release.policy import ReleasePolicyError
from release.submission import (
    choose_submission_action,
    load_submission_policy,
    render_submission,
    submit_release,
)

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'usage-bridge-submission:CrazyBaran/spec-kit-usage-bridge:usage-bridge'


def owned_issue(**overrides):
    issue = {
        'number': 41,
        'state': 'open',
        'user': {'login': 'CrazyBaran'},
        'labels': [],
        'title': '[Extension]: Add usage-bridge',
        'body': f'<!-- {MARKER} -->\n### Version\n\n0.2.1\n',
        'linked_pull_request': None,
    }
    issue.update(overrides)
    return issue


def verified_release(**overrides):
    release = {
        'version': '0.2.2',
        'tag': 'v0.2.2',
        'repository': 'CrazyBaran/spec-kit-usage-bridge',
        'extension_id': 'usage-bridge',
        'author': 'CrazyBaran',
        'prerelease': False,
        'source_sha': 'a' * 40,
        'zip_sha256': 'ab' * 32,
        'download_url': 'https://github.com/CrazyBaran/spec-kit-usage-bridge/releases/download/v0.2.2/usage-bridge-v0.2.2.zip',
    }
    release.update(overrides)
    return release


def _manifest():
    return {
        'extension': {
            'id': 'usage-bridge',
            'name': 'Usage Bridge — token-usage for Spec Kit',
            'version': '0.2.2',
            'description': 'Bridges token-usage into Spec Kit.',
            'author': 'CrazyBaran',
            'license': 'MIT',
        },
        'requires': {'speckit_version': '>=1.0.12'},
        'provides': {'commands': [{}, {}, {}, {}]},
        'hooks': [{}, {}, {}],
        'tags': ['tokens', 'cost'],
    }


def _evidence(**overrides):
    release = verified_release()
    binding = {key: release[key] for key in ('repository', 'version', 'tag', 'source_sha', 'zip_sha256')}
    data = {
        'install_verified': True,
        'commands_verified': True,
        'readme_verified': True,
        'verification': dict(binding, build_sha=release['source_sha'], provenance=True,
                             install_verified=True, commands_verified=True, packaging_verified=True),
        'attestation_binding': dict(binding),
        'attestations': {
            'real_project': 'Installed on a private sample repo and captured one specify run.',
            'documentation_review': True,
            'security_review': 'No new credential or transcript storage.',
        },
        'policy_fingerprint': json.loads(
            (ROOT / '.github/upstream-submission-policy.json').read_text(encoding='utf-8'))['form_sha256'],
    }
    data.update(overrides)
    return data


class ReadyAPI:
    """Real REST response shapes for policy files, tag identity and release assets."""
    def __init__(self, delegate=None, changed_file=None):
        self.delegate = delegate
        self.changed_file = changed_file
        self.reads = []
        self.writes = []

    def pages(self, path):
        if path.endswith('/timeline'):
            return []
        return self.delegate.pages(path) if self.delegate else []

    def request(self, method, path, payload=None):
        if method == 'GET':
            self.reads.append(path)
            if path == '/repos/github/spec-kit/commits/main':
                return {'sha': 'b' * 40}
            if path.startswith('/repos/github/spec-kit/contents/'):
                relative = path.split('/contents/', 1)[1].split('?', 1)[0]
                names = {'.github/ISSUE_TEMPLATE/extension_submission.yml': 'extension_submission.yml',
                         '.github/workflows/add-community-extension.md': 'add-community-extension.md',
                         'extensions/EXTENSION-PUBLISHING-GUIDE.md': 'EXTENSION-PUBLISHING-GUIDE.md',
                         'CONTRIBUTING.md': 'CONTRIBUTING.md'}
                blob = (ROOT / 'tests/fixtures/release/upstream-policy' / names[relative]).read_bytes()
                if relative == self.changed_file:
                    blob += b'\nchanged policy\n'
                return {'type': 'file', 'encoding': 'base64',
                        'content': base64.b64encode(blob).decode('ascii'), 'size': len(blob)}
            if '/releases/tags/' in path:
                release = verified_release()
                return {'id': 5, 'tag_name': release['tag'], 'draft': False, 'prerelease': False,
                        'assets': [{'name': 'usage-bridge-v0.2.2.zip',
                                    'digest': 'sha256:' + release['zip_sha256']}]}
            if '/git/ref/tags/' in path:
                return {'object': {'type': 'commit', 'sha': 'a' * 40}}
        else:
            self.writes.append((method, path, payload))
        if self.delegate:
            return self.delegate.request(method, path, payload)
        if method == 'POST' and path.endswith('/issues'):
            return {'number': 9, 'html_url': 'https://example.test/issues/9'}
        raise AssertionError(method + ' ' + path)


def test_triaged_issue_is_not_rewritten():
    issue = owned_issue()
    issue['labels'] = [{'name': 'extension-submission'}]
    action = choose_submission_action((issue,), verified_release())
    assert action['action'] == 'create'
    assert action['supersedes'] == issue['number']


def test_same_version_triaged_retry_reuses_one_issue():
    issue = owned_issue(body=f'<!-- {MARKER} -->\n### Version\n\n0.2.2\n', labels=[{'name': 'extension-submission'}])
    action = choose_submission_action((issue,), verified_release())
    assert action['action'] == 'reuse'
    assert action['number'] == 41


def test_untriaged_newer_updates_and_older_is_a_noop():
    issue = owned_issue()
    assert choose_submission_action((issue,), verified_release())['action'] == 'update_untriaged'
    older = choose_submission_action((issue,), verified_release(version='0.2.0', tag='v0.2.0'))
    assert older['action'] == 'reuse'


def test_ambiguous_owned_issues_block():
    action = choose_submission_action((owned_issue(), owned_issue(number=42)), verified_release())
    assert action['action'] == 'block'


def test_closed_rejected_submission_blocks():
    issue = owned_issue(state='closed', labels=[{'name': 'extension-submission'}])
    assert choose_submission_action((issue,), verified_release())['action'] == 'block'


def test_render_uses_official_headings_and_literal_metadata():
    form = {'headings': json.loads(
        (ROOT / '.github/upstream-submission-policy.json').read_text(encoding='utf-8'))['required_headings']}
    release = verified_release(version='0.2.2; rm -rf /', tag='v0.2.2')
    body = render_submission(_manifest(), release, _evidence(), form)
    for heading in form['headings']:
        assert f'### {heading}' in body
    assert release['download_url'] in body
    assert release['zip_sha256'] in body
    assert '0.2.2; rm -rf /' in body
    assert '- [x] Extension installs successfully via download URL' in body
    assert '- [x] Documentation is complete and accurate' in body
    assert '- [x] No security vulnerabilities identified' in body
    assert '- [x] Tested on at least one real project' in body
    assert MARKER in body


def test_missing_attestation_does_not_create_an_issue():
    class API:
        def __init__(self):
            self.created_issues = []
            self.writes = []

        def pages(self, path):
            return []

        def request(self, method, path, payload=None):
            if method != 'GET':
                self.writes.append((method, path, payload))
            if method == 'POST' and path.endswith('/issues'):
                self.created_issues.append(payload)
            return {'number': 1, 'html_url': 'https://example.test/issues/1', 'labels': [], 'body': ''}

    api = API()
    evidence = _evidence()
    del evidence['attestations']['security_review']
    result = submit_release(ReadyAPI(api), verified_release(), evidence, manifest=_manifest())
    assert result['status'] == 'pending'
    assert api.created_issues == []
    assert api.writes == []
    assert '### Proposed Catalog Entry' in result['body']


def test_submit_does_not_label_or_write_catalog():
    class API:
        def __init__(self):
            self.created_issues = []
            self.paths = []

        def pages(self, path):
            self.paths.append(path)
            return []

        def request(self, method, path, payload=None):
            self.paths.append(path)
            if method == 'POST' and path.endswith('/issues'):
                self.created_issues.append(payload)
                return {'number': 9, 'html_url': 'https://example.test/issues/9', 'body': payload['body'],
                        'labels': payload.get('labels', []), 'state': 'open', 'user': {'login': 'CrazyBaran'}}
            if method == 'GET':
                return {'number': 9, 'labels': [], 'body': (payload or {}).get('body', ''), 'state': 'open'}
            raise AssertionError(method + ' ' + path)

    api = API()
    result = submit_release(ReadyAPI(api), verified_release(), _evidence(), manifest=_manifest())
    assert result['action'] == 'create'
    assert api.created_issues[0].get('labels', []) == []
    assert all('CrazyBaran/spec-kit' not in path for path in api.paths)
    assert all('/pulls' not in path for path in api.paths)


def test_triage_between_reads_blocks_the_update():
    class API:
        def __init__(self):
            self.writes = []

        def pages(self, path):
            return [owned_issue()]

        def request(self, method, path, payload=None):
            if method == 'GET':
                issue = owned_issue(labels=[{'name': 'extension-submission'}])
                return issue
            self.writes.append(method)
            raise AssertionError('should not write')

    result = submit_release(ReadyAPI(API()), verified_release(), _evidence(), manifest=_manifest())
    assert result['action'] == 'block'


def test_forbidden_status_blocks_without_a_write():
    class API:
        def pages(self, path):
            raise GitHubAPIError('forbidden', status=403)

        def request(self, method, path, payload=None):
            raise GitHubAPIError('forbidden', status=403)

    result = submit_release(ReadyAPI(API()), verified_release(), _evidence(), manifest=_manifest())
    assert result['action'] == 'block'
    assert result['status'] == 'forbidden'


def test_prerelease_is_not_submitted():
    release = verified_release(prerelease=True, tag='v0.2.2-rc.1')
    with pytest.raises(ReleasePolicyError):
        submit_release(object(), release, _evidence(), manifest=_manifest())


def test_superseding_pending_issue_is_reused_on_retry():
    previous = owned_issue(labels=[{'name': 'extension-submission'}])
    pending = owned_issue(number=42, body=f'<!-- {MARKER} -->\n### Version\n\n0.2.2\n\nSupersedes #41\n')
    action = choose_submission_action([previous, pending], verified_release())
    assert action == {'action': 'reuse', 'number': 42}


def test_newer_pending_supersession_is_updated_without_touching_triaged_issue():
    previous = owned_issue(labels=[{'name': 'extension-submission'}])
    pending = owned_issue(number=42, body=f'<!-- {MARKER} -->\n### Version\n\n0.2.2\n\nSupersedes #41\n')
    action = choose_submission_action([previous, pending], verified_release(version='0.2.3'))
    assert action['action'] == 'update_untriaged'
    assert action['number'] == 42
    assert action['supersedes'] == 41


def test_closed_accepted_submission_allows_a_new_update():
    accepted = owned_issue(state='closed', linked_pull_request={'number': 99, 'merged': True})
    action = choose_submission_action([accepted], verified_release())
    assert action == {'action': 'create', 'supersedes': 41}


def test_closed_accepted_same_version_is_reused():
    accepted = owned_issue(state='closed', linked_pull_request={'number': 99, 'merged': True},
                           body=f'<!-- {MARKER} -->\n### Version\n\n0.2.2\n')
    assert choose_submission_action([accepted], verified_release()) == {'action': 'reuse', 'number': 41}


def test_unlinked_pending_issues_remain_ambiguous():
    old = owned_issue(labels=['extension-submission'])
    other = owned_issue(number=42, body=f'<!-- {MARKER} -->\n### Version\n\n0.2.2\n')
    assert choose_submission_action([old, other], verified_release())['action'] == 'block'


@pytest.mark.parametrize('field', ['provenance', 'install_verified', 'commands_verified', 'packaging_verified'])
def test_incomplete_stable_verification_cannot_submit(field):
    evidence = _evidence()
    evidence['verification'][field] = False
    api = ReadyAPI()
    result = submit_release(api, verified_release(), evidence, manifest=_manifest())
    assert result['action'] == 'block'
    assert api.writes == []


@pytest.mark.parametrize('field', ['tag', 'source_sha', 'zip_sha256', 'version', 'repository'])
def test_attestations_are_bound_to_exact_verified_release(field):
    evidence = _evidence()
    evidence['attestation_binding'][field] = 'mismatched'
    api = ReadyAPI()
    assert submit_release(api, verified_release(), evidence, manifest=_manifest())['action'] == 'block'
    assert api.writes == []


def test_waived_quality_check_withholds_submission():
    evidence = _evidence()
    evidence['verification']['waived'] = ['lint']
    api = ReadyAPI()
    assert submit_release(api, verified_release(), evidence, manifest=_manifest())['action'] == 'block'
    assert api.writes == []


@pytest.mark.parametrize('path', list(load_submission_policy()['reviewed_fingerprints']))
def test_each_live_upstream_policy_file_is_checked(path):
    api = ReadyAPI(changed_file=path)
    result = submit_release(api, verified_release(), _evidence(), manifest=_manifest())
    assert result['status'] == 'policy_drift'
    assert api.writes == []
    assert path in str(result['blockers'])


def test_successful_submission_checks_all_evidenced_requirements():
    api = ReadyAPI()
    result = submit_release(api, verified_release(), _evidence(), manifest=_manifest())
    assert result['action'] == 'create'
    requirements = result['body'].split('### Submission Requirements', 1)[1].split('### Testing Details', 1)[0]
    assert '- [ ]' not in requirements
    assert requirements.count('- [x]') == 6
    assert len([path for path in api.reads if '/contents/' in path]) == 4


def test_readme_requirement_without_source_evidence_stays_pending():
    evidence = _evidence(readme_verified=False)
    api = ReadyAPI()
    result = submit_release(api, verified_release(), evidence, manifest=_manifest())
    assert result['action'] == 'block'
    assert '- [ ] README.md with installation and usage instructions' in result['body']
    assert api.writes == []


def test_closed_accepted_issue_is_resolved_from_real_timeline_and_pull_api():
    class API(ReadyAPI):
        def pages(self, path):
            if path.endswith('/timeline'):
                return [{'event': 'cross-referenced', 'source': {'issue': {
                    'pull_request': {'url': 'https://api.github.com/repos/github/spec-kit/pulls/99'}}}}]
            return [owned_issue(state='closed')]

        def request(self, method, path, payload=None):
            if path == '/repos/github/spec-kit/pulls/99':
                return {'number': 99, 'merged': True,
                        'html_url': 'https://github.com/github/spec-kit/pull/99',
                        'head': {'ref': 'add-usage-bridge-extension'},
                        'base': {'ref': 'main', 'repo': {'full_name': 'github/spec-kit'}}}
            return super().request(method, path, payload)

    result = submit_release(API(), verified_release(), _evidence(), manifest=_manifest())
    assert result['action'] == 'create'
    assert result['supersedes'] == 41
    assert 'https://github.com/github/spec-kit/pull/99' in result['body']


def test_untriaged_issue_with_generated_pull_is_frozen():
    class API(ReadyAPI):
        def pages(self, path):
            if path.endswith('/timeline'):
                return [{'event': 'cross-referenced', 'source': {'issue': {
                    'pull_request': {'url': 'https://api.github.com/repos/github/spec-kit/pulls/99'}}}}]
            return [owned_issue()]

        def request(self, method, path, payload=None):
            if path == '/repos/github/spec-kit/pulls/99':
                return {'number': 99, 'merged': False, 'html_url': 'https://github.com/github/spec-kit/pull/99',
                        'head': {'ref': 'add-usage-bridge-extension'},
                        'base': {'ref': 'main', 'repo': {'full_name': 'github/spec-kit'}}}
            if path == '/repos/github/spec-kit/issues/41':
                return owned_issue()
            return super().request(method, path, payload)

    api = API()
    result = submit_release(api, verified_release(), _evidence(), manifest=_manifest())
    assert result['action'] == 'create'
    assert all(method != 'PATCH' for method, _, _ in api.writes)


def test_issue_version_changed_between_reads_cannot_overwrite_newer_submission():
    class API(ReadyAPI):
        def pages(self, path):
            return [] if path.endswith('/timeline') else [owned_issue()]

        def request(self, method, path, payload=None):
            if path == '/repos/github/spec-kit/issues/41':
                return owned_issue(body=f'<!-- {MARKER} -->\n### Version\n\n0.2.3\n')
            return super().request(method, path, payload)

    api = API()
    assert submit_release(api, verified_release(), _evidence(), manifest=_manifest())['status'] == 'race'
    assert api.writes == []


@pytest.mark.parametrize('mismatch', ['draft', 'prerelease', 'source_sha', 'digest'])
def test_remote_release_change_blocks_submission(mismatch):
    class API(ReadyAPI):
        def request(self, method, path, payload=None):
            result = super().request(method, path, payload)
            if '/releases/tags/' in path:
                if mismatch in ('draft', 'prerelease'):
                    result[mismatch] = True
                if mismatch == 'digest':
                    result['assets'][0]['digest'] = 'sha256:' + '0' * 64
            if '/git/ref/tags/' in path and mismatch == 'source_sha':
                result['object']['sha'] = '0' * 40
            return result

    api = API()
    assert submit_release(api, verified_release(), _evidence(), manifest=_manifest())['action'] == 'block'
    assert api.writes == []


def test_policy_files_are_pinned_to_one_live_commit_not_caller_fingerprint():
    api = ReadyAPI()
    evidence = _evidence(policy_fingerprint='forged')
    result = submit_release(api, verified_release(), evidence, manifest=_manifest())
    assert result['action'] == 'create'
    assert all(path.endswith('?ref=' + 'b' * 40) for path in api.reads if '/contents/' in path)


def test_update_preserves_supersession_link():
    old = owned_issue(labels=['extension-submission'],
                      body=f'<!-- {MARKER} -->\n### Version\n\n0.2.0\n')
    pending = owned_issue(number=42, body=f'<!-- {MARKER} -->\n### Version\n\n0.2.1\n\nSupersedes #41\n')

    class API(ReadyAPI):
        def pages(self, path):
            if path.endswith('/timeline'):
                return []
            return [old, pending]

        def request(self, method, path, payload=None):
            if method == 'GET' and path == '/repos/github/spec-kit/issues/42':
                return pending
            if method == 'PATCH':
                self.writes.append((method, path, payload))
                return {'number': 42, 'html_url': 'https://github.com/github/spec-kit/issues/42'}
            return super().request(method, path, payload)

    api = API()
    result = submit_release(api, verified_release(), _evidence(), manifest=_manifest())
    assert result['action'] == 'update_untriaged'
    assert 'Supersedes #41' in api.writes[-1][2]['body']
