import hashlib
import importlib.util
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR_SOURCE = ROOT / "scripts/python/vendor/token_usage"
SPEC = importlib.util.spec_from_file_location("update_vendor", ROOT / "tools/update-vendor.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def copy_repo_vendor(tmp_path):
    target = tmp_path / "scripts/python/vendor/token_usage"
    shutil.copytree(VENDOR_SOURCE, target)
    return tmp_path


def fake_archive(files, comment=b""):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.comment = comment
        for name, body in files.items():
            archive.writestr("token-usage-x/" + name, body)
    return data.getvalue()


def test_update_replaces_only_vendored_files(tmp_path):
    repo = copy_repo_vendor(tmp_path)
    archive = fake_archive(
        {
            "scripts/token_usage.py": b"print(1)\n",
            "data/pricing.json": b"{}\n",
            "LICENSE": b"MIT\n",
            "CHANGELOG.md": b"## [0.7.0]\n- new\n",
            "README.md": b"x",
        },
        comment=b"a" * 40,
    )

    info = mod.update(repo, "v0.7.0", False, lambda url: archive)
    vendor = repo / "scripts/python/vendor/token_usage"

    assert (vendor / "scripts/token_usage.py").read_bytes() == b"print(1)\n"
    assert not (vendor / "README.md").exists()
    assert (info["ref"], info["commit"]) == ("v0.7.0", "a" * 40)
    assert info["files"]["LICENSE"] == "sha256:" + hashlib.sha256(b"MIT\n").hexdigest()
    assert json.loads((vendor / "VENDOR.json").read_text(encoding="utf-8")) == info


def test_manifest_write_works_without_path_write_text_newline_support(tmp_path, monkeypatch):
    repo = copy_repo_vendor(tmp_path)
    archive = fake_archive(
        {
            "scripts/token_usage.py": b"print(1)\n",
            "data/pricing.json": b"{}\n",
            "LICENSE": b"MIT\n",
            "CHANGELOG.md": b"## [0.7.0]\n- new\n",
        },
        comment=b"a" * 40,
    )
    original_write_text = Path.write_text

    def python39_write_text(path, data, encoding=None):
        return original_write_text(path, data, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", python39_write_text)

    mod.update(repo, "v0.7.0", False, lambda url: archive)

    manifest = (repo / "scripts/python/vendor/token_usage/VENDOR.json").read_bytes()
    assert b"\r\n" not in manifest


def test_update_prints_only_changelog_sections_newer_than_pinned_version(tmp_path, capsys):
    repo = copy_repo_vendor(tmp_path)
    archive = fake_archive(
        {
            "scripts/token_usage.py": b"print(1)\n",
            "data/pricing.json": b"{}\n",
            "LICENSE": b"MIT\n",
            "CHANGELOG.md": (
                b"## [0.8.0]\n- latest\n\n## [0.7.0]\n- pinned\n\n## [0.6.0]\n- old\n"
            ),
        },
        comment=b"b" * 40,
    )
    vendor = repo / "scripts/python/vendor/token_usage"
    old_manifest = json.loads((vendor / "VENDOR.json").read_text(encoding="utf-8"))
    old_manifest["upstream_version"] = "0.7.0"
    (vendor / "VENDOR.json").write_text(json.dumps(old_manifest), encoding="utf-8")

    mod.update(repo, "v0.8.0", False, lambda url: archive)

    output = capsys.readouterr().out
    assert "- latest" in output
    assert "- pinned" not in output
    assert "- old" not in output


def test_changelog_fallback_handles_missing_pinned_version(tmp_path, capsys):
    repo = copy_repo_vendor(tmp_path)
    archive = fake_archive(
        {
            "scripts/token_usage.py": b"print(1)\n",
            "data/pricing.json": b"{}\n",
            "LICENSE": b"MIT\n",
            "CHANGELOG.md": b"## [0.8.0]\n- latest\n\n## [0.7.0]\n- previous\n",
        },
        comment=b"c" * 40,
    )
    vendor = repo / "scripts/python/vendor/token_usage"
    old_manifest = json.loads((vendor / "VENDOR.json").read_text(encoding="utf-8"))
    old_manifest["upstream_version"] = "0.5.0"
    (vendor / "VENDOR.json").write_text(json.dumps(old_manifest), encoding="utf-8")

    mod.update(repo, "v0.8.0", False, lambda url: archive)

    output = capsys.readouterr().out
    assert "- latest" in output
    assert "- previous" in output


def test_malformed_archive_is_rejected_without_changing_vendor(tmp_path):
    repo = copy_repo_vendor(tmp_path)
    vendor = repo / "scripts/python/vendor/token_usage"
    original = {path.relative_to(vendor): path.read_bytes() for path in vendor.rglob("*") if path.is_file()}

    with pytest.raises(SystemExit, match="Cannot update vendor: invalid upstream archive"):
        mod.update(repo, "v0.7.0", False, lambda url: b"not a zip archive")

    assert {path: (vendor / path).read_bytes() for path in original} == original


def test_refuses_when_local_files_drifted(tmp_path):
    repo = copy_repo_vendor(tmp_path)
    (repo / "scripts/python/vendor/token_usage/LICENSE").write_bytes(b"edited")

    with pytest.raises(SystemExit):
        mod.update(repo, "v0.7.0", False, lambda url: b"")


def test_urls_for_tag_and_commit():
    assert mod.archive_url("v0.7.0", False).endswith("/zip/refs/tags/v0.7.0")
    assert mod.archive_url("abc", True).endswith("/zip/abc")


def test_unreleased_updates_keep_release_version_and_show_changed_content(tmp_path, capsys):
    repo = copy_repo_vendor(tmp_path)
    def archive(body, commit):
        return fake_archive({'scripts/token_usage.py': b'print(1)\n', 'data/pricing.json': b'{}\n',
                             'LICENSE': b'MIT\n',
                             'CHANGELOG.md': b'## [Unreleased]\n' + body + b'\n## [0.6.1]\n- released\n'},
                            comment=commit)
    info = mod.update(repo, 'a' * 40, True, lambda url: archive(b'- first', b'a' * 40))
    assert info['upstream_version'] == '0.6.1'
    assert info['unreleased_sha256'].startswith('sha256:')
    capsys.readouterr()
    next_info = mod.update(repo, 'b' * 40, True, lambda url: archive(b'- second', b'b' * 40))
    assert next_info['upstream_version'] == '0.6.1'
    assert next_info['unreleased_sha256'] != info['unreleased_sha256']
    output = capsys.readouterr().out
    assert '- second' in output and '- released' not in output
    mod.update(repo, 'c' * 40, True, lambda url: archive(b'- second', b'c' * 40))
    assert 'No new CHANGELOG sections.' in capsys.readouterr().out


def test_legacy_unreleased_manifest_does_not_hide_current_changes(tmp_path, capsys):
    repo = copy_repo_vendor(tmp_path)
    manifest = repo / 'scripts/python/vendor/token_usage/VENDOR.json'
    info = json.loads(manifest.read_text(encoding='utf-8'))
    info['upstream_version'] = 'Unreleased'
    manifest.write_text(json.dumps(info), encoding='utf-8')
    archive = fake_archive({'scripts/token_usage.py': b'print(1)\n', 'data/pricing.json': b'{}\n',
                            'LICENSE': b'MIT\n', 'CHANGELOG.md': b'## [Unreleased]\n- current\n## [0.6.1]\n- old\n'},
                           comment=b'a' * 40)
    assert mod.update(repo, 'a' * 40, True, lambda url: archive)['upstream_version'] == '0.6.1'
    assert '- current' in capsys.readouterr().out
