"""Release tooling CLI. Development only; no publication on prepare."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from github_api import GitHubAPI, GitHubAPIError
from release.policy import ReleasePolicyError
from release.prepare import prepare_release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--version', required=True)
    prepare.add_argument('--main-sha', required=True)
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--repo', default='CrazyBaran/spec-kit-usage-bridge')
    prepare.add_argument('--checkout', type=Path, default=Path('.'))
    prepare.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare_release(
                GitHubAPI(), args.repo, args.version, args.main_sha,
                checkout=args.checkout, dry_run=args.dry_run,
            )
        else:
            return 2
    except ReleasePolicyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except GitHubAPIError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
