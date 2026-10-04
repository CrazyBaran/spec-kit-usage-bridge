from pathlib import Path

import pytest

from release.policy import ReleasePolicyError
from release.verification import verify_release

SHA = 'a' * 40


def _expected(**overrides):
    data = {
        'schema_version': 1, 'repository': 'CrazyBaran/spec-kit-usage-bridge', 'version': '0.2.2',
        'tag': 'v0.2.2', 'source_sha': SHA, 'run_id': 1, 'attempt': 1,
        'zip_sha256': 'abc', 'candidate_tag': 'v0.2.2-rc.1', 'checks': [], 'override': None,
        'verification': {'provenance': True, 'build_sha': SHA},
    }
    data.update(overrides)
    return data


def test_verify_rejects_tampered_digest(tmp_path: Path):
    def download(url: str, dest: Path) -> None:
        dest.write_bytes(b'tampered')

    with pytest.raises(ReleasePolicyError):
        verify_release(None, 'v0.2.2', _expected(zip_sha256='f' * 64), tmp_path, downloader=download)


def test_verify_rejects_unknown_schema(tmp_path: Path):
    with pytest.raises(ReleasePolicyError):
        verify_release(None, 'v0.2.2', _expected(schema_version=2), tmp_path, downloader=lambda url, dest: None)


def test_verify_rejects_missing_provenance(tmp_path: Path):
    with pytest.raises(ReleasePolicyError):
        verify_release(None, 'v0.2.2', _expected(verification={}), tmp_path, downloader=lambda url, dest: None)
