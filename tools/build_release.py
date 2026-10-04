"""Build the install archive and its private catalog from tracked files."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from release.artifacts import runtime_members, safe_source, write_catalog, write_deterministic_archive


def release_notes(repo: Path, version: str) -> str:
    path = repo / 'CHANGELOG.md'
    if not path.exists() and not path.is_symlink():
        return ''
    path = safe_source(repo, 'CHANGELOG.md')
    text = path.read_text(encoding='utf-8-sig')
    match = re.search(r'^##\s+\[?' + re.escape(version) + r'\]?(?=\s|$)[^\n]*\n', text, re.M)
    if not match:
        return ''
    tail = text[match.end():]
    return re.split(r'^##\s', tail, maxsplit=1, flags=re.M)[0].strip() + '\n'


def build(repo: Path, version: str, out_dir: Path, base_url: str, *,
          release_tag: str | None = None) -> tuple[Path, Path]:
    members = runtime_members(repo)
    manifest = yaml.safe_load((repo / 'extension.yml').read_text(encoding='utf-8-sig'))
    if version != manifest['extension']['version']:
        raise SystemExit('Release version must match extension.yml')
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / ('usage-bridge-v' + version + '.zip')
    write_deterministic_archive(repo, members, archive)
    tag = release_tag or ('v' + version)
    catalog = write_catalog(
        repo, archive, version, tag, base_url, out_dir / 'catalog.json', latest=release_tag is None,
    )
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
