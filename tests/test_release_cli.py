import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from github_api import GitHubAPIError
from release_cli import main

REPO = 'CrazyBaran/spec-kit-usage-bridge'
SHA = 'a' * 40
OLD = 'b' * 40
APP = 15368


class FakeAPI:
    def __init__(self):
        self.created_issues = []
        self.created_releases = []
        self.created_pull_requests = []
        self.uploads = []
        self.releases = []
        self.pulls = []
        self.refs = {}
        self.direct_main_updates = []
        self.deleted_branches = []
        self.auto_merges = []
        self._next = 1
        self.error = None

    def pages(self, path):
        if self.error is not None:
            raise self.error
        if path.endswith('/releases'):
            return list(self.releases)
        if '/pulls' in path:
            return list(self.pulls)
        if path.endswith('/issues') or '/issues?' in path:
            return []
        return []

    def request(self, method, path, payload=None):
        if self.error is not None:
            raise self.error
        if method == 'GET' and '/git/ref/heads/release/' in path:
            name = path.rsplit('/', 1)[-1]
            if name not in self.refs:
                raise GitHubAPIError('missing ref', status=404)
            return {'object': {'sha': self.refs[name]}}
        if method == 'POST' and path.endswith('/releases'):
            release = {
                'id': self._next, 'tag_name': payload['tag_name'], 'draft': True,
                'prerelease': payload['prerelease'], 'body': payload.get('body', ''),
                'assets': [], 'target_commitish': payload.get('target_commitish'),
            }
            self._next += 1
            self.created_releases.append(release)
            self.releases.append(release)
            return release
        if method == 'POST' and '/assets' in path:
            asset = {'name': payload['name'], 'sha256': payload['sha256']}
            self.uploads.append(asset)
            release_id = int(path.split('/releases/')[1].split('/')[0])
            next(item for item in self.releases if item['id'] == release_id)['assets'].append(asset)
            return asset
        if method == 'PATCH' and '/releases/' in path:
            release = next(item for item in self.releases if str(item['id']) in path)
            release.update(payload)
            return release
        if method == 'POST' and path.endswith('/pulls'):
            self.created_pull_requests.append(payload)
            return {'html_url': 'https://example.test/pull/1'}
        if method == 'PUT' and path.endswith('/graphql'):
            self.auto_merges.append(payload)
            return {'data': {}}
        if method == 'DELETE' and '/git/refs/heads/' in path:
            self.deleted_branches.append(path)
            return {}
        if method == 'PATCH' and '/pulls/' in path:
            return payload or {}
        if method == 'POST' and path.endswith('/merge'):
            self.direct_main_updates.append(payload)
            raise GitHubAPIError('direct merge is forbidden', status=403)
        raise GitHubAPIError('unexpected ' + method + ' ' + path, status=500)


@pytest.fixture
def cli_fixture(tmp_path, capsys):
    api = FakeAPI()

    def run(*args):
        code = main(list(args), api=api)
        captured = capsys.readouterr()
        return SimpleNamespace(returncode=code, stdout=captured.out, stderr=captured.err, api=api)

    run.api = api
    fixture = SimpleNamespace(run=run, api=api, root=tmp_path)
    return fixture


def _evidence(tmp_path: Path, **overrides) -> Path:
    payload = {
        'schema_version': 1, 'repository': REPO, 'version': '0.2.2', 'tag': 'v0.2.2',
        'source_sha': SHA, 'run_id': 1, 'attempt': 1, 'zip_sha256': 'abc',
        'candidate_tag': 'v0.2.2-rc.1', 'checks': [], 'override': None,
        'verification': {'provenance': True, 'build_sha': SHA},
        'changelog': '## [0.2.2]\n\nReady.\n',
    }
    payload.update(overrides)
    path = tmp_path / 'evidence.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def _check(name, conclusion='success', status='completed'):
    return {
        'name': name, 'source_sha': SHA, 'run_id': 1, 'attempt': 1, 'app_id': APP,
        'status': status, 'conclusion': conclusion, 'url': 'https://example.test/checks/' + name,
    }


