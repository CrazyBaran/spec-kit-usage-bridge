"""Idempotent release-branch preparation. Does not create tags or releases."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from github_api import GitHubAPI, GitHubAPIError
from release.policy import ReleasePolicyError, parse_version

_STABLE_TAG = re.compile(r'^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')
_BOT_NAME = 'usage-bridge-release'
_BOT_EMAIL = 'usage-bridge-release@users.noreply.github.com'


def prepare_release(api: GitHubAPI, repo: str, version: str, main_sha: str, *,
                    checkout: Path | None = None, dry_run: bool = False) -> dict:
    parse_version(version)
    branch = f'release/{version}'
    _require_newer_than_stable(api, repo, version)
    _require_only_this_train(api, repo, branch)
    existing = _branch_sha(api, repo, branch)
    if existing:
        url = None if dry_run else _ensure_draft(api, repo, branch, version)
        return {'branch': branch, 'pull_request': url, 'source_sha': existing, 'reused': True}
    if dry_run:
        return {'branch': branch, 'pull_request': None, 'source_sha': main_sha, 'reused': False}
    if checkout is None:
        raise ReleasePolicyError('a checkout is required to create a release branch')
    _require_fresh_main(api, repo, main_sha)
    if _git(checkout, 'rev-parse', 'HEAD') != main_sha:
        raise ReleasePolicyError('trusted checkout must match the fresh protected main SHA')
    if _git(checkout, 'status', '--porcelain', '--untracked-files=no'):
        raise ReleasePolicyError('trusted checkout must be clean before release preparation')
    _commit_release_tree(checkout, version, main_sha)
    source_sha = _upload_release_tree(api, repo, checkout, version, main_sha)
    _require_fresh_main(api, repo, main_sha)
    api.request('POST', f'/repos/{repo}/git/refs', {'ref': f'refs/heads/{branch}', 'sha': source_sha})
    url = _ensure_draft(api, repo, branch, version)
    return {'branch': branch, 'pull_request': url, 'source_sha': source_sha, 'reused': False}


def _require_fresh_main(api, repo: str, main_sha: str) -> None:
    if not re.fullmatch(r'[0-9a-f]{40}', main_sha):
        raise ReleasePolicyError('main SHA must be a full commit SHA')
    current = api.request('GET', f'/repos/{repo}/git/ref/heads/main')
    if (current.get('object') or {}).get('sha') != main_sha:
        raise ReleasePolicyError('requested main SHA does not match fresh protected main')


def _upload_release_tree(api, repo: str, checkout: Path, version: str, main_sha: str) -> str:
    """Create remote objects before referencing them; never updates an existing ref."""
    base = f'/repos/{repo}/git'
    parent = api.request('GET', f'{base}/commits/{main_sha}')
    tree = api.request('POST', f'{base}/trees', {
        'base_tree': parent['tree']['sha'],
        'tree': [{'path': name, 'mode': '100644', 'type': 'blob',
                  'content': (checkout / name).read_text(encoding='utf-8')}
                 for name in ('extension.yml', 'CHANGELOG.md')],
    })
    commit = api.request('POST', f'{base}/commits', {
        'message': f'chore: prepare release {version}',
        'tree': tree['sha'], 'parents': [main_sha],
        'author': {'name': _BOT_NAME, 'email': _BOT_EMAIL},
        'committer': {'name': _BOT_NAME, 'email': _BOT_EMAIL},
    })
    return str(commit['sha'])


def _require_newer_than_stable(api: GitHubAPI, repo: str, version: str) -> None:
    proposed = parse_version(version)
    for release in api.pages(f'/repos/{repo}/releases'):
        if release.get('draft') or release.get('prerelease'):
            continue
        match = _STABLE_TAG.fullmatch(str(release.get('tag_name') or ''))
        if match and proposed <= tuple(int(part) for part in match.groups()):
            raise ReleasePolicyError('version is not newer than the newest published stable')


def _require_only_this_train(api: GitHubAPI, repo: str, branch: str) -> None:
    for pull in api.pages(f'/repos/{repo}/pulls?state=open'):
        head = str((pull.get('head') or {}).get('ref') or '')
        if head.startswith('release/') and head != branch:
            raise ReleasePolicyError('another release train is open: ' + head)


def _branch_sha(api: GitHubAPI, repo: str, branch: str) -> str | None:
    try:
        body = api.request('GET', f'/repos/{repo}/git/ref/heads/{branch}')
    except GitHubAPIError as exc:
        if exc.status == 404:
            return None
        raise
    return str(body['object']['sha'])


def _ensure_draft(api: GitHubAPI, repo: str, branch: str, version: str) -> str:
    for pull in api.pages(f'/repos/{repo}/pulls?state=open'):
        if (pull.get('head') or {}).get('ref') == branch:
            return str(pull.get('html_url') or '')
    created = api.request('POST', f'/repos/{repo}/pulls', {
        'title': f'Release {version}',
        'head': branch,
        'base': 'main',
        'draft': True,
    })
    return str(created.get('html_url') or '')


def _commit_release_tree(checkout: Path, version: str, main_sha: str) -> str:
    branch = f'release/{version}'
    _git(checkout, 'checkout', '-B', branch, main_sha)
    manifest = checkout / 'extension.yml'
    text = manifest.read_text(encoding='utf-8')
    updated, count = re.subn(r'(version:\s*")[^"]+(")', rf'\g<1>{version}\2', text, count=1)
    if count != 1:
        raise ReleasePolicyError('extension.yml has no version field to update')
    manifest.write_text(updated, encoding='utf-8')
    changelog = checkout / 'CHANGELOG.md'
    notes = changelog.read_text(encoding='utf-8') if changelog.exists() else '# Changelog\n'
    heading = f'## [{version}]'
    if heading not in notes:
        if notes.startswith('# '):
            first, _, rest = notes.partition('\n')
            notes = f'{first}\n\n{heading}\n\n{rest.lstrip()}'
        else:
            notes = f'{heading}\n\n{notes}'
        changelog.write_text(notes, encoding='utf-8')
    _git(checkout, 'add', 'extension.yml', 'CHANGELOG.md')
    env = dict(os.environ)
    env.update(GIT_AUTHOR_NAME=_BOT_NAME, GIT_AUTHOR_EMAIL=_BOT_EMAIL,
               GIT_COMMITTER_NAME=_BOT_NAME, GIT_COMMITTER_EMAIL=_BOT_EMAIL)
    _git(checkout, 'commit', '-m', f'chore: prepare release {version}', env=env)
    return _git(checkout, 'rev-parse', 'HEAD').strip()


def _git(checkout: Path, *args: str, env: dict | None = None) -> str:
    result = subprocess.run(['git', *args], cwd=checkout, check=True, capture_output=True, text=True, env=env)
    return result.stdout.strip()
