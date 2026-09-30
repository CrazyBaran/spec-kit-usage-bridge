#!/usr/bin/env python3
"""Update the pinned token-usage source files from a GitHub archive."""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

VENDOR_RELATIVE = Path("scripts/python/vendor/token_usage")
UPSTREAM_REPO = "https://github.com/Wicked-Sick-Ltd/token-usage"
FILES = ("scripts/token_usage.py", "data/pricing.json", "LICENSE")
CHANGELOG = "CHANGELOG.md"


def archive_url(ref: str, is_commit: bool) -> str:
    suffix = ref if is_commit else "refs/tags/" + ref
    return "https://codeload.github.com/Wicked-Sick-Ltd/token-usage/zip/" + suffix


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _read_archive(archive_data: bytes) -> tuple[dict[str, bytes], str]:
    try:
        with zipfile.ZipFile(BytesIO(archive_data)) as archive:
            comment = archive.comment.decode("ascii").strip()
            if not re.fullmatch(r"[0-9a-fA-F]{40}", comment):
                raise ValueError("archive comment is not a 40-character commit id")
            found = {}
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                parts = Path(entry.filename).parts
                if len(parts) < 2:
                    continue
                relative = "/".join(parts[1:])
                if relative in FILES or relative == CHANGELOG:
                    if relative in found:
                        raise ValueError("archive contains duplicate " + relative)
                    found[relative] = archive.read(entry)
    except (UnicodeDecodeError, zipfile.BadZipFile, OSError) as exc:
        raise ValueError("invalid upstream archive: " + str(exc)) from exc

    missing = [name for name in (*FILES, CHANGELOG) if name not in found]
    if missing:
        raise ValueError("upstream archive is missing: " + ", ".join(missing))
    return found, comment.lower()


def _changelog_sections(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^##\s+\[?([^\]\s]+)\]?(?:\s.*)?$", text))
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(1), text[match.start():end].strip()))
    if not sections:
        raise ValueError("upstream CHANGELOG.md has no version sections")
    return sections


def _changed_sections(sections: list[tuple[str, str]], previous: str) -> str:
    selected = []
    for version, body in sections:
        if version == previous:
            break
        selected.append(body)
    if previous and not any(version == previous for version, _ in sections):
        return "\n\n".join(selected)
    return "\n\n".join(selected)


def update(
    repo: Path, ref: str, is_commit: bool, fetch: Callable[[str], bytes]
) -> dict[str, Any]:
    repo = Path(repo)
    vendor = repo / VENDOR_RELATIVE
    manifest_path = vendor / "VENDOR.json"
    try:
        old_info = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Cannot read vendor manifest: " + str(exc)) from exc

    for name in FILES:
        path = vendor / Path(name)
        try:
            actual = _sha256(path.read_bytes())
        except OSError as exc:
            raise SystemExit("Cannot verify vendored file " + name + ": " + str(exc)) from exc
        if actual != old_info.get("files", {}).get(name):
            raise SystemExit("Vendored file has local changes: " + name)

    try:
        archive, commit = _read_archive(fetch(archive_url(ref, is_commit)))
        sections = _changelog_sections(archive[CHANGELOG].decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SystemExit("Cannot update vendor: " + str(exc)) from exc

    version = sections[0][0]
    new_info = {
        "repo": old_info.get("repo", UPSTREAM_REPO),
        "ref": ref,
        "commit": commit,
        "upstream_version": version,
        "files": {name: _sha256(archive[name]) for name in FILES},
    }

    for name in FILES:
        destination = vendor / Path(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive[name])
    with manifest_path.open("w", encoding="utf-8", newline="\n") as manifest_file:
        manifest_file.write(json.dumps(new_info, indent=2, ensure_ascii=False) + "\n")

    changes = _changed_sections(sections, old_info.get("upstream_version", ""))
    print("Upstream CHANGELOG changes:")
    print(changes if changes else "No new CHANGELOG sections.")
    print("Run the contract tests: python -m pytest -m contract")
    return new_info


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ref", nargs="?", help="upstream tag (for example v0.7.0)")
    parser.add_argument("--commit", dest="commit", help="fetch an explicit commit SHA")
    args = parser.parse_args(argv)
    if bool(args.ref) == bool(args.commit):
        parser.error("provide either <tag> or --commit <sha>")
    ref = args.commit or args.ref
    try:
        update(Path(__file__).resolve().parents[1], ref, bool(args.commit), _fetch)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print("Cannot update vendor: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
