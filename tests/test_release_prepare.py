import subprocess
from pathlib import Path

import pytest

from github_api import GitHubAPIError
from release.policy import ReleasePolicyError
from release.prepare import prepare_release

REPO = 'CrazyBaran/spec-kit-usage-bridge'
SHA = 'a' * 40


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.created_pull_requests = []
        self.created_releases = []
        self.created_tags = []
        self.releases = []
        self.pulls = []
        self.refs = {}
        self.fail_next_pr = False

    def request(self, method, path, payload=None):
        self.calls.append(type('Call', (), {'method': method, 'path': path, 'payload': payload})())
        if method == 'GET' and '/git/ref/heads/release/' in path:
            name = path.rsplit('/', 1)[-1]
            if name not in self.refs:
                raise GitHubAPIError('missing ref', status=404)
            return {'object': {'sha': self.refs[name]}}
        if method == 'POST' and path.endswith('/git/refs'):
            ref = payload['ref'].rsplit('/', 1)[-1]
            if ref in self.refs:
                raise GitHubAPIError('ref exists', status=422)
            self.refs[ref] = payload['sha']
            return {'ref': payload['ref'], 'object': {'sha': payload['sha']}}
        if method == 'POST' and path.endswith('/pulls'):
            if self.fail_next_pr:
                self.fail_next_pr = False
                raise GitHubAPIError('temporary', status=503)
            self.created_pull_requests.append(payload)
            number = len(self.created_pull_requests)
            pull = {'number': number, 'draft': payload['draft'], 'html_url': f'https://example.test/pull/{number}',
                    'head': {'ref': payload['head'], 'sha': self.refs.get(payload['head'], '')},
                    'base': {'ref': payload['base']}}
            self.pulls.append(pull)
            return pull
        if method == 'POST' and path.endswith('/releases'):
            self.created_releases.append(payload)
            return payload
        if method == 'POST' and '/git/refs/tags/' in path:
            self.created_tags.append(payload)
            return payload
        raise GitHubAPIError('unexpected ' + method + ' ' + path, status=500)

    def pages(self, path):
        if path.endswith('/releases'):
            return list(self.releases)
        if '/pulls' in path:
            return list(self.pulls)
        return []


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _checkout(tmp_path: Path) -> Path:
    repo = tmp_path / 'src'
    repo.mkdir()
    _git(repo, 'init', '-b', 'main')
    _git(repo, 'config', 'user.email', 'dev@example.test')
    _git(repo, 'config', 'user.name', 'Dev')
    (repo / 'extension.yml').write_text('extension:\n  id: usage-bridge\n  version: "0.2.1"\n', encoding='utf-8')
    (repo / 'CHANGELOG.md').write_text('# Changelog\n\n## [0.2.1]\n\nPrior.\n', encoding='utf-8')
    _git(repo, 'add', 'extension.yml', 'CHANGELOG.md')
    _git(repo, 'commit', '-m', 'base')
    return repo


def test_prepare_never_publishes_release(tmp_path):
    api = FakeAPI()
    result = prepare_release(api, REPO, '0.2.2', _git(_checkout(tmp_path), 'rev-parse', 'HEAD'),
                             checkout=tmp_path / 'src')
    assert result['branch'] == 'release/0.2.2'
    assert api.created_pull_requests[0]['draft'] is True
    assert api.created_pull_requests[0]['base'] == 'main'
    assert api.created_releases == []
    assert api.created_tags == []
    text = (tmp_path / 'src' / 'extension.yml').read_text(encoding='utf-8')
    assert '0.2.2' in text
    assert '## [0.2.2]' in (tmp_path / 'src' / 'CHANGELOG.md').read_text(encoding='utf-8')


def test_prepare_retry_reuses_branch_and_recovers_pr(tmp_path):
    checkout = _checkout(tmp_path)
    sha = _git(checkout, 'rev-parse', 'HEAD')
    api = FakeAPI()
    api.fail_next_pr = True
    with pytest.raises(GitHubAPIError):
        prepare_release(api, REPO, '0.2.2', sha, checkout=checkout)
    first_commit = api.refs['0.2.2']
    again = prepare_release(api, REPO, '0.2.2', sha, checkout=checkout)
    assert again['reused'] is True
    assert api.refs['0.2.2'] == first_commit
    assert len(api.created_pull_requests) == 1


def test_prepare_blocks_other_open_train(tmp_path):
    api = FakeAPI()
    api.pulls.append({'head': {'ref': 'release/0.2.3'}, 'draft': True})
    with pytest.raises(ReleasePolicyError):
        prepare_release(api, REPO, '0.2.2', SHA, checkout=_checkout(tmp_path))


def test_prepare_blocks_older_than_published_stable(tmp_path):
    api = FakeAPI()
    api.releases.append({'tag_name': 'v0.3.0', 'draft': False, 'prerelease': False})
    with pytest.raises(ReleasePolicyError):
        prepare_release(api, REPO, '0.2.2', SHA, checkout=_checkout(tmp_path))


def test_prepare_does_not_overwrite_maintainer_fixes(tmp_path):
    checkout = _checkout(tmp_path)
    sha = _git(checkout, 'rev-parse', 'HEAD')
    api = FakeAPI()
    prepare_release(api, REPO, '0.2.2', sha, checkout=checkout)
    _git(checkout, 'checkout', 'release/0.2.2')
    (checkout / 'extension.yml').write_text('extension:\n  id: usage-bridge\n  version: "0.2.2"\n# maintainer\n',
                                            encoding='utf-8')
    _git(checkout, 'add', 'extension.yml')
    _git(checkout, 'commit', '-m', 'maintainer fix')
    fixed = _git(checkout, 'rev-parse', 'HEAD')
    api.refs['0.2.2'] = fixed
    _git(checkout, 'checkout', 'main')
    again = prepare_release(api, REPO, '0.2.2', sha, checkout=checkout)
    assert again['reused'] is True
    assert api.refs['0.2.2'] == fixed
    _git(checkout, 'checkout', 'release/0.2.2')
    assert '# maintainer' in (checkout / 'extension.yml').read_text(encoding='utf-8')
