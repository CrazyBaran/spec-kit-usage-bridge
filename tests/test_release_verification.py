import json
import zipfile
from pathlib import Path

import pytest

from github_api import GitHubAPIError
from release.policy import ReleasePolicyError
from release.verification import verify_release
from test_release_publication import SHA, FakeAPI, candidate, release_assets, runtime_records


@pytest.mark.parametrize('operation', ['verify', 'retry'])
def test_historical_release_survives_current_tooling_vendor_update(tmp_path, monkeypatch, operation):
    from release.publication import publish_release
    from test_release_publication import ROOT

    api, evidence, assets = published(tmp_path / 'assets')
    vendor_path = ROOT / 'scripts/python/vendor/token_usage/VENDOR.json'
    current = json.loads(vendor_path.read_text(encoding='utf-8'))
    current['commit'] = 'f' * 40
    read_text = Path.read_text

    def changed_main(path, *args, **kwargs):
        return json.dumps(current) if path == vendor_path else read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', changed_main)
    if operation == 'verify':
        assert verify_release(api, evidence['tag'], evidence, tmp_path / 'download')['provenance']
    else:
        assert publish_release(api, evidence, assets, prerelease=False)['reused'] is True


@pytest.mark.parametrize('source_vendor', [b'not JSON', b'{}',
    b'{"commit": "different", "files": {}}'])
def test_verification_rejects_vendor_pin_different_from_release_source(tmp_path, source_vendor):
    api, evidence, _assets = published(tmp_path / 'assets')
    api.source_vendor = source_vendor
    with pytest.raises(ReleasePolicyError, match='vendor'):
        verify_release(api, evidence['tag'], evidence, tmp_path / 'download')


@pytest.mark.parametrize('defect', ['mutable', 'digest', 'asset_identity'])
def test_cli_metadata_loader_requires_original_immutable_asset(tmp_path, defect):
    from release_cli import _remote_evidence

    api, evidence, _assets = published(tmp_path / 'assets')
    release = api.releases[0]
    asset = next(item for item in release['assets'] if item['name'] == 'release-metadata.json')
    if defect == 'mutable':
        release['immutable'] = False
    elif defect == 'digest':
        asset['digest'] = 'sha256:' + 'f' * 64
    else:
        previous = asset['url']
        asset['url'] = 'https://api.github.com/repos/other/repo/releases/assets/1'
        api.blobs[asset['url']] = api.blobs[previous]
    destination = tmp_path / 'download'
    destination.mkdir()
    with pytest.raises(ReleasePolicyError):
        _remote_evidence(api, evidence['repository'], evidence['tag'], destination)


def published(tmp_path):
    api = FakeAPI()
    evidence, assets = release_assets(tmp_path, tag='v0.2.2')
    release = dict(id=10, tag_name='v0.2.2', draft=False, prerelease=False, immutable=True,
                   body='Ready.\n', assets=[])
    api.releases.append(release)
    for name, path in assets.items():
        api.upload_asset('https://uploads.github.com/repos/x/y/releases/10/assets', name, path)
    api.tags['v0.2.2'] = SHA
    candidate(api, evidence['zip_sha256'])
    return api, evidence, assets


@pytest.mark.parametrize('defect', ['missing_tag', 'wrong_version', 'draft', 'stable', 'mutable',
                                  'source', 'digest', 'missing_zip', 'duplicate_zip'])
def test_stable_verification_requires_matching_historical_candidate(tmp_path, defect):
    api, evidence, _assets = published(tmp_path / 'assets')
    historical = api.releases[1]
    if defect == 'missing_tag':
        evidence['candidate_tag'] = None
    elif defect == 'wrong_version':
        evidence['candidate_tag'] = 'v0.2.3-rc.1'
    elif defect == 'source':
        api.tags['v0.2.2-rc.1'] = 'b' * 40
    elif defect == 'digest':
        historical['assets'][0]['digest'] = 'sha256:' + 'f' * 64
    elif defect == 'missing_zip':
        historical['assets'] = []
    elif defect == 'duplicate_zip':
        historical['assets'] *= 2
    else:
        historical[{'draft': 'draft', 'stable': 'prerelease', 'mutable': 'immutable'}[defect]] = defect == 'draft'
    with pytest.raises(ReleasePolicyError, match='candidate'):
        verify_release(api, 'v0.2.2', evidence, tmp_path / 'download')


def test_historical_candidate_verification_does_not_require_release_branch(tmp_path):
    api, evidence, _assets = published(tmp_path / 'assets')
    request = api.request

    def without_branch(method, path, payload=None):
        if '/git/ref/heads/' in path:
            raise GitHubAPIError('release branch was deleted', status=404)
        return request(method, path, payload)

    api.request = without_branch
    assert verify_release(api, 'v0.2.2', evidence, tmp_path / 'download')['provenance'] is True


def test_verification_rejects_unexpected_remote_asset(tmp_path):
    api, evidence, _assets = published(tmp_path / 'assets')
    extra = tmp_path / 'extra.txt'
    extra.write_bytes(b'unverified')
    api.upload_asset('https://uploads.github.com/repos/x/y/releases/10/assets', extra.name, extra)
    destination = tmp_path / 'download'
    with pytest.raises(ReleasePolicyError, match='unexpected.*asset'):
        verify_release(api, evidence['tag'], evidence, destination)
    assert not destination.exists()


