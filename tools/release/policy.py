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
    numeric_tag = bool(re.fullmatch(re.escape(prefix) + r'[1-9]\d*', tag))
    if not (published and same_source and numeric_tag):
        raise ReleasePolicyError('candidate must be a published prerelease of this version at the release tip')


def require_metadata(data: dict) -> dict:
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ReleasePolicyError('unknown release metadata schema')
    missing = [key for key in _METADATA_FIELDS if key not in data]
    if missing:
        raise ReleasePolicyError('release metadata missing ' + ', '.join(missing))
    parse_version(str(data['version']))
    if data['repository'] != _POLICY['repository']:
        raise ReleasePolicyError('release repository is not the canonical repository')
    if not re.fullmatch(r'[0-9a-f]{40}', str(data['source_sha'])):
        raise ReleasePolicyError('release source must be a full commit SHA')
    if not re.fullmatch(r'[0-9a-f]{64}', str(data['zip_sha256'])):
        raise ReleasePolicyError('release archive must name a SHA-256 digest')
    version = re.escape(data['version'])
    if not re.fullmatch(r'v' + version + r'(?:-rc\.[1-9]\d*)?', str(data['tag'])):
        raise ReleasePolicyError('release tag does not match the manifest version')
    for name in ('run_id', 'attempt'):
        if type(data[name]) is not int or data[name] < 1:
            raise ReleasePolicyError('release metadata must name a positive ' + name)
    if not isinstance(data['checks'], list):
        raise ReleasePolicyError('release check evidence must be a list')
    return data


def require_runtime(records: list, source_sha: str, digest: str, *, run_id=None, attempt=None) -> list:
    """Validate concrete isolated installation outcomes, never caller success flags."""
    expected = {(platform, host) for platform in ('linux', 'windows') for host in ('minimum', 'current')}
    if not isinstance(records, list) or len(records) != len(expected):
        raise ReleasePolicyError('isolated runtime verification requires all four platform/host jobs')
    found = set()
    for record in records:
        if not isinstance(record, dict):
            raise ReleasePolicyError('malformed runtime verification record')
        pair = (record.get('platform'), record.get('host'))
        if pair not in expected or pair in found:
            raise ReleasePolicyError('runtime platform/host evidence is missing or duplicated')
        found.add(pair)
        if (record.get('source_sha') != source_sha or record.get('zip_sha256') != digest
                or record.get('isolated') is not True):
            raise ReleasePolicyError('runtime evidence is not bound to the isolated release archive')
        ref = str(record.get('host_ref') or '')
        if not re.fullmatch(r'(?:v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)|[0-9a-f]{40})', ref):
            raise ReleasePolicyError('runtime host must be pinned to a stable tag or commit')
        for name, required in (('run_id', run_id), ('attempt', attempt)):
            value = record.get(name)
            if type(value) is not int or value < 1 or (required is not None and value != required):
                raise ReleasePolicyError('runtime evidence has a stale run or attempt')
        commands = record.get('commands') or {}
        for name in ('install', 'checkpoint', 'capture', 'report', 'check', 'upgrade'):
            if type(commands.get(name)) is not int or commands[name] != 0:
                raise ReleasePolicyError('runtime command did not succeed: ' + name)
    return records


def require_verification(record: dict, expected: dict, *, runtime: bool = True) -> dict:
    if not isinstance(record, dict) or record.get('schema_version') != 1:
        raise ReleasePolicyError('missing verified release record')
    for name in ('repository', 'version', 'tag', 'source_sha', 'zip_sha256'):
        if record.get(name) != expected.get(name):
            raise ReleasePolicyError('verification does not match release ' + name)
    if record.get('build_sha') != expected.get('source_sha'):
        raise ReleasePolicyError('verification build does not match release source')
    for name in ('provenance', 'packaging_verified', 'catalog_verified', 'checksums_verified'):
        if record.get(name) is not True:
            raise ReleasePolicyError('missing mandatory release verification: ' + name)
    if runtime:
        require_runtime(record.get('runtime'), expected['source_sha'], expected['zip_sha256'],
                        run_id=expected.get('run_id'), attempt=expected.get('attempt'))
        if record.get('install_verified') is not True or record.get('commands_verified') is not True:
            raise ReleasePolicyError('missing isolated install/runtime verification')
    return record
