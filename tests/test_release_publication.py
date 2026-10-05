import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from github_api import GitHubAPIError
from release.policy import WAIVABLE_CHECKS, ReleasePolicyError
from release.publication import publish_release

ROOT = Path(__file__).resolve().parents[1]
REPO = 'CrazyBaran/spec-kit-usage-bridge'
SHA = 'a' * 40
OTHER = 'b' * 40


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_records(sha, checksum):
    return [dict(source_sha=sha, zip_sha256=checksum, isolated=True, host=host,
                 platform=platform, host_ref='v1.0.12', run_id=1, attempt=1,
                 commands={name: 0 for name in ('install', 'checkpoint', 'capture', 'report', 'check', 'upgrade')})
            for platform in ('linux', 'windows') for host in ('minimum', 'current')]


def release_assets(tmp_path, tag='v0.2.2-rc.1', version='0.2.2'):
    from release.artifacts import ENTRYPOINTS, LEGAL_FILES, PRICING, VENDOR_FILES
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest = yaml.safe_load((ROOT / 'extension.yml').read_text(encoding='utf-8'))
    manifest['extension']['version'] = version
    members = set(ENTRYPOINTS + LEGAL_FILES + VENDOR_FILES + (PRICING,))
    members.update(command['file'] for command in manifest['provides']['commands'])
    members.update(path.relative_to(ROOT).as_posix() for path in (ROOT / 'scripts/python/usage_bridge').rglob('*.py'))
    archive = tmp_path / f'usage-bridge-v{version}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
        for member in sorted(members):
            data = yaml.safe_dump(manifest).encode() if member == 'extension.yml' else (ROOT / member).read_bytes()
            info = zipfile.ZipInfo('usage-bridge/' + member, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zipped.writestr(info, data)
    checksum = digest(archive)
    verification = dict(schema_version=1, repository=REPO, version=version, tag=tag,
                        source_sha=SHA, build_sha=SHA, zip_sha256=checksum, provenance=True,
                        packaging_verified=True, archive_verified=True, catalog_verified=True,
                        checksums_verified=True, install_verified=True, commands_verified=True,
                        runtime=runtime_records(SHA, checksum))
    evidence = dict(schema_version=1, repository=REPO, version=version, tag=tag, source_sha=SHA,
                    run_id=1, attempt=1, zip_sha256=checksum, candidate_tag='v0.2.2-rc.1',
                    checks=[dict(name=name, source_sha=SHA, run_id=1, attempt=1, app_id=15368,
                                 status='completed', conclusion='success', url='https://example.test/check')
                            for name in WAIVABLE_CHECKS], override=None, verification=verification,
                    members=sorted(members),
                    changelog=f'## [{version}]\n\nReady.\n')
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'schema_version': '1.0',
        'catalog_url': f'https://github.com/{REPO}/releases/download/{tag}/catalog.json',
        'extensions': {'usage-bridge': dict(version=version, sha256=checksum,
            download_url=f'https://github.com/{REPO}/releases/download/{tag}/{archive.name}')}}), encoding='utf-8')
    metadata = tmp_path / 'release-metadata.json'
    metadata.write_text(json.dumps(evidence), encoding='utf-8')
    assets = {path.name: path for path in (archive, catalog, metadata)}
    sums = tmp_path / 'SHA256SUMS'
    sums.write_text(''.join(f'{digest(path)}  {name}\n' for name, path in sorted(assets.items())), encoding='utf-8')
    assets[sums.name] = sums
    return evidence, assets


