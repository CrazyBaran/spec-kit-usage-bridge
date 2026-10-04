import hashlib
import json
import subprocess
import zipfile
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
        self.tags = {}
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
            return {'object': {'type': 'commit', 'sha': self.refs[name]}}
        if method == 'GET' and '/git/ref/tags/' in path:
            tag = path.rsplit('/', 1)[-1]
            if tag not in self.tags:
                raise GitHubAPIError('missing tag', status=404)
            return {'object': {'type': 'commit', 'sha': self.tags[tag]}}
        if method == 'GET' and path.endswith('/git/ref/heads/main'):
            return {'object': {'type': 'commit', 'sha': SHA}}
        if method != 'GET':
            raise AssertionError('unexpected mutation in read-only CLI fake: ' + method + ' ' + path)
        raise GitHubAPIError('unexpected ' + method + ' ' + path, status=500)


@pytest.fixture
def cli_fixture(tmp_path, capsys):
    api = FakeAPI()

    def run(*args):
        code = main(list(args), api=fixture.api)
        captured = capsys.readouterr()
        return SimpleNamespace(returncode=code, stdout=captured.out, stderr=captured.err, api=fixture.api)

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
    cli_fixture.api.refs['0.2.2'] = SHA
    first = tmp_path / 'candidate.json'
    result = cli_fixture.run(
        'candidate-context', '--version', '0.2.2', '--source-sha', SHA, '--output', str(first),
    )
    assert result.returncode == 0
    assert json.loads(first.read_text(encoding='utf-8'))['candidate_tag'] == 'v0.2.2-rc.1'
    cli_fixture.api.releases.append({
        'tag_name': 'v0.2.2-rc.1', 'draft': False, 'prerelease': True, 'target_commitish': OLD,
    })
    cli_fixture.api.tags['v0.2.2-rc.1'] = OLD
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
    from test_release_publication import FakeAPI as PublicationAPI
    from test_release_publication import release_assets

    class InterruptedAPI(PublicationAPI):
        interrupted = False

        def upload_asset(self, url, name, path):
            result = super().upload_asset(url, name, path)
            if not self.interrupted:
                self.interrupted = True
                raise GitHubAPIError('upload response timed out after remote acceptance', status=504)
            return result

    cli_fixture.api = InterruptedAPI()
    _metadata, assets = release_assets(tmp_path / 'assets')
    evidence = assets['release-metadata.json']
    output = tmp_path / 'publish.json'
    args = (
        'publish', '--evidence', str(evidence), '--assets-dir', str(evidence.parent),
        '--output', str(output), '--prerelease',
    )
    assert cli_fixture.run(*args).returncode == 3
    assert len(cli_fixture.api.created_releases) == 1
    assert len(cli_fixture.api.uploads) == 1
    assert cli_fixture.run(*args).returncode == 0
    assert cli_fixture.run(*args).returncode == 0
    assert len(cli_fixture.api.created_releases) == 1
    assert len(cli_fixture.api.uploads) == 4