def test_prepare_dry_run_creates_no_release(cli_fixture, tmp_path):
    output = tmp_path / 'prepare.json'
    result = cli_fixture.run(
        'prepare', '--version', '0.2.2', '--main-sha', SHA, '--output', str(output), '--dry-run',
    )
    assert result.returncode == 0
    body = json.loads(output.read_text(encoding='utf-8'))
    assert body['branch'] == 'release/0.2.2'
    assert cli_fixture.api.created_releases == []
    assert cli_fixture.api.created_pull_requests == []


def test_candidate_then_stale_promotion_then_new_candidate(cli_fixture, tmp_path):
    first = tmp_path / 'candidate.json'
    result = cli_fixture.run(
        'candidate-context', '--version', '0.2.2', '--source-sha', SHA, '--output', str(first),
    )
    assert result.returncode == 0
    assert json.loads(first.read_text(encoding='utf-8'))['candidate_tag'] == 'v0.2.2-rc.1'
    cli_fixture.api.releases.append({
        'tag_name': 'v0.2.2-rc.1', 'draft': False, 'prerelease': True, 'target_commitish': OLD,
    })
    stale = tmp_path / 'stale.json'
    blocked = cli_fixture.run(
        'promotion-context', '--version', '0.2.2', '--candidate-tag', 'v0.2.2-rc.1',
        '--source-sha', SHA, '--output', str(stale),
    )
    assert blocked.returncode == 2
    again = tmp_path / 'next.json'
    retry = cli_fixture.run(
        'candidate-context', '--version', '0.2.2', '--source-sha', SHA, '--output', str(again),
    )
    assert retry.returncode == 0
    assert json.loads(again.read_text(encoding='utf-8'))['candidate_tag'] == 'v0.2.2-rc.2'
    assert cli_fixture.api.created_releases == []


def test_approved_quality_override_still_requires_install(cli_fixture, tmp_path):
    digest = 'ab' * 32
    evidence = tmp_path / 'gate.json'
    evidence.write_text(json.dumps({
        'source_sha': SHA,
        'digest': digest,
        'required': ['lint', 'install (ubuntu-latest, minimum)'],
        'checks': [_check('lint', conclusion='failure')],
        'override': {
            'requested': True, 'approved': True, 'reason': 'known lint flake',
            'waived_checks': ['lint'], 'run_id': 1, 'attempt': 1, 'source_sha': SHA,
        },
        'approvals': [{
            'environment': 'release-override', 'approver': 'CrazyBaran', 'run_id': 1,
            'attempt': 1, 'source_sha': SHA, 'digest': digest,
        }],
    }), encoding='utf-8')
    output = tmp_path / 'decision.json'
    result = cli_fixture.run('gate', '--evidence', str(evidence), '--output', str(output))
    decision = json.loads(output.read_text(encoding='utf-8'))
    assert result.returncode == 2
    assert decision['waived'] == ['lint']
    assert any('install' in blocker for blocker in decision['blockers'])


def test_input_approved_flag_does_not_waive(cli_fixture, tmp_path):
    evidence = tmp_path / 'gate.json'
    evidence.write_text(json.dumps({
        'source_sha': SHA, 'digest': 'cd' * 32, 'required': ['lint'],
        'checks': [_check('lint', conclusion='failure')],
        'override': {
            'requested': True, 'approved': True, 'reason': 'not reviewed',
            'waived_checks': ['lint'], 'run_id': 1, 'attempt': 1, 'source_sha': SHA,
        },
        'approvals': [],
    }), encoding='utf-8')
    output = tmp_path / 'decision.json'
    result = cli_fixture.run('gate', '--evidence', str(evidence), '--output', str(output))
    decision = json.loads(output.read_text(encoding='utf-8'))
    assert result.returncode == 2
    assert decision['approved'] is False
    assert decision['waived'] == []


def test_publish_interruption_does_not_republish(cli_fixture, tmp_path):
    asset = tmp_path / 'assets' / 'usage-bridge-v0.2.2.zip'
    asset.parent.mkdir()
    asset.write_bytes(b'zip-bytes')
    evidence = _evidence(tmp_path, tag='v0.2.2-rc.1', zip_sha256='abc')
    output = tmp_path / 'publish.json'
    args = (
        'publish', '--evidence', str(evidence), '--assets-dir', str(asset.parent),
        '--output', str(output), '--prerelease',
    )
    assert cli_fixture.run(*args).returncode == 0
    assert cli_fixture.run(*args).returncode == 0
    assert len(cli_fixture.api.created_releases) == 1
    assert len(cli_fixture.api.uploads) == 1


