import subprocess
from pathlib import Path

import pytest
import yaml

from github_api import GitHubAPIError
from release.policy import ReleasePolicyError
from release.prepare import prepare_release

REPO = 'CrazyBaran/spec-kit-usage-bridge'
SHA = 'a' * 40


class FakeAPI:
    def __init__(self, main_sha=SHA):
        self.main_sha = main_sha
        self.calls = []
        self.created_pull_requests = []
        self.created_releases = []
        self.created_tags = []
        self.releases = []
        self.pulls = []
        self.refs = {}
        self.fail_next_pr = False
        self.remote_objects = {}

    def request(self, method, path, payload=None):
        self.calls.append(type('Call', (), {'method': method, 'path': path, 'payload': payload})())
        if method == 'GET' and path.endswith('/git/ref/heads/main'):
            return {'object': {'type': 'commit', 'sha': self.main_sha}}
        if method == 'GET' and '/git/commits/' in path:
            return {'tree': {'sha': 'base-tree'}}
        if method == 'POST' and path.endswith('/git/trees'):
            sha = 'remote-tree'
            self.remote_objects[sha] = payload
            return {'sha': sha}
        if method == 'POST' and path.endswith('/git/commits'):
            assert payload['tree'] in self.remote_objects
            sha = 'remote-commit'
            self.remote_objects[sha] = payload
            return {'sha': sha}
        if method == 'GET' and '/git/ref/heads/release/' in path:
            name = path.rsplit('/', 1)[-1]
            if name not in self.refs:
                raise GitHubAPIError('missing ref', status=404)
            return {'object': {'sha': self.refs[name]}}
        if method == 'POST' and path.endswith('/git/refs'):
            if payload['sha'] not in self.remote_objects:
                raise GitHubAPIError('Git object does not exist remotely', status=422)
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
    root = Path(__file__).resolve().parents[1]
    (repo / 'extension.yml').write_bytes((root / 'extension.yml').read_bytes())
    package = repo / 'scripts/python/usage_bridge/__init__.py'
    package.parent.mkdir(parents=True)
    package.write_bytes((root / 'scripts/python/usage_bridge/__init__.py').read_bytes())
    (repo / 'CHANGELOG.md').write_text('# Changelog\n\n## [0.2.1]\n\nPrior.\n', encoding='utf-8')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-m', 'base')
    return repo


def test_prepare_never_publishes_release(tmp_path):
    checkout = _checkout(tmp_path)
    sha = _git(checkout, 'rev-parse', 'HEAD')
    api = FakeAPI(sha)
    result = prepare_release(api, REPO, '0.2.2', sha,
                             checkout=tmp_path / 'src')
    assert result['branch'] == 'release/0.2.2'
    assert api.created_pull_requests[0]['draft'] is True
    assert api.created_pull_requests[0]['base'] == 'main'
    assert api.created_releases == []
    assert api.created_tags == []
    text = (tmp_path / 'src' / 'extension.yml').read_text(encoding='utf-8')
    assert '0.2.2' in text
    assert '## [0.2.2]' in (tmp_path / 'src' / 'CHANGELOG.md').read_text(encoding='utf-8')
    assert result['source_sha'] == 'remote-commit'
    assert api.remote_objects['remote-commit']['parents'] == [
        _git(tmp_path / 'src', 'rev-parse', 'main')]
    assert {entry['path'] for entry in api.remote_objects['remote-tree']['tree']} == {
        'extension.yml', 'CHANGELOG.md', 'scripts/python/usage_bridge/__init__.py'}


def test_prepare_retry_reuses_branch_and_recovers_pr(tmp_path):
    checkout = _checkout(tmp_path)
    sha = _git(checkout, 'rev-parse', 'HEAD')
    api = FakeAPI(sha)
    api.fail_next_pr = True
    with pytest.raises(GitHubAPIError):
        prepare_release(api, REPO, '0.2.2', sha, checkout=checkout)
    first_commit = api.refs['0.2.2']
    again = prepare_release(api, REPO, '0.2.2', sha, checkout=checkout)
    assert again['reused'] is True
    assert api.refs['0.2.2'] == first_commit
    assert len(api.created_pull_requests) == 1


def test_prepare_updates_release_versions_without_changing_schema(tmp_path):
    checkout = _checkout(tmp_path)
    sha = _git(checkout, 'rev-parse', 'HEAD')
    api = FakeAPI(sha)
    prepare_release(api, REPO, '0.2.2', sha, checkout=checkout)
    manifest = yaml.safe_load((checkout / 'extension.yml').read_text(encoding='utf-8'))
    assert manifest['schema_version'] == '1.0'
    assert manifest['extension']['version'] == '0.2.2'
    namespace = {}
    package_path = 'scripts/python/usage_bridge/__init__.py'
    exec((checkout / package_path).read_text(encoding='utf-8'), namespace)
    assert namespace['__version__'] == '0.2.2'
    remote = {entry['path']: entry['content'] for entry in api.remote_objects['remote-tree']['tree']}
    assert yaml.safe_load(remote['extension.yml'])['extension']['version'] == '0.2.2'
    assert remote[package_path] == (checkout / package_path).read_text(encoding='utf-8')


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
    api = FakeAPI(sha)
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


def test_prepare_rejects_a_source_other_than_fresh_remote_main(tmp_path):
    checkout = _checkout(tmp_path)
    main = _git(checkout, 'rev-parse', 'HEAD')
    _git(checkout, 'checkout', '-b', 'untrusted')
    (checkout / 'extension.yml').write_text('extension:\n  version: "9.9.9"\n', encoding='utf-8')
    _git(checkout, 'commit', '-am', 'untrusted source')
    untrusted = _git(checkout, 'rev-parse', 'HEAD')
    _git(checkout, 'checkout', 'main')
    api = FakeAPI(main)
    with pytest.raises(ReleasePolicyError, match='main'):
        prepare_release(api, REPO, '0.2.2', untrusted, checkout=checkout)
    assert _git(checkout, 'rev-parse', 'HEAD') == main
    assert not any(call.method != 'GET' for call in api.calls)


def test_prepare_rejects_checkout_other_than_fresh_main(tmp_path):
    checkout = _checkout(tmp_path)
    main = _git(checkout, 'rev-parse', 'HEAD')
    _git(checkout, 'checkout', '-b', 'other')
    (checkout / 'extra').write_text('unrelated')
    _git(checkout, 'add', 'extra')
    _git(checkout, 'commit', '-m', 'other checkout')
    other = _git(checkout, 'rev-parse', 'HEAD')
    api = FakeAPI(main)
    with pytest.raises(ReleasePolicyError, match='checkout'):
        prepare_release(api, REPO, '0.2.2', main, checkout=checkout)
    assert _git(checkout, 'rev-parse', 'HEAD') == other
    assert not any(call.method != 'GET' for call in api.calls)


def test_prepare_rejects_staged_changes_before_mutating_checkout(tmp_path):
    checkout = _checkout(tmp_path)
    main = _git(checkout, 'rev-parse', 'HEAD')
    (checkout / 'extra').write_text('human work')
    _git(checkout, 'add', 'extra')
    api = FakeAPI(main)
    with pytest.raises(ReleasePolicyError, match='clean'):
        prepare_release(api, REPO, '0.2.2', main, checkout=checkout)
    assert _git(checkout, 'rev-parse', 'HEAD') == main
    assert _git(checkout, 'status', '--porcelain') == 'A  extra'
