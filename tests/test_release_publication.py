from pathlib import Path

import pytest

from github_api import GitHubAPIError
from release.policy import ReleasePolicyError
from release.publication import publish_release

SHA = 'a' * 40


class FakeAPI:
    def __init__(self):
        self.created_releases = []
        self.replaced_assets = []
        self.uploads = []
        self.releases = []
        self._next = 1

    def request(self, method, path, payload=None):
        if method == 'GET' and path.endswith('/releases'):
            return list(self.releases)
        if method == 'POST' and path.endswith('/releases'):
            release = {'id': self._next, 'tag_name': payload['tag_name'], 'draft': payload.get('draft', True),
                       'prerelease': payload['prerelease'], 'make_latest': payload['make_latest'],
                       'body': payload.get('body', ''), 'assets': []}
            self._next += 1
            self.created_releases.append(release)
            self.releases.append(release)
            return release
        if method == 'POST' and '/assets' in path and payload and payload.get('replace'):
            self.replaced_assets.append(payload)
            raise GitHubAPIError('replacement is forbidden', status=422)
        if method == 'POST' and '/assets' in path:
            release_id = int(path.split('/releases/')[1].split('/')[0])
            asset = {'id': self._next, 'name': payload['name'], 'sha256': payload['sha256']}
            self._next += 1
            self.uploads.append(asset)
            next(item for item in self.releases if item['id'] == release_id)['assets'].append(asset)
            return asset
        if method == 'PATCH' and '/releases/' in path:
            release = next(item for item in self.releases if str(item['id']) in path)
            release.update(payload)
            return release
        raise GitHubAPIError('unexpected ' + method + ' ' + path, status=500)

    def pages(self, path):
        if path.endswith('/releases'):
            return list(self.releases)
        return []


def _evidence(tag='v0.2.2-rc.1', version='0.2.2', notes='## [0.2.2]\n\nReady.\n'):
    return {
        'schema_version': 1, 'repository': 'CrazyBaran/spec-kit-usage-bridge', 'version': version,
        'tag': tag, 'source_sha': SHA, 'run_id': 1, 'attempt': 1, 'zip_sha256': 'abc',
        'candidate_tag': 'v0.2.2-rc.1', 'checks': [], 'override': None, 'verification': None,
        'changelog': notes,
    }


def _assets(tmp_path: Path) -> dict[str, Path]:
    path = tmp_path / 'usage-bridge-v0.2.2.zip'
    path.write_bytes(b'zip-bytes')
    return {'usage-bridge-v0.2.2.zip': path}


def test_publish_retry_never_replaces_asset(tmp_path):
    api = FakeAPI()
    evidence = _evidence()
    assets = _assets(tmp_path)
    first = publish_release(api, evidence, assets, prerelease=True)
    second = publish_release(api, evidence, assets, prerelease=True)
    assert first['release_id'] == second['release_id']
    assert api.replaced_assets == []
    assert len(api.created_releases) == 1
    assert api.created_releases[0]['prerelease'] is True
    assert api.created_releases[0]['make_latest'] == 'false'


def test_latest_only_for_newest_stable(tmp_path):
    api = FakeAPI()
    api.releases.append({'id': 9, 'tag_name': 'v0.3.0', 'draft': False, 'prerelease': False, 'assets': []})
    result = publish_release(api, _evidence(tag='v0.2.2', version='0.2.2'), _assets(tmp_path), prerelease=False)
    created = next(item for item in api.created_releases if item['id'] == result['release_id'])
    assert created['make_latest'] == 'false'


def test_stable_notes_match_changelog(tmp_path):
    api = FakeAPI()
    publish_release(api, _evidence(tag='v0.2.2', version='0.2.2'), _assets(tmp_path), prerelease=False)
    assert api.created_releases[-1]['body'] == 'Ready.\n'
    with pytest.raises(ReleasePolicyError):
        publish_release(api, _evidence(tag='v9.9.9', version='9.9.9', notes='# Changelog\n'), _assets(tmp_path),
                        prerelease=False)
