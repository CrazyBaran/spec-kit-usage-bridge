"""Idempotent draft-then-publish release assets. Never replaces an uploaded asset."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from release.policy import ReleasePolicyError, parse_version, require_metadata


def _section(changelog: str, version: str) -> str:
    match = re.search(r'^##\s+\[' + re.escape(version) + r'\][^\n]*\n', changelog, re.M)
    if not match:
        raise ReleasePolicyError('changelog has no section for ' + version)
    tail = changelog[match.end():]
    return re.split(r'^##\s', tail, maxsplit=1, flags=re.M)[0].strip() + '\n'


def _make_latest(api, evidence: dict, prerelease: bool) -> str:
    if prerelease:
        return 'false'
    proposed = parse_version(evidence['version'])
    for release in api.pages(f"/repos/{evidence['repository']}/releases"):
        if release.get('draft') or release.get('prerelease'):
            continue
        tag = str(release.get('tag_name') or '')
        if not tag.startswith('v') or '-' in tag[1:]:
            continue
        try:
            published = parse_version(tag[1:])
        except ReleasePolicyError:
            continue
        if published >= proposed:
            return 'false'
    return 'true'


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish_release(api, evidence: dict, assets: dict[str, Path], prerelease: bool) -> dict:
    require_metadata(evidence)
    notes = _section(str(evidence.get('changelog') or ''), evidence['version'])
    repository = evidence['repository']
    existing = next((item for item in api.pages(f'/repos/{repository}/releases')
                     if item.get('tag_name') == evidence['tag']), None)
    if existing is None:
        existing = api.request('POST', f'/repos/{repository}/releases', {
            'tag_name': evidence['tag'],
            'target_commitish': evidence['source_sha'],
            'name': evidence['tag'],
            'body': notes,
            'draft': True,
            'prerelease': prerelease,
            'make_latest': _make_latest(api, evidence, prerelease),
        })
    elif existing.get('body') not in (None, '', notes) and existing.get('body') != notes:
        raise ReleasePolicyError('existing release notes do not match the changelog section')
    present = {asset['name']: asset.get('sha256') for asset in existing.get('assets') or []}
    for name, path in sorted(assets.items()):
        digest = _digest(path)
        if name in present:
            if present[name] != digest:
                raise ReleasePolicyError('refusing to replace asset ' + name)
            continue
        uploaded = api.request('POST', f"/repos/{repository}/releases/{existing['id']}/assets",
                               {'name': name, 'sha256': digest})
        present[name] = uploaded['sha256']
        existing.setdefault('assets', []).append(uploaded)
    if existing.get('draft', True):
        existing = api.request('PATCH', f"/repos/{repository}/releases/{existing['id']}",
                               {'draft': False, 'prerelease': prerelease})
    return {'release_id': existing['id'], 'tag': evidence['tag']}
