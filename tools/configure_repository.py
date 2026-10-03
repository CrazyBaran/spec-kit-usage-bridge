"""Inspect and apply protected-main configuration (development tooling only).

Usage: python tools/configure_repository.py main --repo CrazyBaran/spec-kit-usage-bridge [--apply]

Inspection (dry run) is the default. Mutation requires ``--apply`` and is only ever
permitted for the single repository named in ``ALLOWED_REPOSITORY``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from github_api import GitHubAPI, GitHubAPIError
from repository_policy import (
    REQUIRED_CONTEXTS,
    RULESET_NAME,
    RepositoryPolicyError,
    expected_main_state,
    plan_main_updates,
    verify_main_policy,
)

ALLOWED_REPOSITORY = 'CrazyBaran/spec-kit-usage-bridge'
ACTIONS_SLUG = 'github-actions'
DEFAULT_REPORT_DIR = 'build/repository-config'


def _report(repository: str, apply: bool) -> dict:
    return {
        'repository': repository,
        'mode': 'apply' if apply else 'dry-run',
        'actions_app_id': None,
        'planned': [],
        'applied': [],
        'verified': False,
        'problems': [],
        'errors': [],
    }


def _read_ruleset(api, base: str) -> dict | None:
    """Return the full owned ruleset (found by name), or None when absent."""
    for summary in api.pages(f'{base}/rulesets'):
        if summary.get('name') == RULESET_NAME:
            return api.request('GET', f'{base}/rulesets/{summary["id"]}')
    return None


def _gather(api, base: str, repository: dict) -> dict:
    rulesets = [api.request('GET', f'{base}/rulesets/{summary["id"]}')
                for summary in api.pages(f'{base}/rulesets')]
    return {
        'repository': repository,
        'rulesets': rulesets,
        'effective_rules': api.pages(f'{base}/rules/branches/main'),
        'check_runs': api.pages(f'{base}/commits/main/check-runs'),
    }


def _discover_actions_app(check_runs: list[dict]) -> tuple[int | None, list[str]]:
    """Find the single GitHub Actions app id behind the required checks."""
    apps = {}
    for run in check_runs:
        if run.get('name') in REQUIRED_CONTEXTS:
            app = run.get('app') or {}
            apps[app.get('id')] = app.get('slug')
    if not apps:
        return None, ['no check runs for the required contexts were found on main']
    if len(apps) != 1:
        return None, [f'required checks come from several apps: '
                      f'{sorted((str(i), str(s)) for i, s in apps.items())}']
    (app_id, slug), = apps.items()
    if slug != ACTIONS_SLUG or not isinstance(app_id, int):
        return None, [f'required checks come from app {slug!r} (id {app_id!r}), '
                      f'not {ACTIONS_SLUG!r}']
    return app_id, []


def _observe(api, base: str) -> dict:
    return {
        'repository': api.request('GET', base),
        'ruleset': _read_ruleset(api, base),
        'effective_rules': api.pages(f'{base}/rules/branches/main'),
    }


def _apply(api, report: dict, base: str, expected: dict) -> None:
    for operation in report['planned']:
        try:
            api.request(operation['method'], operation['path'], operation['payload'])
        except GitHubAPIError as error:
            report['errors'].append(str(error))
            return
        report['applied'].append(operation)
    report['problems'] = verify_main_policy(_observe(api, base), expected)
    report['verified'] = not report['problems']


def configure_main(api, repository: str, apply: bool) -> dict:
    """Inspect (default) or apply protected-main configuration and report the result."""
    report = _report(repository, apply)
    if repository != ALLOWED_REPOSITORY:
        report['errors'].append(
            f'refusing to operate on {repository!r}; only {ALLOWED_REPOSITORY!r} is permitted')
        return report
    base = f'repos/{repository}'
    try:
        repo = api.request('GET', base)
        blockers = []
        if not (repo.get('permissions') or {}).get('admin'):
            blockers.append('admin authority on the repository is required')
        if repo.get('default_branch') != 'main':
            blockers.append(f'default branch is {repo.get("default_branch")!r}, expected main')
        existing = _gather(api, base, repo)
        app_id, app_problems = _discover_actions_app(existing['check_runs'])
        report['actions_app_id'] = app_id
        blockers.extend(app_problems)
        if blockers:
            report['errors'].extend(blockers)
            return report
        try:
            report['planned'] = plan_main_updates(existing, app_id)
        except RepositoryPolicyError as error:
            report['errors'].extend(error.problems)
            return report
        expected = expected_main_state(app_id)
        if apply:
            _apply(api, report, base, expected)
        else:
            observed = {
                'repository': repo,
                'ruleset': next((r for r in existing['rulesets']
                                 if r.get('name') == RULESET_NAME), None),
                'effective_rules': existing['effective_rules'],
            }
            report['problems'] = verify_main_policy(observed, expected)
            report['verified'] = not report['problems']
    except GitHubAPIError as error:
        report['errors'].append(str(error))
        report['verified'] = False
    return report


def _write_report(report: dict, report_dir: str) -> Path:
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = directory / f'main-{stamp}.json'
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return path


def main(argv=None, api=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    main_parser = sub.add_parser('main', help='configure protection for main')
    main_parser.add_argument('--repo', required=True, help='owner/name')
    main_parser.add_argument('--apply', action='store_true',
                             help='perform the planned writes (default: inspect only)')
    main_parser.add_argument('--report-dir', default=DEFAULT_REPORT_DIR)
    args = parser.parse_args(argv)

    report = configure_main(api or GitHubAPI(), args.repo, args.apply)
    text = json.dumps(report, indent=2)
    print(text)
    _write_report(report, args.report_dir)
    if report['errors']:
        return 1
    return 0 if (not args.apply or report['verified']) else 1


if __name__ == '__main__':
    sys.exit(main())