class FakeAPI:
    def __init__(self):
        self.created_releases = []
        self.uploads = []
        self.releases = []
        self.branch_sha = SHA
        self.source_sha = SHA
        self.tags = {'v0.2.2-rc.1': SHA}
        self.blobs = {}
        self.provenance = True
        self._next = 1
        self.source_vendor = (ROOT / 'scripts/python/vendor/token_usage/VENDOR.json').read_bytes()

    def request(self, method, path, payload=None):
        if method == 'GET' and '/contents/scripts/python/vendor/token_usage/VENDOR.json?' in path:
            assert path.endswith('?ref=' + self.source_sha)
            return {'type': 'file', 'encoding': 'base64', 'size': len(self.source_vendor),
                    'content': base64.b64encode(self.source_vendor).decode()}
        if method == 'GET' and path.endswith('/immutable-releases'):
            return {'enabled': True}
        if method == 'GET' and '/actions/runs/' in path and '/attempts/' in path:
            return dict(head_branch='main', event='workflow_dispatch', head_repository={'full_name': REPO},
                        path='.github/workflows/release.yml', run_attempt=int(path.rsplit('/', 1)[1]))
        if method == 'GET' and '/git/ref/heads/release/' in path:
            return {'object': {'type': 'commit', 'sha': self.branch_sha}}
        if method == 'GET' and '/git/ref/tags/' in path:
            tag = path.split('/git/ref/tags/')[1]
            if tag not in self.tags:
                raise GitHubAPIError('missing tag', status=404)
            return {'object': {'type': 'commit', 'sha': self.tags[tag]}}
        if method == 'POST' and path.endswith('/git/refs'):
            self.tags[payload['ref'].split('refs/tags/')[1]] = payload['sha']
            return {'object': {'type': 'commit', 'sha': payload['sha']}}
        if method == 'POST' and path.endswith('/releases'):
            release = dict(id=self._next, tag_name=payload['tag_name'], draft=True,
                           prerelease=payload['prerelease'], body=payload['body'],
                           make_latest=payload['make_latest'], assets=[],
                           target_commitish='release/0.2.2',
                           upload_url=f'https://uploads.github.com/repos/{REPO}/releases/{self._next}/assets{{?name,label}}')
            self._next += 1
            self.created_releases.append(release)
            self.releases.append(release)
            return release
        if method == 'PATCH' and '/releases/' in path:
            release = next(item for item in self.releases if str(item['id']) == path.rsplit('/', 1)[1])
            release.update(payload)
            release['immutable'] = not release['draft']
            return release
        if method == 'GET' and '/releases/tags/' in path:
            return next(item for item in self.releases if item['tag_name'] == path.split('/releases/tags/')[1])
        raise GitHubAPIError('unexpected ' + method + ' ' + path, status=500)

    def upload_asset(self, url, name, path):
        release_id = int(url.split('/releases/')[1].split('/')[0])
        blob = Path(path).read_bytes()
        asset = dict(id=self._next, name=name, digest='sha256:' + hashlib.sha256(blob).hexdigest(),
                     url=f'https://api.github.com/repos/{REPO}/releases/assets/{self._next}')
        self._next += 1
        self.blobs[asset['url']] = blob
        self.uploads.append(asset)
        next(item for item in self.releases if item['id'] == release_id)['assets'].append(asset)
        return asset

    def download_asset(self, url, dest):
        Path(dest).write_bytes(self.blobs[url])
        return dest

    def verify_attestation(self, path, repo, source_sha, **bindings):
        if not self.provenance:
            raise GitHubAPIError('invalid attestation')
        return True

    def pages(self, path):
        if path.endswith('/releases'):
            return list(self.releases)
        if path.endswith('/jobs'):
            names = list(WAIVABLE_CHECKS) + [f'install ({os}, {host})'
                for os in ('ubuntu-latest', 'windows-latest') for host in ('minimum', 'current')]
            return [dict(name=name, status='completed', conclusion='success', html_url='https://example.test/job')
                    for name in names]
        return []


def candidate(api, checksum=None):
    api.releases.append(dict(id=99, tag_name='v0.2.2-rc.1', draft=False,
                             prerelease=True, immutable=True, target_commitish='release/0.2.2',
                             assets=[] if checksum is None else [dict(name='usage-bridge-v0.2.2.zip',
                                                                     digest='sha256:' + checksum)]))


def test_publish_uploads_bytes_and_retry_accepts_github_digest(tmp_path):
    api = FakeAPI()
    evidence, assets = release_assets(tmp_path)
    first = publish_release(api, evidence, assets, prerelease=True)
    second = publish_release(api, evidence, assets, prerelease=True)
    assert first['release_id'] == second['release_id']
    assert len(api.created_releases) == 1
    assert len(api.uploads) == 4
    remote_archive = next(item for item in api.uploads if item['name'].endswith('.zip'))
    assert api.blobs[remote_archive['url']] == assets[remote_archive['name']].read_bytes()
    assert api.created_releases[0]['make_latest'] == 'false'


@pytest.mark.parametrize('defect', [
    'missing_assets', 'digest', 'checks', 'install', 'branch', 'candidate', 'attestation',
])
def test_publication_rejects_missing_or_stale_prerequisites_without_writes(tmp_path, defect):
    api = FakeAPI()
    evidence, assets = release_assets(tmp_path, tag='v0.2.2')
    candidate(api, evidence['zip_sha256'])
    if defect == 'missing_assets':
        assets.pop('catalog.json')
    elif defect == 'digest':
        evidence['zip_sha256'] = 'f' * 64
    elif defect == 'checks':
        evidence['checks'] = []
    elif defect == 'install':
        evidence['verification']['runtime'] = []
    elif defect == 'branch':
        api.branch_sha = OTHER
    elif defect == 'candidate':
        api.tags['v0.2.2-rc.1'] = OTHER
    else:
        api.provenance = False
    with pytest.raises((ReleasePolicyError, GitHubAPIError)):
        publish_release(api, evidence, assets, prerelease=False)
    assert api.created_releases == []
    assert api.uploads == []


