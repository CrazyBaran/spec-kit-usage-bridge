"""Release tooling CLI. Development only; publication stays behind explicit commands."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from github_api import GitHubAPI, GitHubAPIError
from release.context import candidate_context, decide_gate, promotion_context
from release.mergeback import enable_mergeback
from release.policy import ReleasePolicyError, parse_version
from release.prepare import prepare_release
from release.publication import publish_release
from release.submission import load_submission_policy, render_submission, submit_release
from release.verification import verify_release

DEFAULT_REPO = 'CrazyBaran/spec-kit-usage-bridge'


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError('missing configuration file ' + str(path))
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')


def _stable_tag(tag: str) -> str:
    if not tag.startswith('v'):
        raise ReleasePolicyError('tag must look like vX.Y.Z')
    version = tag[1:]
    if '-' in version:
        raise ReleasePolicyError('only a verified stable release can be submitted')
    parse_version(version)
    return version


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)

    prepare = commands.add_parser('prepare')
    prepare.add_argument('--version', required=True)
    prepare.add_argument('--main-sha', required=True)
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--repo', default=DEFAULT_REPO)
    prepare.add_argument('--checkout', type=Path, default=Path('.'))
    prepare.add_argument('--dry-run', action='store_true')

    candidate = commands.add_parser('candidate-context')
    candidate.add_argument('--version', required=True)
    candidate.add_argument('--source-sha', required=True)
    candidate.add_argument('--output', type=Path, required=True)
    candidate.add_argument('--repo', default=DEFAULT_REPO)

    promotion = commands.add_parser('promotion-context')
    promotion.add_argument('--version', required=True)
    promotion.add_argument('--candidate-tag', default='')
    promotion.add_argument('--source-sha', required=True)
    promotion.add_argument('--output', type=Path, required=True)
    promotion.add_argument('--repo', default=DEFAULT_REPO)

    gate = commands.add_parser('gate')
    gate.add_argument('--evidence', type=Path, required=True)
    gate.add_argument('--output', type=Path, required=True)

    publish = commands.add_parser('publish')
    publish.add_argument('--evidence', type=Path, required=True)
    publish.add_argument('--assets-dir', type=Path, required=True)
    publish.add_argument('--output', type=Path, required=True)
    publish.add_argument('--prerelease', action='store_true')

    verify = commands.add_parser('verify')
    verify.add_argument('--tag', required=True)
    verify.add_argument('--evidence', type=Path, required=True)
    verify.add_argument('--archive', type=Path, required=True)
    verify.add_argument('--download-dir', type=Path, required=True)
    verify.add_argument('--output', type=Path, required=True)

    mergeback = commands.add_parser('mergeback')
    mergeback.add_argument('--version', required=True)
    mergeback.add_argument('--source-sha', required=True)
    mergeback.add_argument('--verification', type=Path, required=True)
    mergeback.add_argument('--output', type=Path, required=True)
    mergeback.add_argument('--repo', default=DEFAULT_REPO)

    submit = commands.add_parser('submit')
    submit.add_argument('--tag', required=True)
    submit.add_argument('--verification', type=Path)
    submit.add_argument('--evidence', type=Path)
    submit.add_argument('--manifest', type=Path)
    submit.add_argument('--output', type=Path)
    submit.add_argument('--prepare-only', action='store_true')
    return parser


def _dispatch(args, api) -> tuple[dict, int]:
    if args.command == 'prepare':
        result = prepare_release(
            api, args.repo, args.version, args.main_sha,
            checkout=args.checkout, dry_run=args.dry_run,
        )
        return result, 0
    if args.command == 'candidate-context':
        return candidate_context(api, args.repo, args.version, args.source_sha), 0
    if args.command == 'promotion-context':
        result = promotion_context(
            api, args.repo, args.version, args.candidate_tag, args.source_sha,
        )
        code = 2 if result['status'] == 'manual_publication' else 0
        return result, code
    if args.command == 'gate':
        decision = decide_gate(_read_json(args.evidence))
        return decision, 0 if decision['allowed'] else 2
    if args.command == 'publish':
        evidence = _read_json(args.evidence)
        assets = {path.name: path for path in sorted(args.assets_dir.iterdir()) if path.is_file()}
        if not assets:
            raise ReleasePolicyError('publish assets directory is empty')
        return publish_release(api, evidence, assets, args.prerelease), 0
    if args.command == 'verify':
        evidence = _read_json(args.evidence)
        archive = args.archive
        if not archive.is_file():
            raise FileNotFoundError('missing release archive ' + str(archive))

        def download(url, dest, source=archive):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())

        return verify_release(api, args.tag, evidence, args.download_dir, downloader=download), 0
    if args.command == 'mergeback':
        verification = _read_json(args.verification)
        if verification.get('provenance') is not True:
            raise ReleasePolicyError('merge-back requires provenance verification')
        if verification.get('build_sha') != args.source_sha:
            raise ReleasePolicyError('merge-back verification does not match the source SHA')
        result = enable_mergeback(api, args.version, args.source_sha, repo=args.repo)
        code = 0 if result['status'] in {'auto_merge_enabled', 'already_merged'} else 2
        return result, code
    if args.command == 'submit':
        version = _stable_tag(args.tag)
        if args.output is None or args.verification is None or args.evidence is None or args.manifest is None:
            raise FileNotFoundError('submit requires --verification, --evidence, --manifest, and --output')
        verification = _read_json(args.verification)
        evidence = _read_json(args.evidence)
        manifest = _read_json(args.manifest)
        release = {
            'version': version,
            'tag': args.tag,
            'repository': verification.get('repository', DEFAULT_REPO),
            'extension_id': manifest['extension']['id'],
            'author': manifest['extension']['author'],
            'prerelease': False,
            'zip_sha256': verification['zip_sha256'],
            'download_url': (
                f"https://github.com/{verification.get('repository', DEFAULT_REPO)}"
                f"/releases/download/{args.tag}/usage-bridge-v{version}.zip"
            ),
        }
        policy = load_submission_policy()
        provided = evidence.get('attestations') or {}
        missing = [
            name for name, ready in (
                ('real_project', bool(str(provided.get('real_project') or '').strip())),
                ('documentation_review', provided.get('documentation_review') is True),
                ('security_review', bool(str(provided.get('security_review') or '').strip())),
            ) if not ready
        ]
        if args.prepare_only or missing:
            body = render_submission(
                manifest, release, evidence, {'headings': policy['required_headings']},
            )
            return {
                'action': 'block', 'status': 'pending', 'body': body,
                'blockers': ['missing attestation: ' + name for name in missing],
            }, 0
        result = submit_release(api, release, evidence, manifest=manifest)
        if result.get('status') == 'forbidden':
            return result, 3
        if result.get('action') == 'block' and result.get('status') != 'pending':
            return result, 2
        return result, 0
    raise ReleasePolicyError('unknown release command')


def main(argv: list[str] | None = None, api=None) -> int:
    parser = _parser()
    if argv and argv[0] == 'submit' and any(arg.startswith('v') and '-rc.' in arg for arg in argv):
        print('only a verified stable release can be submitted', file=sys.stderr)
        return 2
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    try:
        result, code = _dispatch(args, api or GitHubAPI())
    except ReleasePolicyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except GitHubAPIError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    if getattr(args, 'output', None) is not None:
        _write(args.output, result)
    return code


if __name__ == '__main__':
    sys.exit(main())
