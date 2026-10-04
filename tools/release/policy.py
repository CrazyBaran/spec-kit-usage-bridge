"""Pure release-gate decisions. No network and no credential access."""
from __future__ import annotations

import json
import re
from pathlib import Path

from release.models import CheckResult, GateDecision, OverrideRequest

_VERSION = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')
_METADATA_FIELDS = (
    'schema_version', 'repository', 'version', 'tag', 'source_sha', 'run_id', 'attempt',
    'zip_sha256', 'candidate_tag', 'checks', 'override', 'verification',
)
_POLICY_PATH = Path(__file__).resolve().parents[2] / '.github' / 'release-policy.json'
_WAIVABLE_CONCLUSIONS = frozenset({'failure', 'timed_out', 'action_required', 'startup_failure'})


class ReleasePolicyError(ValueError):
    """A version, candidate, or metadata value violates release policy."""


def load_release_policy(path: Path | None = None) -> dict:
    return json.loads((path or _POLICY_PATH).read_text(encoding='utf-8'))


_POLICY = load_release_policy()
ACTIONS_APP_ID = int(_POLICY['actions_app_id'])
WAIVABLE_CHECKS = tuple(_POLICY['required_checks'])


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ReleasePolicyError('version must be plain major.minor.patch without a prefix or leading zeros')
    return tuple(int(part) for part in match.groups())


def next_candidate_tag(version: str, existing_tags: tuple[str, ...]) -> str:
    parse_version(version)
    prefix = f'v{version}-rc.'
    numbers = []
    for tag in existing_tags:
        if not tag.startswith(prefix):
            continue
        suffix = tag[len(prefix):]
        if suffix.isdigit() and not (len(suffix) > 1 and suffix.startswith('0')):
            numbers.append(int(suffix))
    return f'{prefix}{max(numbers, default=0) + 1}'


def _can_waive(name: str, check: CheckResult, override: OverrideRequest, source_sha: str) -> bool:
    return bool(
        name in WAIVABLE_CHECKS
        and name in override.waived_checks
        and override.requested
        and override.approved
        and override.reason.strip()
        and override.approver
        and override.source_sha == source_sha
        and check.source_sha == source_sha
        and check.app_id == ACTIONS_APP_ID
        and override.run_id == check.run_id
        and override.attempt == check.attempt
        and check.status == 'completed'
        and check.conclusion in _WAIVABLE_CONCLUSIONS
    )


def evaluate_checks(checks: tuple[CheckResult, ...], required: tuple[str, ...], source_sha: str,
                    override: OverrideRequest) -> GateDecision:
    grouped: dict[str, list[CheckResult]] = {}
    for check in checks:
        grouped.setdefault(check.name, []).append(check)
    blockers: list[str] = []
    waived: list[str] = []
    for name in required:
        relevant = [
            check for check in grouped.get(name, [])
            if check.source_sha == source_sha and check.app_id == ACTIONS_APP_ID
        ]
        if not relevant:
            blockers.append(f'missing {name}')
            continue
        for check in relevant:
            if check.status == 'completed' and check.conclusion == 'success':
                continue
            if _can_waive(name, check, override, source_sha):
                if name not in waived:
                    waived.append(name)
                continue
            blockers.append(f'{name} is {check.status}/{check.conclusion}')
            break
    return GateDecision(not blockers, tuple(blockers), tuple(waived))


def require_candidate(version: str, tip_sha: str, candidate: dict | None) -> None:
    parse_version(version)
    if candidate is None:
        raise ReleasePolicyError('no published candidate can be overridden')
    published = candidate.get('draft') is False and candidate.get('prerelease') is True
    same_source = candidate.get('version') == version and candidate.get('sha') == tip_sha
    tag = str(candidate.get('tag') or '')
    prefix = f'v{version}-rc.'
    numeric_tag = tag.startswith(prefix) and tag[len(prefix):].isdigit()
    if not (published and same_source and numeric_tag):
        raise ReleasePolicyError('candidate must be a published prerelease of this version at the release tip')


def require_metadata(data: dict) -> dict:
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ReleasePolicyError('unknown release metadata schema')
    missing = [key for key in _METADATA_FIELDS if key not in data]
    if missing:
        raise ReleasePolicyError('release metadata missing ' + ', '.join(missing))
    parse_version(str(data['version']))
    return data
