"""Trusted workflow boundary: build bytes and collect current-attempt evidence."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from build_release import build
from release.artifacts import runtime_members, safe_source, validate_archive, validate_release_assets, write_catalog
from release.context import decide_gate
from release.policy import ACTIONS_APP_ID, WAIVABLE_CHECKS, ReleasePolicyError, parse_version

COMMANDS = ('install', 'checkpoint', 'capture', 'report', 'check', 'upgrade')


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(checkout: Path, repo: str, version: str, tag: str, source_sha: str,
           run_id: int, attempt: int, assets_dir: Path, *, candidate_archive: Path | None = None,
           candidate_tag: str | None = None) -> dict:
    parse_version(version)
    if not re.fullmatch(r'[0-9a-f]{40}', source_sha):
        raise ReleasePolicyError('source SHA must be a full commit SHA')
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=checkout, check=True,
                          capture_output=True, text=True).stdout.strip()
    if head != source_sha:
        raise ReleasePolicyError('checkout SHA does not match requested source SHA')
    dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=checkout,
                           check=True, capture_output=True, text=True).stdout
    if dirty.strip():
        raise ReleasePolicyError('release checkout must be clean')
    if tag != f'v{version}' and not re.fullmatch(r'v' + re.escape(version) + r'-rc\.[1-9]\d*', tag):
        raise ReleasePolicyError('tag does not match release version')
    members = runtime_members(checkout)
    assets_dir.mkdir(parents=True, exist_ok=True)
    if candidate_archive:
        archive = assets_dir / f'usage-bridge-v{version}.zip'
        shutil.copyfile(candidate_archive, archive)
        write_catalog(checkout, archive, version, tag, f'https://github.com/{repo}', assets_dir / 'catalog.json')
    else:
        archive, _ = build(checkout, version, assets_dir, f'https://github.com/{repo}', release_tag=tag)
        (assets_dir / 'RELEASE_NOTES.md').unlink()
    validate_archive(archive, members)
    metadata = {
        'schema_version': 1, 'repository': repo, 'version': version, 'tag': tag,
        'source_sha': source_sha, 'run_id': run_id, 'attempt': attempt, 'zip_sha256': digest(archive),
        'candidate_tag': candidate_tag or (tag if '-rc.' in tag else None),
        'checks': [], 'override': None, 'verification': None, 'members': list(members),
        'changelog': safe_source(checkout, 'CHANGELOG.md').read_text(encoding='utf-8-sig'),
    }
    write_json(assets_dir / 'release-metadata.json', metadata)
    write_checksums(assets_dir)
    return metadata


def write_checksums(assets_dir: Path) -> None:
    names = sorted(path.name for path in assets_dir.iterdir() if path.is_file() and path.name != 'SHA256SUMS')
    (assets_dir / 'SHA256SUMS').write_text(
        ''.join(f'{digest(assets_dir / name)}  {name}\n' for name in names), encoding='utf-8')


def collect_run_evidence(api, repository: str, source_sha: str, run_id: int, attempt: int,
                         digest: str, override_reason: str = '', waived_checks=(), host_refs=None,
                         *, install_prefix: str = 'install') -> dict:
    """Read only this attempt; old successful attempts and caller claims never count."""
    base = f'/repos/{repository}/actions/runs/{int(run_id)}'
    run = api.request('GET', f'{base}/attempts/{int(attempt)}')
    manual_detection = install_prefix == 'verify-install' and run.get('event') == 'release'
    if ((not manual_detection and (run.get('head_branch') != 'main' or run.get('event') != 'workflow_dispatch'))
            or run.get('head_repository', {}).get('full_name') != repository
            or run.get('path', '').split('@')[0] not in {
                '.github/workflows/release.yml', '.github/workflows/promote-release.yml',
                '.github/workflows/release-follow-through.yml', '.github/workflows/verify-release.yml'}
            or int(run.get('run_attempt', 0)) != int(attempt)):
        raise ReleasePolicyError('evidence must come from the trusted main workflow run attempt')
    jobs = api.pages(f'{base}/attempts/{int(attempt)}/jobs')
    by_name = {}
    for job in jobs:
        name = str(job.get('name', '')).rsplit(' / ', 1)[-1]
        if name in by_name:
            raise ReleasePolicyError('ambiguous job evidence for ' + name)
        by_name[name] = job
    checks = []
    runtime = []
    hosts = host_refs or {'minimum': 'v1.0.12', 'current': 'v1.0.12'}
    for os_name in ('ubuntu-latest', 'windows-latest'):
        for host in ('minimum', 'current'):
            name = f'{install_prefix} ({os_name}, {host})'
            job = by_name.get(name, {})
            if job.get('status') != 'completed' or job.get('conclusion') != 'success':
                raise ReleasePolicyError('mandatory install/runtime check did not succeed: ' + name)
            runtime.append({
                'source_sha': source_sha, 'zip_sha256': digest, 'isolated': True,
                'host': host, 'host_ref': hosts[host],
                'platform': 'linux' if os_name == 'ubuntu-latest' else 'windows',
                'commands': dict.fromkeys(COMMANDS, 0), 'run_id': run_id, 'attempt': attempt,
                'url': job.get('html_url', ''),
            })
    for name in WAIVABLE_CHECKS:
        job = by_name.get(name)
        if job:
            checks.append({'name': name, 'source_sha': source_sha, 'run_id': run_id, 'attempt': attempt,
                           'app_id': ACTIONS_APP_ID, 'status': job['status'], 'conclusion': job.get('conclusion'),
                           'url': job.get('html_url', '')})
    waived = tuple(waived_checks)
    if any(name not in WAIVABLE_CHECKS for name in waived):
        raise ReleasePolicyError('only quality checks may be waived')
    approvals = []
    if override_reason.strip() and waived:
        # The approval job runs only after install and CI settle. Its completion ties
        # a run-level approval to this attempt; history alone could be an old retry.
        approval_job = by_name.get('override', {})
        if approval_job.get('status') == 'completed' and approval_job.get('conclusion') == 'success':
            history = api.request('GET', base + '/approvals')
            for review in history:
                if review.get('state') != 'approved':
                    continue
                if any(env.get('name') == 'release-override' for env in review.get('environments', [])):
                    approver = review.get('user', {}).get('login')
                    if approver:
                        approvals.append({'environment': 'release-override', 'approver': approver,
                                          'run_id': run_id, 'attempt': attempt,
                                          'source_sha': source_sha, 'digest': digest})
    return {'source_sha': source_sha, 'digest': digest, 'required': list(WAIVABLE_CHECKS),
            'checks': checks, 'runtime': runtime, 'approvals': approvals,
            'override': {'requested': bool(override_reason), 'reason': override_reason,
                         'waived_checks': list(waived), 'run_id': run_id, 'attempt': attempt,
                         'source_sha': source_sha}}


def collect(api, evidence: dict, *, assets_dir: Path | None = None,
            override_reason: str = '', waived_checks=()) -> dict:
    gathered = collect_run_evidence(api, evidence['repository'], evidence['source_sha'], evidence['run_id'],
                                   evidence['attempt'], evidence['zip_sha256'], override_reason, waived_checks)
    decision = decide_gate(gathered)
    if not decision['allowed']:
        raise ReleasePolicyError('; '.join(decision['blockers']))
    result = dict(evidence, checks=gathered['checks'], override=gathered['override'],
                  approvals=gathered['approvals'], gate=decision)
    result['verification'] = {
        key: result[key] for key in ('repository', 'version', 'tag', 'source_sha', 'zip_sha256')}
    result['verification'].update(schema_version=1, build_sha=result['source_sha'], runtime=gathered['runtime'],
                                  install_verified=True, commands_verified=True)
    if assets_dir:
        archive = assets_dir / f"usage-bridge-v{result['version']}.zip"
        api.verify_attestation(archive, result['repository'], result['source_sha'],
                               run_id=result['run_id'], attempt=result['attempt'])
        result['verification'].update(provenance=True, packaging_verified=True, archive_verified=True,
                                      catalog_verified=True, checksums_verified=True)
        write_json(assets_dir / 'release-metadata.json', result)
        write_checksums(assets_dir)
        validate_release_assets({path.name: path for path in assets_dir.iterdir() if path.is_file()}, result)
    return result


def manifest_from_archive(archive: Path) -> dict:
    import zipfile
    with zipfile.ZipFile(archive) as zipped:
        return yaml.safe_load(zipped.read('usage-bridge/extension.yml'))