def test_verification_downloads_remote_bytes_and_does_not_invent_runtime_success(tmp_path):
    api, evidence, assets = published(tmp_path / 'assets')
    dest = tmp_path / 'download'
    result = verify_release(api, 'v0.2.2', evidence, dest)
    assert result['repository'] == evidence['repository']
    assert result['version'] == '0.2.2'
    assert result['source_sha'] == result['build_sha'] == SHA
    assert result['zip_sha256'] == evidence['zip_sha256']
    assert result['provenance'] is True
    assert result['packaging_verified'] is True
    assert result['catalog_verified'] is True
    assert result['checksums_verified'] is True
    assert result['install_verified'] is False
    assert result['commands_verified'] is False
    assert (dest / 'usage-bridge-v0.2.2.zip').read_bytes() == assets['usage-bridge-v0.2.2.zip'].read_bytes()


@pytest.mark.parametrize('defect', ['zip', 'catalog', 'metadata', 'checksums', 'provenance', 'mutable', 'tag'])
def test_verification_rejects_tampered_remote_release(tmp_path, defect):
    api, evidence, assets = published(tmp_path / 'assets')
    names = {'zip': 'usage-bridge-v0.2.2.zip', 'catalog': 'catalog.json',
             'metadata': 'release-metadata.json', 'checksums': 'SHA256SUMS'}
    if defect in names:
        asset = next(item for item in api.releases[0]['assets'] if item['name'] == names[defect])
        api.blobs[asset['url']] = b'tampered'
    elif defect == 'provenance':
        api.provenance = False
    elif defect == 'mutable':
        api.releases[0]['immutable'] = False
    else:
        api.tags['v0.2.2'] = 'b' * 40
    with pytest.raises((ReleasePolicyError, GitHubAPIError)):
        verify_release(api, 'v0.2.2', evidence, tmp_path / 'download')


def test_verification_binds_isolated_runtime_results_to_downloaded_digest(tmp_path):
    api, evidence, assets = published(tmp_path / 'assets')
    result = verify_release(api, 'v0.2.2', evidence, tmp_path / 'download',
        runtime_verifier=lambda archive, source_sha, checksum: runtime_records(source_sha, checksum))
    assert result['install_verified'] is True
    assert result['commands_verified'] is True
    assert len(result['runtime']) == 4
    with pytest.raises(ReleasePolicyError):
        verify_release(api, 'v0.2.2', evidence, tmp_path / 'other',
            runtime_verifier=lambda archive, source_sha, checksum: runtime_records(source_sha, 'f' * 64))


def test_unknown_schema_is_rejected_before_network(tmp_path):
    with pytest.raises(ReleasePolicyError):
        verify_release(None, 'v0.2.2', {'schema_version': 2}, tmp_path)


def test_verified_record_preserves_waived_checks_and_binds_attestation_run(tmp_path):
    api, evidence, assets = published(tmp_path / 'assets')
    evidence['override'] = {'reason': 'lint failure', 'waived_checks': ['lint']}
    evidence['gate'] = {'waived': ['lint']}
    assets['release-metadata.json'].write_text(json.dumps(evidence))
    from test_release_publication import digest
    assets['SHA256SUMS'].write_text(''.join(f'{digest(path)}  {name}\n' for name, path in sorted(assets.items())
                                          if name != 'SHA256SUMS'))
    for asset in api.releases[0]['assets']:
        data = assets[asset['name']].read_bytes()
        api.blobs[asset['url']] = data
        asset['digest'] = 'sha256:' + digest(assets[asset['name']])
    bindings = []
    api.verify_attestation = lambda archive, repo, source, **kwargs: bindings.append(kwargs) or True
    result = verify_release(api, 'v0.2.2', evidence, tmp_path / 'download')
    assert result['override']['waived_checks'] == ['lint']
    assert result['gate']['waived'] == ['lint']
    assert bindings == [{'run_id': 1, 'attempt': 1}]


@pytest.mark.parametrize('defect', ['manifest', 'catalog', 'members', 'vendor', 'case_collision'])
def test_uploaded_digest_does_not_hide_invalid_content(tmp_path, defect):
    from release.artifacts import validate_release_assets
    from test_release_publication import digest

    evidence, assets = release_assets(tmp_path)
    if defect == 'catalog':
        body = json.loads(assets['catalog.json'].read_text())
        body['extensions']['usage-bridge']['download_url'] = 'https://github.com/x/y/releases/latest/download/usage-bridge.zip'
        assets['catalog.json'].write_text(json.dumps(body))
    else:
        archive = assets['usage-bridge-v0.2.2.zip']
        with zipfile.ZipFile(archive) as zipped:
            contents = {info.filename: zipped.read(info) for info in zipped.infolist()}
        if defect == 'manifest':
            contents['usage-bridge/extension.yml'] = contents['usage-bridge/extension.yml'].replace(b'0.2.2', b'9.9.9')
        elif defect == 'members':
            contents['usage-bridge/tools/publisher.py'] = b'no'
        elif defect == 'case_collision':
            contents['usage-bridge/scripts/python/usage_bridge/Config.py'] = b'bad'
            evidence['members'].append('scripts/python/usage_bridge/Config.py')
        else:
            contents['usage-bridge/scripts/python/vendor/token_usage/LICENSE'] = b'tampered'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for name, payload in contents.items():
                zipped.writestr(name, payload)
        evidence['zip_sha256'] = digest(archive)
        body = json.loads(assets['catalog.json'].read_text())
        body['extensions']['usage-bridge']['sha256'] = evidence['zip_sha256']
        assets['catalog.json'].write_text(json.dumps(body))
        assets['release-metadata.json'].write_text(json.dumps(evidence))
    assets['SHA256SUMS'].write_text(''.join(f'{digest(path)}  {name}\n' for name, path in sorted(assets.items())
                                           if name != 'SHA256SUMS'))
    with pytest.raises(ReleasePolicyError):
        validate_release_assets(assets, evidence)
