import os
import stat
import zipfile
from pathlib import Path

import pytest
import yaml

from release.artifacts import ArchiveError, runtime_members, validate_archive

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = (
    'scripts/python/capture.py',
    'scripts/python/report.py',
    'scripts/python/check.py',
    'scripts/python/checkpoint.py',
)
VENDOR = (
    'scripts/python/vendor/token_usage/VENDOR.json',
    'scripts/python/vendor/token_usage/LICENSE',
    'scripts/python/vendor/token_usage/scripts/token_usage.py',
    'scripts/python/vendor/token_usage/data/pricing.json',
)
LEGAL = (
    'extension.yml',
    'config-template.yml',
    'LICENSE',
    'THIRD_PARTY_NOTICES.md',
)


def _expected_members() -> tuple[str, ...]:
    manifest = yaml.safe_load((ROOT / 'extension.yml').read_text(encoding='utf-8-sig'))
    commands = tuple(item['file'] for item in manifest['provides']['commands'])
    package = tuple(sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / 'scripts/python/usage_bridge').rglob('*.py')
        if '.git' not in path.parts and path.is_file()
    ))
    return tuple(sorted(commands + ENTRYPOINTS + package + (
        'scripts/python/usage_bridge/data/openai-pricing.json',
    ) + VENDOR + LEGAL))


def test_runtime_members_exact_and_legal():
    members = runtime_members(ROOT)
    expected = _expected_members()
    assert members == expected
    assert all(path.startswith(('commands/', 'scripts/python/', 'extension.yml',
                                'config-template.yml', 'LICENSE', 'THIRD_PARTY'))
               or path in LEGAL for path in members)
    assert 'README.md' not in members
    assert 'AGENTS.md' not in members
    assert not any(path.startswith(('tests/', 'tools/', 'docs/', '.github/')) for path in members)


def test_rebuild_ignores_mtime_and_mode(tmp_path):
    from test_build_release import build

    first, _ = build(ROOT, '0.2.1', tmp_path / 'a', 'https://example.test')
    target = ROOT / 'extension.yml'
    previous = target.stat()
    os.utime(target, (1_700_000_000, 1_600_000_000))
    os.chmod(target, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    try:
        second, _ = build(ROOT, '0.2.1', tmp_path / 'b', 'https://example.test')
        assert first.read_bytes() == second.read_bytes()
    finally:
        os.utime(target, (previous.st_atime, previous.st_mtime))
        os.chmod(target, previous.st_mode)


def _set_general_flag(path: Path, bit: int) -> None:
    """ZipFile.writestr clears the encryption bit; put it back in both headers."""
    data = bytearray(path.read_bytes())
    for signature, offset in ((b'PK\x03\x04', 6), (b'PK\x01\x02', 8)):
        start = 0
        while True:
            found = data.find(signature, start)
            if found < 0:
                break
            flags = int.from_bytes(data[found + offset:found + offset + 2], 'little') | bit
            data[found + offset:found + offset + 2] = flags.to_bytes(2, 'little')
            start = found + 4
    path.write_bytes(data)


def _zip(path: Path, items: list[tuple[zipfile.ZipInfo, bytes]]) -> None:
    with zipfile.ZipFile(path, 'w') as archive:
        for info, payload in items:
            archive.writestr(info, payload)


def test_symlink_traversal_and_zip_bomb(tmp_path):
    expected = ('extension.yml',)
    escape = tmp_path / 'escape.zip'
    info = zipfile.ZipInfo('usage-bridge/../../outside.txt')
    _zip(escape, [(info, b'nope')])
    with pytest.raises(ArchiveError):
        validate_archive(escape, expected)

    link = tmp_path / 'link.zip'
    linked = zipfile.ZipInfo('usage-bridge/extension.yml')
    linked.external_attr = (0o120777 << 16)
    linked.create_system = 3
    _zip(link, [(linked, b'target')])
    with pytest.raises(ArchiveError):
        validate_archive(link, expected)

    encrypted = tmp_path / 'encrypted.zip'
    secret = zipfile.ZipInfo('usage-bridge/extension.yml')
    _zip(encrypted, [(secret, b'secret')])
    _set_general_flag(encrypted, 0x1)
    with pytest.raises(ArchiveError):
        validate_archive(encrypted, expected)

    duplicate = tmp_path / 'duplicate.zip'
    _zip(duplicate, [
        (zipfile.ZipInfo('usage-bridge/extension.yml'), b'a'),
        (zipfile.ZipInfo('usage-bridge/extension.yml'), b'b'),
    ])
    with pytest.raises(ArchiveError):
        validate_archive(duplicate, expected)

    huge = tmp_path / 'huge.zip'
    _zip(huge, [(zipfile.ZipInfo('usage-bridge/extension.yml'), b'abcdef')])
    with pytest.raises(ArchiveError):
        validate_archive(huge, expected, {'max_expanded_bytes': 4, 'max_compressed_bytes': 25 * 1024 * 1024,
                                          'max_members': 1000})
    with pytest.raises(ArchiveError):
        validate_archive(huge, expected, {'max_expanded_bytes': 100 * 1024 * 1024, 'max_compressed_bytes': 1,
                                          'max_members': 1000})
    with pytest.raises(ArchiveError):
        validate_archive(huge, expected, {'max_expanded_bytes': 100 * 1024 * 1024,
                                          'max_compressed_bytes': 25 * 1024 * 1024, 'max_members': 0})


def test_untracked_runtime_module_rejected(tmp_path):
    extra = ROOT / 'scripts/python/usage_bridge/_local_untracked.py'
    extra.write_text('VALUE = 1\n', encoding='utf-8')
    try:
        assert not any(path.endswith('_local_untracked.py') for path in runtime_members(ROOT))
        from test_build_release import build
        archive, _ = build(ROOT, '0.2.1', tmp_path, 'https://example.test')
        with zipfile.ZipFile(archive) as zipped:
            assert not any('_local_untracked.py' in name for name in zipped.namelist())
    finally:
        extra.unlink(missing_ok=True)
