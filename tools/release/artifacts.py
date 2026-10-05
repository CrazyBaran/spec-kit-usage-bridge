"""Runtime allowlist, deterministic archives, and bounded archive validation."""
from __future__ import annotations

import base64
import hashlib
import json
import re
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


def safe_source(repo: Path, name: str) -> Path:
    """Reject link and path aliases before reading untrusted checkout contents."""
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ArchiveError('escaping runtime source path: ' + str(name))
    root = Path(repo).resolve()
    selected = root
    for part in name.split('/'):
        selected = selected / part
        if selected.is_symlink() or (hasattr(selected, 'is_junction') and selected.is_junction()):
            raise ArchiveError('symlink runtime source path: ' + name)
    if not selected.resolve().is_relative_to(root):
        raise ArchiveError('escaping runtime source path: ' + name)
    if not selected.is_file():
        raise ArchiveError('missing runtime source file: ' + name)
    return selected


def runtime_members(repo: Path) -> tuple[str, ...]:
    """Tracked runtime files only. Untracked checkout files are never packaged."""
    tracked = _tracked(repo)
    manifest = yaml.safe_load(safe_source(repo, 'extension.yml').read_text(encoding='utf-8-sig'))
    commands = tuple(item['file'] for item in manifest['provides']['commands'])
    package = tuple(
        name for name in tracked
        if name.startswith('scripts/python/usage_bridge/') and name.endswith('.py')
    )
    selected = commands + ENTRYPOINTS + package + (PRICING,) + VENDOR_FILES + LEGAL_FILES
    missing = [name for name in selected if name not in tracked]
    if missing:
        raise ArchiveError('missing tracked runtime file: ' + ', '.join(missing))
    for name in selected:
        safe_source(repo, name)
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

    sources = {name: safe_source(repo, name) for name in members}
    stamp = _commit_stamp(repo)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'w') as zipped:
        for name in members:
            info = zipfile.ZipInfo(PREFIX + name, stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.extra = b''
            zipped.writestr(info, sources[name].read_bytes())


def write_catalog(repo: Path, archive: Path, version: str, release_tag: str, base_url: str,
                  output: Path, *, latest: bool = False) -> Path:
    """Write catalog metadata. ``latest`` keeps the stable latest catalog URL.

    A concrete ``release_tag`` with ``latest=False`` pins both the catalog and
    the download URL to that tag (candidate or stable promotion).
    """
    import json

    manifest = yaml.safe_load(safe_source(repo, 'extension.yml').read_text(encoding='utf-8-sig'))
    ext = manifest['extension']
    if version != ext['version']:
        raise SystemExit('Release version must match extension.yml')
    base_url = base_url.rstrip('/')
    download_tag = release_tag
    if latest:
        catalog_path = 'releases/latest/download/catalog.json'
    else:
        catalog_path = f'releases/download/{release_tag}/catalog.json'
    stamp = datetime(*_commit_stamp(repo), tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
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

    bounds = {**DEFAULT_LIMITS, **(limits or {})}
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
            if relative.casefold() in seen:
                raise ArchiveError('duplicate archive member: ' + relative)
            seen.add(relative.casefold())
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


def release_asset_names(version: str) -> tuple[str, ...]:
    return (f'usage-bridge-v{version}.zip', 'catalog.json', 'SHA256SUMS', 'release-metadata.json')


def release_vendor(api, evidence: dict) -> dict:
    """Resolve the reviewed vendor pin from the exact release source, not today's main."""
    from release.policy import ReleasePolicyError, require_metadata

    require_metadata(evidence)
    item = api.request('GET', f"/repos/{evidence['repository']}/contents/{VENDOR_FILES[0]}"
                       f"?ref={evidence['source_sha']}")
    try:
        if (item.get('type') != 'file' or item.get('encoding') != 'base64'
                or type(item.get('size')) is not int or not 0 < item['size'] <= 65536):
            raise ValueError('unsupported file')
        raw = base64.b64decode(item['content'].replace('\n', ''), validate=True)
        if len(raw) != item['size']:
            raise ValueError('file size mismatch')
        vendor = json.loads(raw)
        if not isinstance(vendor, dict) or not isinstance(vendor.get('files'), dict):
            raise ValueError('missing vendor file hashes')
        return vendor
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError):
        raise ReleasePolicyError('invalid vendor provenance at release source') from None


def validate_release_assets(assets: dict[str, Path], evidence: dict, *, vendor_manifest: dict | None = None) -> dict:
    """Validate actual ZIP, manifest, vendor hashes, catalog, and checksum bytes."""
    import zipfile

    from release.policy import ReleasePolicyError, load_release_policy, require_metadata

    require_metadata(evidence)
    names = release_asset_names(evidence['version'])
    if not set(names).issubset(assets):
        raise ReleasePolicyError('release is missing required archive/catalog/checksums/metadata assets')
    for name, path in assets.items():
        if Path(name).name != name or '/' in name or '\\' in name or not Path(path).is_file():
            raise ReleasePolicyError('invalid release asset: ' + name)
        if Path(path).stat().st_size > DEFAULT_LIMITS['max_compressed_bytes']:
            raise ReleasePolicyError('release asset exceeds size limit: ' + name)
    archive_path = Path(assets[names[0]])
    declared = evidence.get('members')
    if (not isinstance(declared, list) or not declared or any(not isinstance(name, str) for name in declared)
            or len(declared) != len(set(declared))):
        raise ReleasePolicyError('release metadata must contain the complete runtime member allowlist')
    try:
        archive_result = validate_archive(archive_path, tuple(declared), load_release_policy()['artifact_limits'])
        if archive_result['sha256'] != evidence['zip_sha256']:
            raise ReleasePolicyError('archive digest does not match release evidence')
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise ReleasePolicyError('release archive contains corrupt member bytes')
            manifest = yaml.safe_load(archive.read(PREFIX + 'extension.yml'))
            extension = manifest['extension']
            if extension['id'] != 'usage-bridge' or extension['version'] != evidence['version']:
                raise ReleasePolicyError('archive manifest version/id does not match the release')
            commands = tuple(item['file'] for item in manifest['provides']['commands'])
            if not commands or any(not re.fullmatch(r'commands/[A-Za-z0-9_-]+\.md', name) for name in commands):
                raise ReleasePolicyError('manifest declares invalid runtime commands')
            required = set(commands + ENTRYPOINTS + VENDOR_FILES + LEGAL_FILES + (PRICING,
                'scripts/python/usage_bridge/__init__.py'))
            if not required.issubset(declared):
                raise ReleasePolicyError('archive is missing a command, legal, vendor, or runtime file')
            for name in declared:
                if name in required:
                    continue
                if not re.fullmatch(r'scripts/python/usage_bridge/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py', name):
                    raise ReleasePolicyError('archive contains a member outside the runtime allowlist: ' + name)
            vendor_prefix = PREFIX + 'scripts/python/vendor/token_usage/'
            trusted_vendor = vendor_manifest if vendor_manifest is not None else json.loads(
                (Path(__file__).resolve().parents[2] / VENDOR_FILES[0]).read_text(encoding='utf-8'))
            if json.loads(archive.read(vendor_prefix + 'VENDOR.json')) != trusted_vendor:
                raise ReleasePolicyError('archive vendor provenance does not match the reviewed pin')
            for name, checksum in trusted_vendor['files'].items():
                if 'sha256:' + hashlib.sha256(archive.read(vendor_prefix + name)).hexdigest() != checksum:
                    raise ReleasePolicyError('archive vendor hash mismatch: ' + name)
        metadata = json.loads(Path(assets['release-metadata.json']).read_text(encoding='utf-8'))
        require_metadata(metadata)
        for name in ('repository', 'version', 'tag', 'source_sha', 'zip_sha256', 'run_id', 'attempt',
                     'candidate_tag', 'members', 'checks', 'override', 'gate', 'verification'):
            if metadata.get(name) != evidence.get(name):
                raise ReleasePolicyError('uploaded metadata differs from evidence: ' + name)
        catalog = json.loads(Path(assets['catalog.json']).read_text(encoding='utf-8'))
        entry = catalog['extensions']['usage-bridge']
        base = f"https://github.com/{evidence['repository']}/releases/download/{evidence['tag']}"
        if (catalog.get('schema_version') != '1.0' or catalog.get('catalog_url') != base + '/catalog.json'
                or entry.get('version') != evidence['version'] or entry.get('sha256') != evidence['zip_sha256']
                or entry.get('download_url') != base + '/' + names[0]):
            raise ReleasePolicyError('catalog metadata must match the release and tag-pinned archive')
        checksums = {}
        for line in Path(assets['SHA256SUMS']).read_text(encoding='utf-8').splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  ([^/\\]+)', line)
            if match is None or match[2] in checksums:
                raise ReleasePolicyError('invalid or duplicate checksum entry')
            checksums[match[2]] = match[1]
        required_checksums = set(assets) - {'SHA256SUMS'}
        if set(checksums) != required_checksums:
            raise ReleasePolicyError('checksums must cover all release assets exactly once')
        for name in required_checksums:
            if hashlib.sha256(Path(assets[name]).read_bytes()).hexdigest() != checksums[name]:
                raise ReleasePolicyError('release asset checksum mismatch: ' + name)
    except (ArchiveError, zipfile.BadZipFile, KeyError, TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, ReleasePolicyError):
            raise
        raise ReleasePolicyError('invalid release artifact: ' + str(exc)) from None
    return {'archive': archive_result, 'manifest': manifest, 'metadata': metadata, 'catalog': catalog,
            'checksums': checksums}