def test_stable_verification_downloads_published_assets(cli_fixture, tmp_path):
    from test_release_verification import published

    api, evidence, assets = published(tmp_path / 'assets')
    cli_fixture.api = api
    # The real download transport creates parent directories before writing.
    original_download = api.download_asset

    def download(url, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        return original_download(url, destination)

    api.download_asset = download
    output = tmp_path / 'verify.json'
    result = cli_fixture.run(
        'verify', '--tag', 'v0.2.2',
        '--download-dir', str(tmp_path / 'download'), '--output', str(output),
    )
    assert result.returncode == 0
    body = json.loads(output.read_text(encoding='utf-8'))
    assert body['source_sha'] == SHA
    assert body['zip_sha256'] == evidence['zip_sha256']
    assert body['packaging_verified'] is True
    assert body['install_verified'] is False
    downloaded = tmp_path / 'download' / 'usage-bridge-v0.2.2.zip'
    assert downloaded.read_bytes() == assets['usage-bridge-v0.2.2.zip'].read_bytes()


def test_local_archive_flag_cannot_substitute_for_remote_verification(cli_fixture, tmp_path):
    archive = tmp_path / 'local.zip'
    archive.write_bytes(b'local-bytes')
    result = cli_fixture.run('verify', '--tag', 'v0.2.2', '--archive', str(archive),
                             '--download-dir', str(tmp_path / 'download'), '--output', str(tmp_path / 'out.json'))
    assert result.returncode == 2
    assert 'unrecognized arguments' in result.stderr


def test_mergeback_conflict_does_not_push_main(cli_fixture, tmp_path):
    from test_release_mergeback import FakeAPI as MergebackAPI
    from test_release_publication import release_assets

    cli_fixture.api = MergebackAPI()
    cli_fixture.api.pull_request['mergeable'] = False
    metadata, _assets = release_assets(tmp_path / 'assets', tag='v0.2.2')
    verification = tmp_path / 'verification.json'
    verification.write_text(json.dumps(metadata['verification']), encoding='utf-8')
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


def test_promotion_emits_stable_tag_to_workflow_output(cli_fixture, tmp_path, monkeypatch):
    cli_fixture.api.refs['0.2.2'] = SHA
    cli_fixture.api.tags['v0.2.2-rc.1'] = SHA
    cli_fixture.api.releases.append({'tag_name': 'v0.2.2-rc.1', 'draft': False, 'prerelease': True})
    workflow_output = tmp_path / 'workflow-output.txt'
    monkeypatch.setenv('GITHUB_OUTPUT', str(workflow_output))
    result = cli_fixture.run('promotion-context', '--version', '0.2.2', '--candidate-tag', 'v0.2.2-rc.1',
                             '--source-sha', SHA, '--output', str(tmp_path / 'promotion.json'))
    assert result.returncode == 0
    assert 'tag=v0.2.2\n' in workflow_output.read_text(encoding='utf-8')
    assert 'tag=v0.2.2-rc.1\n' not in workflow_output.read_text(encoding='utf-8')


def test_promotion_rejects_old_input_sha_after_release_branch_moves(cli_fixture, tmp_path):
    cli_fixture.api.refs['0.2.2'] = SHA
    cli_fixture.api.tags['v0.2.2-rc.1'] = OLD
    cli_fixture.api.releases.append({'tag_name': 'v0.2.2-rc.1', 'draft': False, 'prerelease': True})
    result = cli_fixture.run('promotion-context', '--version', '0.2.2', '--candidate-tag', 'v0.2.2-rc.1',
                             '--source-sha', OLD, '--output', str(tmp_path / 'promotion.json'))
    assert result.returncode == 2
    assert 'branch moved' in result.stderr
    assert cli_fixture.api.created_releases == []


def test_verification_rejects_remote_tampering_even_when_local_asset_is_intact(cli_fixture, tmp_path):
    from test_release_verification import published

    api, _evidence, assets = published(tmp_path / 'assets')
    cli_fixture.api = api
    metadata_path = assets['release-metadata.json']
    remote_archive = next(asset for asset in api.releases[0]['assets'] if asset['name'].endswith('.zip'))
    api.blobs[remote_archive['url']] = b'tampered remote archive'
    assert assets[remote_archive['name']].is_file()
    result = cli_fixture.run('verify', '--tag', 'v0.2.2', '--evidence', str(metadata_path),
                             '--download-dir', str(tmp_path / 'download'), '--output', str(tmp_path / 'verified.json'))
    assert result.returncode == 2
    assert 'digest' in result.stderr
    assert not (tmp_path / 'verified.json').exists()


@pytest.mark.parametrize('mismatch', ['source_sha', 'digest', 'tag', 'install_verified'])
def test_follow_through_identity_rejects_unverified_or_wrong_artifact(cli_fixture, tmp_path, mismatch):
    from test_release_publication import release_assets

    metadata, _assets = release_assets(tmp_path / 'assets', tag='v0.2.2')
    record = metadata['verification']
    if mismatch == 'source_sha':
        record['source_sha'] = OLD
    elif mismatch == 'digest':
        record['zip_sha256'] = '0' * 64
    elif mismatch == 'tag':
        record['tag'] = 'v0.2.3'
    else:
        record['install_verified'] = False
    verification = tmp_path / 'verification.json'
    verification.write_text(json.dumps(record), encoding='utf-8')
    result = cli_fixture.run('check-verification', '--verification', str(verification), '--tag', 'v0.2.2',
                             '--source-sha', SHA, '--digest', metadata['zip_sha256'],
                             '--output', str(tmp_path / 'identity.json'))
    assert result.returncode == 2
    assert not (tmp_path / 'identity.json').exists()


def test_mergeback_success_uses_real_graphql_node_identity(cli_fixture, tmp_path):
    from test_release_mergeback import FakeAPI as MergebackAPI
    from test_release_publication import release_assets

    cli_fixture.api = MergebackAPI()
    metadata, _assets = release_assets(tmp_path / 'assets', tag='v0.2.2')
    verification = tmp_path / 'verification.json'
    verification.write_text(json.dumps(metadata['verification']), encoding='utf-8')
    result = cli_fixture.run('mergeback', '--version', '0.2.2', '--source-sha', SHA,
                             '--verification', str(verification), '--output', str(tmp_path / 'merge.json'))
    assert result.returncode == 0
    assert len(cli_fixture.api.graphql_calls) == 2
    assert cli_fixture.api.auto_merges[0]['variables']['input'] == {
        'pullRequestId': 'PR_node_7', 'mergeMethod': 'MERGE'}
    assert cli_fixture.api.direct_main_updates == []
    assert cli_fixture.api.deleted_branches == []


def test_clean_cli_candidate_to_stable_chain_uses_same_remote_archive_bytes(cli_fixture, tmp_path):
    from test_release_publication import FakeAPI as PublicationAPI
    from test_release_publication import release_assets

    fixture_metadata, fixture_assets = release_assets(tmp_path / 'fixture')
    checkout = tmp_path / 'source'
    checkout.mkdir()
    with zipfile.ZipFile(fixture_assets['usage-bridge-v0.2.2.zip']) as archive:
        for member in archive.infolist():
            relative = member.filename.removeprefix('usage-bridge/')
            destination = checkout / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(member))
    (checkout / 'CHANGELOG.md').write_text(fixture_metadata['changelog'], encoding='utf-8')
    for arguments in (['init', '-b', 'main'], ['add', '.'],
                      ['-c', 'user.name=Release Fixture', '-c', 'user.email=fixture@example.test',
                       'commit', '-m', 'Fixture runtime source']):
        subprocess.run(['git', *arguments], cwd=checkout, check=True, capture_output=True, text=True)
    source_sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=checkout, check=True,
                                capture_output=True, text=True).stdout.strip()

    class ChainAPI(PublicationAPI):
        def pages(self, path):
            rows = super().pages(path)
            if path.endswith('/jobs'):
                rows.extend(dict(name=f'verify-install ({platform}, {host})', status='completed',
                                 conclusion='success', html_url='https://example.test/runtime')
                            for platform in ('ubuntu-latest', 'windows-latest') for host in ('minimum', 'current'))
            return rows

        def download_asset(self, url, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            return super().download_asset(url, destination)

        def request(self, method, path, payload=None):
            if method == 'GET' and '/contents/README.md?' in path:
                return {'type': 'file', 'size': 30}
            return super().request(method, path, payload)

    api = ChainAPI()
    api.branch_sha = source_sha
    api.tags = {}
    cli_fixture.api = api

    def run(*arguments):
        result = cli_fixture.run(*map(str, arguments))
        assert result.returncode == 0, result.stderr

    candidate_dir = tmp_path / 'candidate-assets'
    run('candidate-context', '--version', '0.2.2', '--source-sha', source_sha,
        '--output', tmp_path / 'candidate-context.json')
    run('bundle', '--checkout', checkout, '--version', '0.2.2', '--tag', 'v0.2.2-rc.1',
        '--source-sha', source_sha, '--run-id', '1', '--attempt', '1',
        '--assets-dir', candidate_dir, '--output', tmp_path / 'candidate-bundle.json')
    run('collect', '--evidence', candidate_dir / 'release-metadata.json',
        '--assets-dir', candidate_dir, '--output', tmp_path / 'candidate-evidence.json')
    run('publish', '--evidence', candidate_dir / 'release-metadata.json',
        '--assets-dir', candidate_dir, '--prerelease', '--output', tmp_path / 'candidate-published.json')
    candidate_bytes = (candidate_dir / 'usage-bridge-v0.2.2.zip').read_bytes()
    run('promotion-context', '--version', '0.2.2', '--candidate-tag', 'v0.2.2-rc.1',
        '--source-sha', source_sha, '--output', tmp_path / 'promotion-context.json')
    stable_dir = tmp_path / 'stable-assets'
    run('bundle', '--checkout', checkout, '--version', '0.2.2', '--tag', 'v0.2.2',
        '--candidate-tag', 'v0.2.2-rc.1', '--source-sha', source_sha, '--run-id', '1', '--attempt', '1',
        '--assets-dir', stable_dir, '--output', tmp_path / 'stable-bundle.json')
    assert (stable_dir / 'usage-bridge-v0.2.2.zip').read_bytes() == candidate_bytes
    run('collect', '--evidence', stable_dir / 'release-metadata.json',
        '--assets-dir', stable_dir, '--output', tmp_path / 'stable-evidence.json')
    run('publish', '--evidence', stable_dir / 'release-metadata.json',
        '--assets-dir', stable_dir, '--output', tmp_path / 'stable-published.json')
    downloaded = tmp_path / 'downloaded'
    run('verify', '--tag', 'v0.2.2', '--download-dir', downloaded,
        '--output', downloaded / 'verification.json')
    assert (downloaded / 'usage-bridge-v0.2.2.zip').read_bytes() == candidate_bytes
    complete = tmp_path / 'complete.json'
    run('complete-verification', '--verification', downloaded / 'verification.json',
        '--run-id', '1', '--attempt', '1', '--output', complete)
    verification = json.loads(complete.read_text(encoding='utf-8'))
    assert verification['install_verified'] is True
    assert verification['commands_verified'] is True
    assert len(verification['runtime']) == 4
    checksum = hashlib.sha256(candidate_bytes).hexdigest()
    run('check-verification', '--verification', complete, '--tag', 'v0.2.2',
        '--source-sha', source_sha, '--digest', checksum, '--output', tmp_path / 'identity.json')
    submission = tmp_path / 'submission-evidence.json'
    run('submission-evidence', '--verification', complete, '--output', submission)
    run('submit', '--tag', 'v0.2.2', '--verification', complete, '--evidence', submission,
        '--manifest', downloaded / 'extension.json', '--output', tmp_path / 'pending-submission.json')
    assert json.loads((tmp_path / 'pending-submission.json').read_text(encoding='utf-8'))['status'] == 'pending'
    assert len(api.created_releases) == 2
    assert len(api.uploads) == 8
    assert api.tags == {'v0.2.2-rc.1': source_sha, 'v0.2.2': source_sha}
