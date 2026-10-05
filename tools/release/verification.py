"""Verify a published release from downloaded bytes and recorded provenance."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from release.artifacts import release_asset_names, release_vendor, validate_release_assets
from release.context import resolve_tag_sha
from release.policy import ReleasePolicyError, require_candidate, require_metadata, require_runtime


def published_metadata(api, repository: str, tag: str, download_dir: Path) -> dict:
    """Read the original metadata asset of an immutable release for retry/detection."""
    release = api.request('GET', f'/repos/{repository}/releases/tags/{tag}')
    if release.get('draft') is not False or release.get('immutable') is not True:
        raise ReleasePolicyError('metadata must come from an immutable published release')
    matches = [asset for asset in release.get('assets') or [] if asset.get('name') == 'release-metadata.json']
    if len(matches) != 1:
        raise ReleasePolicyError('published release must contain one original metadata asset')
    asset = matches[0]
    url = f"https://api.github.com/repos/{repository}/releases/assets/{asset.get('id')}"
    if asset.get('url') != url:
        raise ReleasePolicyError('metadata asset URL does not match the repository and asset identity')
    dest = Path(download_dir) / 'release-metadata.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        raise ReleasePolicyError('metadata destination must not be a symlink')
    api.download_asset(url, dest)
    if asset.get('digest') != 'sha256:' + hashlib.sha256(dest.read_bytes()).hexdigest():
        raise ReleasePolicyError('published metadata digest does not match downloaded bytes')
    try:
        metadata = json.loads(dest.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        raise ReleasePolicyError('published metadata is not valid JSON') from None
    require_metadata(metadata)
    if metadata['repository'] != repository or metadata['tag'] != tag:
        raise ReleasePolicyError('published metadata belongs to a different release')
    return metadata


def verify_release(api, tag: str, expected: dict, download_dir: Path, *, downloader=None,
                   runtime_verifier=None) -> dict:
    require_metadata(expected)
    if expected.get('tag') != tag:
        raise ReleasePolicyError('verification tag does not match the expected release')
    repository = expected['repository']
    release = api.request('GET', f'/repos/{repository}/releases/tags/{tag}')
    if (release.get('tag_name') != tag or release.get('draft') is not False
            or release.get('prerelease') is not ('-rc.' in tag) or release.get('immutable') is not True):
        raise ReleasePolicyError('verification requires the immutable published release for this tag')
    if resolve_tag_sha(api, repository, tag) != expected['source_sha']:
        raise ReleasePolicyError('published release tag differs from the expected source commit')
    if '-rc.' not in tag:
        candidate_tag = expected.get('candidate_tag')
        if not re.fullmatch(re.escape(f"v{expected['version']}-rc.") + r'[1-9]\d*', str(candidate_tag or '')):
            raise ReleasePolicyError('stable verification requires a candidate tag for this version')
        candidate = api.request('GET', f'/repos/{repository}/releases/tags/{candidate_tag}')
        if candidate.get('tag_name') != candidate_tag or candidate.get('immutable') is not True:
            raise ReleasePolicyError('stable verification requires the immutable historical candidate')
        require_candidate(expected['version'], expected['source_sha'], {
            'version': expected['version'], 'tag': candidate_tag,
            'sha': resolve_tag_sha(api, repository, candidate_tag),
            'draft': candidate.get('draft'), 'prerelease': candidate.get('prerelease'),
        })
        candidate_zips = [asset for asset in candidate.get('assets') or []
                          if asset.get('name') == f"usage-bridge-v{expected['version']}.zip"]
        if len(candidate_zips) != 1 or candidate_zips[0].get('digest') != 'sha256:' + expected['zip_sha256']:
            raise ReleasePolicyError('historical candidate ZIP must match the stable release digest')
    assets_by_name = {}
    for asset in release.get('assets') or []:
        name = asset.get('name')
        if name in assets_by_name:
            raise ReleasePolicyError('published release contains duplicate assets')
        assets_by_name[name] = asset
    if set(assets_by_name) - set(release_asset_names(expected['version'])):
        raise ReleasePolicyError('published release contains unexpected assets')
    download_dir = Path(download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)
    downloaded = {}
    download = downloader or api.download_asset
    for name in release_asset_names(expected['version']):
        asset = assets_by_name.get(name)
        if asset is None:
            raise ReleasePolicyError('published release is missing asset: ' + name)
        url = f"https://api.github.com/repos/{repository}/releases/assets/{asset.get('id')}"
        if asset.get('url') != url:
            raise ReleasePolicyError('release asset URL does not match this repository and asset identity')
        dest = download_dir / name
        if dest.is_symlink():
            raise ReleasePolicyError('download destination must not be a symlink')
        download(url, dest)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if asset.get('digest') != 'sha256:' + digest:
            raise ReleasePolicyError('downloaded asset digest differs from the immutable release: ' + name)
        downloaded[name] = dest
    validated = validate_release_assets(downloaded, expected, vendor_manifest=release_vendor(api, expected))
    archive = downloaded[f"usage-bridge-v{expected['version']}.zip"]
    if api.verify_attestation(archive, repository, expected['source_sha'],
                              run_id=expected['run_id'], attempt=expected['attempt']) is not True:
        raise ReleasePolicyError('release archive provenance could not be verified')
    runtime = []
    if runtime_verifier is not None:
        runtime = runtime_verifier(archive, expected['source_sha'], expected['zip_sha256'])
        require_runtime(runtime, expected['source_sha'], expected['zip_sha256'])
    return {
        'schema_version': 1, 'repository': repository, 'version': expected['version'],
        'tag': tag, 'source_sha': expected['source_sha'], 'build_sha': expected['source_sha'],
        'zip_sha256': expected['zip_sha256'], 'sha256': expected['zip_sha256'],
        'run_id': expected['run_id'], 'attempt': expected['attempt'],
        'provenance': True, 'packaging_verified': True, 'archive_verified': True,
        'catalog_verified': True, 'checksums_verified': True,
        'install_verified': bool(runtime), 'commands_verified': bool(runtime), 'runtime': runtime,
        'manifest': validated['manifest'], 'members': list(validated['archive']['members']),
        'override': validated['metadata'].get('override'), 'gate': validated['metadata'].get('gate'),
    }