def test_stable_verification_checks_the_local_archive(cli_fixture, tmp_path):
    blob = b'verified-zip'
    archive = tmp_path / 'usage-bridge-v0.2.2.zip'
    archive.write_bytes(blob)
    evidence = _evidence(tmp_path, zip_sha256=hashlib.sha256(blob).hexdigest())
    output = tmp_path / 'verify.json'
    result = cli_fixture.run(
        'verify', '--tag', 'v0.2.2', '--evidence', str(evidence), '--archive', str(archive),
        '--download-dir', str(tmp_path / 'download'), '--output', str(output),
    )
    assert result.returncode == 0
    assert json.loads(output.read_text(encoding='utf-8'))['source_sha'] == SHA


def test_mergeback_conflict_does_not_push_main(cli_fixture, tmp_path):
    cli_fixture.api.pulls.append({
        'number': 7, 'draft': True, 'merged': False, 'mergeable': False,
        'html_url': 'https://example.test/pull/7',
        'head': {'ref': 'release/0.2.2', 'sha': SHA}, 'base': {'ref': 'main'},
    })
    verification = tmp_path / 'verification.json'
    verification.write_text(json.dumps({'provenance': True, 'build_sha': SHA}), encoding='utf-8')
    output = tmp_path / 'merge.json'
    result = cli_fixture.run(
        'mergeback', '--version', '0.2.2', '--source-sha', SHA,
        '--verification', str(verification), '--output', str(output),
    )
    assert result.returncode == 2
    assert json.loads(output.read_text(encoding='utf-8'))['status'] == 'manual_action_required'
    assert cli_fixture.api.direct_main_updates == []
    assert cli_fixture.api.deleted_branches == []


def test_submission_pending_creates_no_issue(cli_fixture, tmp_path):
    verification = _evidence(tmp_path)
    evidence = tmp_path / 'submission.json'
    evidence.write_text(json.dumps({
        'install_verified': True, 'commands_verified': True,
        'attestations': {'real_project': 'ran specify once'},
        'policy_fingerprint': '0' * 64,
    }), encoding='utf-8')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({
        'extension': {
            'id': 'usage-bridge', 'name': 'Usage Bridge', 'version': '0.2.2',
            'description': 'Bridges token usage.', 'author': 'CrazyBaran', 'license': 'MIT',
        },
        'requires': {'speckit_version': '>=1.0.12'},
        'provides': {'commands': [{}, {}, {}, {}]},
        'tags': ['tokens'],
    }), encoding='utf-8')
    output = tmp_path / 'pending.json'
    result = cli_fixture.run(
        'submit', '--tag', 'v0.2.2', '--verification', str(verification),
        '--evidence', str(evidence), '--manifest', str(manifest), '--output', str(output),
    )
    body = json.loads(output.read_text(encoding='utf-8'))
    assert result.returncode == 0
    assert body['status'] == 'pending'
    assert '### Proposed Catalog Entry' in body['body']
    assert cli_fixture.api.created_issues == []


def test_submit_prerelease_is_policy_error(cli_fixture):
    result = cli_fixture.run('submit', '--tag', 'v0.2.2-rc.1')
    assert result.returncode == 2
    assert cli_fixture.api.created_issues == []


def test_api_failure_redacts_credentials(cli_fixture, tmp_path, monkeypatch):
    monkeypatch.setenv('GH_TOKEN', 'super-secret-token')
    cli_fixture.api.error = GitHubAPIError('super-secret-token failed', status=502)
    output = tmp_path / 'candidate.json'
    result = cli_fixture.run(
        'candidate-context', '--version', '0.2.2', '--source-sha', SHA, '--output', str(output),
    )
    assert result.returncode == 3
    assert 'super-secret-token' not in result.stderr
    assert '***' in result.stderr


def test_missing_configuration_exits_4(cli_fixture, tmp_path):
    result = cli_fixture.run(
        'gate', '--evidence', str(tmp_path / 'missing.json'), '--output', str(tmp_path / 'out.json'),
    )
    assert result.returncode == 4
    assert 'missing configuration file' in result.stderr
    assert 'GH_TOKEN' not in result.stderr
