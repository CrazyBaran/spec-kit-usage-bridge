import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://github.com/CrazyBaran/spec-kit-usage-bridge'
VERSION = yaml.safe_load((ROOT / 'extension.yml').read_text(encoding='utf-8-sig'))['extension']['version']


def build(*args, **kwargs):
    spec = importlib.util.spec_from_file_location('build_release', ROOT / 'tools/build_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build(*args, **kwargs)


def test_zip_layout(tmp_path):
    archive, _ = build(ROOT, VERSION, tmp_path, BASE)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert archive.name == f'usage-bridge-v{VERSION}.zip'
        assert all(n.startswith('usage-bridge/') for n in names)
        assert 'usage-bridge/AGENTS.md' not in names
        for required in ('extension.yml', 'THIRD_PARTY_NOTICES.md',
                         'scripts/python/vendor/token_usage/LICENSE', 'commands/report.md',
                         'scripts/python/usage_bridge/adapters/codex.py',
                         'scripts/python/usage_bridge/adapters/cursor.py',
                         'scripts/python/usage_bridge/cursor_worker.py',
                         'scripts/python/usage_bridge/bindings.py',
                         'scripts/python/usage_bridge/checkpoint.py',
                         'scripts/python/checkpoint.py', 'commands/checkpoint.md',
                         'scripts/python/usage_bridge/data/openai-pricing.json'):
            assert 'usage-bridge/' + required in names
            assert z.read('usage-bridge/' + required) == (ROOT / required).read_bytes()
        assert not any(n.startswith(('usage-bridge/tests/', 'usage-bridge/tools/',
                                     'usage-bridge/docs/', 'usage-bridge/.github/')) for n in names)


def test_catalog_entry(tmp_path):
    _, catalog = build(ROOT, VERSION, tmp_path, BASE)
    data = json.loads(catalog.read_text(encoding='utf-8'))
    entry = data['extensions']['usage-bridge']
    assert data['schema_version'] == '1.0'
    assert data['catalog_url'] == BASE + '/releases/latest/download/catalog.json'
    assert entry['download_url'] == BASE + f'/releases/download/v{VERSION}/usage-bridge-v{VERSION}.zip'
    assert (entry['version'], entry['requires']['speckit_version'], entry['license']) == (VERSION, '>=1.0.12', 'MIT')
    assert entry['provides']['commands'] == 4
    assert entry['provides']['hooks'] == 3


def test_candidate_catalog_is_tag_pinned(tmp_path):
    archive, catalog = build(ROOT, VERSION, tmp_path, BASE, release_tag=f'v{VERSION}-rc.1')
    data = json.loads(catalog.read_text())
    assert data['extensions']['usage-bridge']['version'] == VERSION
    assert f'/download/v{VERSION}-rc.1/' in data['extensions']['usage-bridge']['download_url']
    assert f'/download/v{VERSION}-rc.1/' in data['catalog_url']
    assert data['extensions']['usage-bridge']['sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_version_must_match_manifest(tmp_path):
    with pytest.raises(SystemExit):
        build(ROOT, '9.9.9', tmp_path, BASE)
    assert not list(tmp_path.glob('*.zip'))
