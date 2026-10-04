import json
from pathlib import Path

import pytest

from github_api import GitHubAPIError
from release.policy import ReleasePolicyError
from release.submission import choose_submission_action, render_submission, submit_release

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
    data = {
        'install_verified': True,
        'commands_verified': True,
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
    result = submit_release(api, verified_release(), evidence, manifest=_manifest())
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
    result = submit_release(api, verified_release(), _evidence(), manifest=_manifest())
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

    result = submit_release(API(), verified_release(), _evidence(), manifest=_manifest())
    assert result['action'] == 'block'


def test_forbidden_status_blocks_without_a_write():
    class API:
        def pages(self, path):
            raise GitHubAPIError('forbidden', status=403)

        def request(self, method, path, payload=None):
            raise GitHubAPIError('forbidden', status=403)

    result = submit_release(API(), verified_release(), _evidence(), manifest=_manifest())
    assert result['action'] == 'block'
    assert result['status'] == 'forbidden'


def test_prerelease_is_not_submitted():
    release = verified_release(prerelease=True, tag='v0.2.2-rc.1')
    with pytest.raises(ReleasePolicyError):
        submit_release(object(), release, _evidence(), manifest=_manifest())
