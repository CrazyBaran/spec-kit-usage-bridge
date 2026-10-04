"""Verify a published release from downloaded bytes and recorded provenance."""
from __future__ import annotations

import hashlib
from pathlib import Path

from release.policy import ReleasePolicyError, require_metadata


def verify_release(api, tag: str, expected: dict, download_dir: Path, *, downloader=None) -> dict:
    require_metadata(expected)
    if expected.get('tag') != tag:
        raise ReleasePolicyError('verification tag does not match the expected release')
    verification = expected.get('verification') or {}
    if verification.get('provenance') is not True or verification.get('build_sha') != expected.get('source_sha'):
        raise ReleasePolicyError('release is missing provenance for its source SHA')
    if downloader is None:
        raise ReleasePolicyError('a downloader is required to verify published bytes')
    dest = Path(download_dir) / f"usage-bridge-v{expected['version']}.zip"
    url = (f"https://github.com/{expected['repository']}/releases/download/{tag}/"
           f"usage-bridge-v{expected['version']}.zip")
    downloader(url, dest)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if digest != expected['zip_sha256']:
        raise ReleasePolicyError('downloaded archive digest does not match release evidence')
    return {'tag': tag, 'sha256': digest, 'source_sha': expected['source_sha']}
