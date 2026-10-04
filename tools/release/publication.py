"""Idempotent draft-then-publish release assets. Never replaces an uploaded asset."""
from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from release.artifacts import validate_release_assets
from release.context import decide_gate, promotion_context, release_branch_sha, resolve_tag_sha
from release.policy import (
    WAIVABLE_CHECKS,
    ReleasePolicyError,
    parse_version,
    require_metadata,
    require_runtime,
    require_verification,
)


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


def _recheck_source(api, evidence: dict, prerelease: bool) -> None:
    if release_branch_sha(api, evidence['repository'], evidence['version']) != evidence['source_sha']:
        raise ReleasePolicyError('release branch moved after validation')
    if not prerelease:
        promotion_context(api, evidence['repository'], evidence['version'],
                          evidence['candidate_tag'], evidence['source_sha'])


def _validate_publication(api, evidence: dict, assets: dict, prerelease: bool) -> None:
    # Collection is imported lazily to keep the pure policy/artifact layers independent.
    from release.orchestration import collect_run_evidence

    require_metadata(evidence)
    if prerelease != ('-rc.' in evidence['tag']):
        raise ReleasePolicyError('release tag and prerelease status disagree')
    validate_release_assets(assets, evidence)
    require_verification(evidence.get('verification'), evidence)
    original_gate = decide_gate(dict(evidence, digest=evidence['zip_sha256'], required=WAIVABLE_CHECKS))
    if not original_gate['allowed']:
        raise ReleasePolicyError('recorded quality checks are incomplete: ' + '; '.join(original_gate['blockers']))
    override = evidence.get('override') or {}
    refreshed = collect_run_evidence(api, evidence['repository'], evidence['source_sha'], evidence['run_id'],
                                    evidence['attempt'], evidence['zip_sha256'],
                                    override_reason=str(override.get('reason') or ''),
                                    waived_checks=override.get('waived_checks') or ())
    decision = decide_gate(refreshed)
    if not decision['allowed']:
        raise ReleasePolicyError('current quality checks are incomplete: ' + '; '.join(decision['blockers']))
    require_runtime(refreshed.get('runtime'), evidence['source_sha'], evidence['zip_sha256'],
                    run_id=evidence['run_id'], attempt=evidence['attempt'])
    archive = assets[f"usage-bridge-v{evidence['version']}.zip"]
    if api.verify_attestation(archive, evidence['repository'], evidence['source_sha'],
                              run_id=evidence['run_id'], attempt=evidence['attempt']) is not True:
        raise ReleasePolicyError('release archive provenance could not be verified')
    immutable = api.request('GET', f"/repos/{evidence['repository']}/immutable-releases")
    if not isinstance(immutable, dict) or immutable.get('enabled') is not True:
        raise ReleasePolicyError('repository release immutability must be enabled before publication')
    _recheck_source(api, evidence, prerelease)
    if not prerelease:
        candidate = next((item for item in api.pages(f"/repos/{evidence['repository']}/releases")
                          if item.get('tag_name') == evidence['candidate_tag']), None)
        if candidate is None or candidate.get('immutable') is not True:
            raise ReleasePolicyError('stable promotion requires an immutable published candidate')
        archives = [asset for asset in candidate.get('assets') or [] if asset.get('name') == archive.name]
        if len(archives) != 1 or archives[0].get('digest') != 'sha256:' + evidence['zip_sha256']:
            raise ReleasePolicyError('stable ZIP bytes must match the immutable candidate archive')


def publish_release(api, evidence: dict, assets: dict[str, Path], prerelease: bool) -> dict:
    _validate_publication(api, evidence, assets, prerelease)
    notes = _section(str(evidence.get('changelog') or ''), evidence['version'])
    repository = evidence['repository']
    existing = next((item for item in api.pages(f'/repos/{repository}/releases')
                     if item.get('tag_name') == evidence['tag']), None)
    tag_sha = resolve_tag_sha(api, repository, evidence['tag'], missing_ok=True)
    if tag_sha is not None and tag_sha != evidence['source_sha']:
        raise ReleasePolicyError('existing release tag points to a different source commit')
    if tag_sha is None:
        if existing is not None and existing.get('draft') is False:
            raise ReleasePolicyError('published release is missing its immutable tag')
        _recheck_source(api, evidence, prerelease)
        api.request('POST', f'/repos/{repository}/git/refs',
                    {'ref': 'refs/tags/' + evidence['tag'], 'sha': evidence['source_sha']})
        if resolve_tag_sha(api, repository, evidence['tag']) != evidence['source_sha']:
            raise ReleasePolicyError('new release tag does not resolve to the validated source')
    if existing is None:
        _recheck_source(api, evidence, prerelease)
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
    if existing.get('prerelease') is not prerelease:
        raise ReleasePolicyError('existing release has a different prerelease status')
    if existing.get('draft') is False:
        from release.verification import published_metadata, verify_release

        with tempfile.TemporaryDirectory(prefix='usage-bridge-release-retry-') as temporary:
            original = published_metadata(api, repository, evidence['tag'], Path(temporary))
            for name in ('repository', 'version', 'tag', 'source_sha', 'zip_sha256'):
                if original[name] != evidence[name]:
                    raise ReleasePolicyError('existing immutable release differs from retry ' + name)
            verify_release(api, evidence['tag'], original, Path(temporary) / 'verified')
        _recheck_source(api, evidence, prerelease)
        return {'release_id': existing['id'], 'tag': evidence['tag'], 'reused': True, 'evidence': original}
    present = {}
    for asset in existing.get('assets') or []:
        if asset['name'] in present:
            raise ReleasePolicyError('existing release contains duplicate asset names')
        present[asset['name']] = asset.get('digest')
    for name, path in sorted(assets.items()):
        digest = 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
        if name in present:
            if present[name] != digest:
                raise ReleasePolicyError('refusing to replace draft asset ' + name
                                         + '; retry with the original evidence bundle or a new release version')
            continue
        if existing.get('draft') is not True:
            raise ReleasePolicyError('published assets are immutable; refusing to add a missing asset')
        _recheck_source(api, evidence, prerelease)
        uploaded = api.upload_asset(existing['upload_url'], name, path)
        if uploaded.get('name') != name or uploaded.get('digest') != digest:
            raise ReleasePolicyError('uploaded asset digest does not match local bytes: ' + name)
        present[name] = uploaded['digest']
    if existing.get('draft', True):
        _recheck_source(api, evidence, prerelease)
        existing = api.request('PATCH', f"/repos/{repository}/releases/{existing['id']}",
                               {'draft': False, 'prerelease': prerelease,
                                'make_latest': _make_latest(api, evidence, prerelease)})
    if existing.get('immutable') is not True:
        raise ReleasePolicyError('published release is not immutable')
    return {'release_id': existing['id'], 'tag': evidence['tag']}
