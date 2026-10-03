"""Runtime allowlist, deterministic archives, and bounded archive validation."""
from __future__ import annotations

import hashlib
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

PREFIX = 'usage-bridge/'
DEFAULT_LIMITS = {
    'max_compressed_bytes': 25 * 1024 * 1024,
    'max_expanded_bytes': 100 * 1024 * 1024,
    'max_members': 1000,
}
ENTRYPOINTS = (
    'scripts/python/capture.py',
    'scripts/python/report.py',
    'scripts/python/check.py',
    'scripts/python/checkpoint.py',
)
VENDOR_FILES = (
    'scripts/python/vendor/token_usage/VENDOR.json',
    'scripts/python/vendor/token_usage/LICENSE',
    'scripts/python/vendor/token_usage/scripts/token_usage.py',
    'scripts/python/vendor/token_usage/data/pricing.json',
)
LEGAL_FILES = (
    'extension.yml',
    'config-template.yml',
    'LICENSE',
    'THIRD_PARTY_NOTICES.md',
)
PRICING = 'scripts/python/usage_bridge/data/openai-pricing.json'
_ZIP_EPOCH = datetime(1980, 1, 1, tzinfo=timezone.utc)


class ArchiveError(ValueError):
    """A release archive failed allowlist, structure, or size checks."""


def _tracked(repo: Path) -> set[str]:
    result = subprocess.run(
        ['git', 'ls-files', '-z'], cwd=repo, check=True, capture_output=True,
    )
    return {name for name in result.stdout.decode('utf-8').split('\0') if name}


def runtime_members(repo: Path) -> tuple[str, ...]:
    """Tracked runtime files only. Untracked checkout files are never packaged."""
    tracked = _tracked(repo)
    manifest = yaml.safe_load((repo / 'extension.yml').read_text(encoding='utf-8-sig'))
    commands = tuple(item['file'] for item in manifest['provides']['commands'])
    package = tuple(
        name for name in tracked
        if name.startswith('scripts/python/usage_bridge/') and name.endswith('.py')
    )
    selected = commands + ENTRYPOINTS + package + (PRICING,) + VENDOR_FILES + LEGAL_FILES
    missing = [name for name in selected if name not in tracked]
    if missing:
        raise ArchiveError('missing tracked runtime file: ' + ', '.join(missing))
    return tuple(sorted(set(selected)))


def _commit_stamp(repo: Path) -> tuple[int, int, int, int, int, int]:
    result = subprocess.run(
        ['git', 'log', '-1', '--format=%ct'], cwd=repo, check=True, capture_output=True, text=True,
    )
    when = datetime.fromtimestamp(int(result.stdout.strip() or '0'), timezone.utc)
    if when < _ZIP_EPOCH:
        when = _ZIP_EPOCH
    second = when.second - (when.second % 2)
    return (when.year, when.month, when.day, when.hour, when.minute, second)


def write_deterministic_archive(repo: Path, members: tuple[str, ...], archive: Path) -> None:
    import zipfile

    stamp = _commit_stamp(repo)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'w') as zipped:
        for name in members:
            info = zipfile.ZipInfo(PREFIX + name, stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.extra = b''
            zipped.writestr(info, (repo / name).read_bytes())


def write_catalog(repo: Path, archive: Path, version: str, release_tag: str, base_url: str,
                  output: Path, *, latest: bool = False) -> Path:
    """Write catalog metadata. ``latest`` keeps the stable latest catalog URL.

    A concrete ``release_tag`` with ``latest=False`` pins both the catalog and
    the download URL to that tag (candidate or stable promotion).
    """
    import json

    manifest = yaml.safe_load((repo / 'extension.yml').read_text(encoding='utf-8-sig'))
    ext = manifest['extension']
    if version != ext['version']:
        raise SystemExit('Release version must match extension.yml')
    base_url = base_url.rstrip('/')
    download_tag = release_tag
    if latest:
        catalog_path = 'releases/latest/download/catalog.json'
    else:
        catalog_path = f'releases/download/{release_tag}/catalog.json'
    stamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    entry = dict(ext)
    entry.update(
        download_url=f'{base_url}/releases/download/{download_tag}/{archive.name}',
        repository=base_url,
        homepage=base_url,
        documentation=base_url + '#readme',
        changelog=base_url + '/blob/main/CHANGELOG.md',
        requires=manifest['requires'],
        provides={'commands': len(manifest['provides']['commands']), 'hooks': len(manifest['hooks'])},
        tags=manifest['tags'],
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        created_at=stamp,
        updated_at=stamp,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        'schema_version': '1.0',
        'catalog_url': f'{base_url}/{catalog_path}',
        'extensions': {ext['id']: entry},
    }, indent=2) + '\n', encoding='utf-8')
    return output


def _limits(limits: dict | None) -> dict:
    merged = dict(DEFAULT_LIMITS)
    if limits:
        merged.update(limits)
    return merged


def _relative_member(name: str) -> str:
    if '\\' in name or name.startswith('/') or (len(name) >= 2 and name[1] == ':'):
        raise ArchiveError('escaping archive member: ' + name)
    parts = name.split('/')
    if any(part in ('', '..') for part in parts):
        raise ArchiveError('escaping archive member: ' + name)
    if not name.startswith(PREFIX):
        raise ArchiveError('archive member outside usage-bridge/: ' + name)
    relative = name[len(PREFIX):]
    if not relative or relative.endswith('/'):
        raise ArchiveError('archive member outside usage-bridge/: ' + name)
    return relative


def validate_archive(path: Path, expected_members: tuple[str, ...], limits: dict | None = None) -> dict:
    """Validate central-directory metadata. Does not extract or read member bytes."""
    import zipfile

    bounds = _limits(limits)
    compressed = path.stat().st_size
    if compressed > bounds['max_compressed_bytes']:
        raise ArchiveError(f'archive exceeds compressed limit: {compressed}')
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > bounds['max_members']:
            raise ArchiveError(f'archive exceeds member limit: {len(infos)}')
        expanded = sum(info.file_size for info in infos)
        if expanded > bounds['max_expanded_bytes']:
            raise ArchiveError(f'archive exceeds expanded limit: {expanded}')
        if sum(info.compress_size for info in infos) > bounds['max_compressed_bytes']:
            raise ArchiveError('archive exceeds compressed member limit')
        relatives: list[str] = []
        seen: set[str] = set()
        for info in infos:
            if info.flag_bits & 0x1:
                raise ArchiveError('encrypted archive member: ' + info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ArchiveError('symlink archive member: ' + info.filename)
            relative = _relative_member(info.filename)
            if relative in seen:
                raise ArchiveError('duplicate archive member: ' + relative)
            seen.add(relative)
            relatives.append(relative)
    expected = tuple(sorted(expected_members))
    found = tuple(sorted(relatives))
    if found != expected:
        raise ArchiveError('archive members do not match the runtime allowlist')
    return {
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'members': found,
        'uncompressed_bytes': expanded,
    }
