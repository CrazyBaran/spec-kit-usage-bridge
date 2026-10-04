"""Release tooling CLI. Development only; publication stays behind explicit commands."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from github_api import GitHubAPI, GitHubAPIError
from release.context import candidate_context, decide_gate, promotion_context
from release.mergeback import enable_mergeback
from release.orchestration import (
    bundle,
    collect,
    collect_run_evidence,
    manifest_from_archive,
    write_json,
)
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
    write_json(path, payload)


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

    build = commands.add_parser('bundle')
    build.add_argument('--checkout', type=Path, required=True)
    build.add_argument('--repo', default=DEFAULT_REPO)
    build.add_argument('--version', required=True)
    build.add_argument('--tag', required=True)
    build.add_argument('--source-sha', required=True)
    build.add_argument('--run-id', type=int, required=True)
    build.add_argument('--attempt', type=int, required=True)
    build.add_argument('--candidate-tag', default='')
    build.add_argument('--assets-dir', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True)

    gather = commands.add_parser('collect')
    gather.add_argument('--evidence', type=Path, required=True)
    gather.add_argument('--assets-dir', type=Path)
    gather.add_argument('--override-reason', default='')
    gather.add_argument('--waived-checks', default='[]', help='JSON array of exact quality check names')
    gather.add_argument('--output', type=Path, required=True)

    complete = commands.add_parser('complete-verification')
    complete.add_argument('--verification', type=Path, required=True)
    complete.add_argument('--run-id', type=int, required=True)
    complete.add_argument('--attempt', type=int, required=True)
    complete.add_argument('--output', type=Path, required=True)

    submission = commands.add_parser('submission-evidence')
    submission.add_argument('--verification', type=Path, required=True)
    submission.add_argument('--output', type=Path, required=True)

    identity = commands.add_parser('check-verification')
    identity.add_argument('--verification', type=Path, required=True)
    identity.add_argument('--tag', required=True)
    identity.add_argument('--source-sha', default='')
    identity.add_argument('--digest', default='')
    identity.add_argument('--output', type=Path, required=True)

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
    verify.add_argument('--evidence', type=Path)
    verify.add_argument('--repo', default=DEFAULT_REPO)
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
    if args.command == 'check-verification':
        record = _read_json(args.verification)
        if record.get('tag') != args.tag or not all(record.get(key) is True for key in (
                'provenance', 'packaging_verified', 'install_verified', 'commands_verified')):
            raise ReleasePolicyError('follow-through requires successful verification of the requested tag')
        if args.source_sha and record.get('source_sha') != args.source_sha:
            raise ReleasePolicyError('verified source does not match requested source SHA')
        if args.digest and record.get('zip_sha256') != args.digest:
            raise ReleasePolicyError('verified digest does not match requested digest')
        # A release event is a detector only; no credentials or mutations follow it.
        if os.environ.get('GITHUB_EVENT_NAME') == 'release':
            return dict(record, status='manual_publication', submit=False, merge=False), 0
        if '-rc.' in args.tag:
            raise ReleasePolicyError('only verified stable releases may proceed to follow-through')
        return record, 0
    if args.command == 'bundle':
        candidate_archive = None
        if args.candidate_tag:
            promotion_context(api, args.repo, args.version, args.candidate_tag, args.source_sha)
            candidate_dir = args.assets_dir.parent / 'candidate-download'
            candidate = _remote_evidence(api, args.repo, args.candidate_tag, candidate_dir)
            verify_release(api, args.candidate_tag, candidate, candidate_dir)
            candidate_archive = candidate_dir / f'usage-bridge-v{args.version}.zip'
        result = bundle(args.checkout, args.repo, args.version, args.tag, args.source_sha,
                        args.run_id, args.attempt, args.assets_dir,
                        candidate_archive=candidate_archive, candidate_tag=args.candidate_tag or None)
        _write(args.assets_dir.parent / 'predicate.json', {
            key: result[key] for key in ('repository', 'source_sha', 'zip_sha256', 'run_id', 'attempt')})
        _write(args.assets_dir.parent / 'extension.json',
               manifest_from_archive(args.assets_dir / f'usage-bridge-v{args.version}.zip'))
        return result, 0
    if args.command == 'collect':
        return collect(api, _read_json(args.evidence), assets_dir=args.assets_dir,
                       override_reason=args.override_reason, waived_checks=json.loads(args.waived_checks)), 0
    if args.command == 'complete-verification':
        result = _read_json(args.verification)
        if not all(result.get(key) is True for key in ('provenance', 'packaging_verified')):
            raise ReleasePolicyError('published assets have not passed cryptographic and packaging verification')
        gathered = collect_run_evidence(
            api, result['repository'], result['source_sha'], args.run_id, args.attempt,
            result['zip_sha256'], install_prefix='verify-install')
        result.update(runtime=gathered['runtime'], install_verified=True, commands_verified=True)
        return result, 0
    if args.command == 'submission-evidence':
        verification = _read_json(args.verification)
        binding = {key: verification[key] for key in ('repository', 'version', 'tag', 'source_sha', 'zip_sha256')}
        readme = api.request('GET', f"/repos/{binding['repository']}/contents/README.md?ref={binding['source_sha']}")
        return {'verification': verification, 'attestation_binding': binding,
                'readme_verified': readme.get('type') == 'file' and readme.get('size', 0) > 0,
                'install_verified': verification.get('install_verified') is True,
                'commands_verified': verification.get('commands_verified') is True,
                'attestations': {'real_project': os.environ.get('REAL_PROJECT', ''),
                                'documentation_review': os.environ.get('DOCUMENTATION_REVIEW') == 'true',
                                'security_review': os.environ.get('SECURITY_REVIEW', '')}}, 0
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
        if result['status'] == 'ready':
            result['tag'] = 'v' + args.version
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
        evidence = (_read_json(args.evidence) if args.evidence else
                    _remote_evidence(api, args.repo, args.tag, args.download_dir))
        result = verify_release(api, args.tag, evidence, args.download_dir)
        _write(args.download_dir / 'extension.json', manifest_from_archive(
            args.download_dir / f"usage-bridge-v{evidence['version']}.zip"))
        return result, 0
    if args.command == 'mergeback':
        verification = _read_json(args.verification)
        if not all(verification.get(key) is True for key in (
                'provenance', 'install_verified', 'commands_verified', 'packaging_verified')):
            raise ReleasePolicyError('merge-back requires successful published archive verification')
        if verification.get('build_sha') != args.source_sha:
            raise ReleasePolicyError('merge-back verification does not match the source SHA')
        if (verification.get('tag') != f'v{args.version}' or verification.get('repository') != args.repo):
            raise ReleasePolicyError('merge-back verification does not match the stable release')
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
            'source_sha': verification['source_sha'],
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


def _remote_evidence(api, repo: str, tag: str, directory: Path) -> dict:
    from urllib.parse import quote

    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-rc\.[1-9]\d*)?', tag):
        raise ReleasePolicyError('invalid release tag')
    release = api.request('GET', f'/repos/{repo}/releases/tags/{quote(tag, safe="")}')
    if release.get('draft') or release.get('tag_name') != tag:
        raise ReleasePolicyError('verification requires a published release with the requested tag')
    matches = [asset for asset in release.get('assets', []) if asset.get('name') == 'release-metadata.json']
    if len(matches) != 1:
        raise ReleasePolicyError('published release must have exactly one release-metadata.json')
    destination = directory / 'release-metadata.json'
    api.download_asset(matches[0]['url'], destination)
    evidence = _read_json(destination)
    if evidence.get('repository') != repo or evidence.get('tag') != tag:
        raise ReleasePolicyError('downloaded release metadata does not match requested repository/tag')
    return evidence


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
    except (ValueError, KeyError, TypeError) as exc:
        print('invalid release evidence: ' + str(exc), file=sys.stderr)
        return 2
    if getattr(args, 'output', None) is not None:
        _write(args.output, result)
    if os.environ.get('GITHUB_OUTPUT') and code == 0:
        outputs = {'tag': result.get('tag') or result.get('candidate_tag'),
                   'version': result.get('version'), 'digest': result.get('zip_sha256')}
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for key, value in outputs.items():
                if value is not None:
                    if '\n' in str(value) or '\r' in str(value):
                        raise ReleasePolicyError('invalid workflow output')
                    stream.write(f'{key}={value}\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
