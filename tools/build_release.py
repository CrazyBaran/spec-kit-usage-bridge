"""Build the install archive and its private catalog from tracked files."""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml


def excluded(name: str, patterns: list[str]) -> bool:
    parts = name.split('/')
    for pattern in patterns:
        pattern = pattern.removeprefix('**/')
        directory = pattern.endswith('/')
        pattern = pattern.rstrip('/')
        candidates = parts[:-1] if directory else parts
        if '/' not in pattern and any(fnmatch.fnmatchcase(p, pattern) for p in candidates):
            return True
        if fnmatch.fnmatchcase(name, pattern) or name.startswith(pattern + '/'):
            return True
    return False


def release_notes(repo: Path, version: str) -> str:
    path = repo / 'CHANGELOG.md'
    if not path.exists():
        return ''
    text = path.read_text(encoding='utf-8-sig')
    match = re.search(r'^##\s+\[?' + re.escape(version) + r'\]?(?=\s|$)[^\n]*\n', text, re.M)
    if not match:
        return ''
    tail = text[match.end():]
    return re.split(r'^##\s', tail, maxsplit=1, flags=re.M)[0].strip() + '\n'


def build(repo: Path, version: str, out_dir: Path, base_url: str) -> tuple[Path, Path]:
    manifest = yaml.safe_load((repo / 'extension.yml').read_text(encoding='utf-8-sig'))
    ext = manifest['extension']
    if version != ext['version']:
        raise SystemExit('Release version must match extension.yml')
    tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=repo, check=True, capture_output=True).stdout
    patterns = [p.strip() for p in (repo / '.extensionignore').read_text().splitlines()
                if p.strip() and not p.lstrip().startswith('#')]
    names = sorted(n for n in tracked.decode('utf-8').split('\0') if n and not excluded(n, patterns))
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / ('usage-bridge-v' + version + '.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.write(repo / name, 'usage-bridge/' + name)
    base_url = base_url.rstrip('/')
    stamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    entry = dict(ext)
    entry.update(download_url=base_url + '/releases/download/v' + version + '/' + archive.name,
                 repository=base_url, homepage=base_url, documentation=base_url + '#readme',
                 changelog=base_url + '/blob/main/CHANGELOG.md', requires=manifest['requires'],
                 provides={'commands': len(manifest['provides']['commands']), 'hooks': len(manifest['hooks'])},
                 tags=manifest['tags'], created_at=stamp, updated_at=stamp)
    catalog = out_dir / 'catalog.json'
    catalog.write_text(json.dumps({'schema_version': '1.0',
                                  'catalog_url': base_url + '/releases/latest/download/catalog.json',
                                  'extensions': {ext['id']: entry}}, indent=2) + '\n', encoding='utf-8')
    (out_dir / 'RELEASE_NOTES.md').write_text(release_notes(repo, version), encoding='utf-8')
    return archive, catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--out', type=Path, default=Path('dist'))
    parser.add_argument('--base-url', required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.version, args.out, args.base_url)


if __name__ == '__main__':
    main()