def test_latest_only_for_newest_stable_and_notes_from_changelog(tmp_path):
    api = FakeAPI()
    api.releases.append(dict(id=9, tag_name='v0.3.0', draft=False, prerelease=False, assets=[]))
    evidence, assets = release_assets(tmp_path, tag='v0.2.2')
    candidate(api, evidence['zip_sha256'])
    publish_release(api, evidence, assets, prerelease=False)
    assert api.created_releases[-1]['body'] == 'Ready.\n'
    assert api.created_releases[-1]['make_latest'] == 'false'


def test_reused_draft_rejects_unexpected_remote_asset(tmp_path):
    api = FakeAPI()
    evidence, assets = release_assets(tmp_path / 'assets')
    draft = api.request('POST', f'/repos/{REPO}/releases', {
        'tag_name': evidence['tag'], 'prerelease': True, 'body': 'Ready.\n', 'make_latest': 'false'})
    extra = tmp_path / 'extra.txt'
    extra.write_bytes(b'unverified')
    api.upload_asset(draft['upload_url'], extra.name, extra)
    with pytest.raises(ReleasePolicyError, match='unexpected.*asset'):
        publish_release(api, evidence, assets, prerelease=True)
    assert draft['draft'] is True
    assert [asset['name'] for asset in draft['assets']] == ['extra.txt']


@pytest.mark.parametrize('body', [None, ''])
def test_reused_draft_requires_changelog_notes_before_publication(tmp_path, body):
    api = FakeAPI()
    evidence, assets = release_assets(tmp_path)
    draft = api.request('POST', f'/repos/{REPO}/releases', {
        'tag_name': evidence['tag'], 'prerelease': True, 'body': body, 'make_latest': 'false'})
    with pytest.raises(ReleasePolicyError, match='release notes'):
        publish_release(api, evidence, assets, prerelease=True)
    assert draft['draft'] is True
    assert draft['assets'] == []


def test_branch_move_during_upload_leaves_only_a_draft(tmp_path):
    class MovingAPI(FakeAPI):
        def upload_asset(self, url, name, path):
            uploaded = super().upload_asset(url, name, path)
            self.branch_sha = OTHER
            return uploaded

    api = MovingAPI()
    evidence, assets = release_assets(tmp_path)
    with pytest.raises(ReleasePolicyError):
        publish_release(api, evidence, assets, prerelease=True)
    assert len(api.created_releases) == 1
    assert api.created_releases[0]['draft'] is True


def test_publisher_does_not_trust_caller_green_checks(tmp_path):
    class RedAPI(FakeAPI):
        def pages(self, path):
            records = super().pages(path)
            if path.endswith('/jobs'):
                records[0]['conclusion'] = 'failure'
            return records

    api = RedAPI()
    evidence, assets = release_assets(tmp_path)
    with pytest.raises(ReleasePolicyError):
        publish_release(api, evidence, assets, prerelease=True)
    assert api.created_releases == []
    assert api.uploads == []


@pytest.mark.parametrize('tampered', [False, True])
def test_new_run_reuses_original_immutable_release_without_replacing_metadata(tmp_path, tampered):
    api = FakeAPI()
    original, first_assets = release_assets(tmp_path / 'first')
    first = publish_release(api, original, first_assets, prerelease=True)
    evidence, assets = release_assets(tmp_path / 'retry')
    evidence['run_id'] = 2
    for check in evidence['checks']:
        check['run_id'] = 2
    for record in evidence['verification']['runtime']:
        record['run_id'] = 2
    assets['release-metadata.json'].write_text(json.dumps(evidence))
    assets['SHA256SUMS'].write_text(''.join(f'{digest(path)}  {name}\n' for name, path in sorted(assets.items())
                                          if name != 'SHA256SUMS'))
    metadata_asset = next(asset for asset in api.uploads if asset['name'] == 'release-metadata.json')
    if tampered:
        api.blobs[metadata_asset['url']] = b'bad metadata'
        with pytest.raises(ReleasePolicyError):
            publish_release(api, evidence, assets, prerelease=True)
    else:
        result = publish_release(api, evidence, assets, prerelease=True)
        assert result['release_id'] == first['release_id']
        assert result['reused'] is True
        assert json.loads(api.blobs[metadata_asset['url']])['run_id'] == 1
    assert len(api.created_releases) == 1
    assert len(api.uploads) == 4
