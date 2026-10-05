"""Assemble release evidence without creating tags, releases, or issues."""
from __future__ import annotations

from github_api import GitHubAPIError
from release.models import CheckResult, OverrideRequest
from release.policy import (
    WAIVABLE_CHECKS,
    ReleasePolicyError,
    evaluate_checks,
    next_candidate_tag,
    parse_version,
    require_candidate,
)

_OVERRIDE_ENVIRONMENT = 'release-override'


def release_branch_sha(api, repo: str, version: str) -> str:
    body = api.request('GET', f'/repos/{repo}/git/ref/heads/release/{version}')
    obj = body.get('object') or {}
    if obj.get('type') not in (None, 'commit') or not obj.get('sha'):
        raise ReleasePolicyError('release branch does not resolve to a commit')
    return str(obj['sha'])


def resolve_tag_sha(api, repo: str, tag: str, *, missing_ok: bool = False) -> str | None:
    try:
        body = api.request('GET', f'/repos/{repo}/git/ref/tags/{tag}')
    except GitHubAPIError as exc:
        if missing_ok and exc.status == 404:
            return None
        raise
    obj = body.get('object') or {}
    for _ in range(10):
        if obj.get('type') == 'commit' and obj.get('sha'):
            return str(obj['sha'])
        if obj.get('type') != 'tag' or not obj.get('sha'):
            break
        body = api.request('GET', f"/repos/{repo}/git/tags/{obj['sha']}")
        obj = body.get('object') or {}
    raise ReleasePolicyError('release tag does not resolve to a commit')


def candidate_context(api, repo: str, version: str, source_sha: str) -> dict:
    parse_version(version)
    tags = tuple(
        str(item.get('tag_name'))
        for item in api.pages(f'/repos/{repo}/releases')
        if item.get('tag_name')
    )
    return {
        'status': 'context',
        'repository': repo,
        'version': version,
        'source_sha': source_sha,
        'candidate_tag': next_candidate_tag(version, tags),
        'published': False,
    }


def promotion_context(api, repo: str, version: str, candidate_tag: str, source_sha: str) -> dict:
    parse_version(version)
    if not str(candidate_tag or '').strip():
        return {
            'status': 'manual_publication',
            'repository': repo,
            'version': version,
            'source_sha': source_sha,
            'submit': False,
            'merge': False,
            'blockers': ['stable release has no candidate'],
        }
    tip = release_branch_sha(api, repo, version)
    if tip != source_sha:
        raise ReleasePolicyError('release branch moved after validation')
    match = next((
        item for item in api.pages(f'/repos/{repo}/releases')
        if item.get('tag_name') == candidate_tag
    ), None)
    candidate = None
    if match is not None:
        candidate = {
            'draft': match.get('draft'),
            'prerelease': match.get('prerelease'),
            'version': version,
            'sha': resolve_tag_sha(api, repo, candidate_tag),
            'tag': candidate_tag,
        }
    require_candidate(version, tip, candidate)
    return {
        'status': 'ready',
        'repository': repo,
        'version': version,
        'candidate_tag': candidate_tag,
        'source_sha': source_sha,
        'submit': False,
        'merge': False,
        'blockers': [],
    }


def bind_override(payload: dict, *, source_sha: str, digest: str) -> OverrideRequest:
    """Environment approval history is the only approval. A JSON flag is not."""
    raw = payload.get('override') or {}
    requested_run = int(raw.get('run_id') or 0)
    requested_attempt = int(raw.get('attempt') or 0)
    approver = None
    for approval in payload.get('approvals') or []:
        same_attempt = (
            int(approval.get('run_id') or 0) == requested_run
            and int(approval.get('attempt') or 0) == requested_attempt
        )
        if (
            approval.get('environment') == _OVERRIDE_ENVIRONMENT
            and approval.get('source_sha') == source_sha
            and approval.get('digest') == digest
            and same_attempt
            and approval.get('approver')
        ):
            approver = str(approval['approver'])
            break
    return OverrideRequest(
        requested=bool(raw.get('requested')),
        reason=str(raw.get('reason') or ''),
        waived_checks=tuple(raw.get('waived_checks') or ()),
        run_id=requested_run,
        attempt=requested_attempt,
        source_sha=str(raw.get('source_sha') or ''),
        approved=approver is not None,
        approver=approver,
    )


def decide_gate(payload: dict) -> dict:
    source_sha = str(payload.get('source_sha') or '')
    digest = str(payload.get('digest') or '')
    if not source_sha or not digest:
        raise ReleasePolicyError('gate evidence must name the source SHA and artifact digest')
    checks = tuple(
        CheckResult(
            name=item['name'],
            source_sha=item['source_sha'],
            run_id=int(item['run_id']),
            attempt=int(item['attempt']),
            app_id=int(item.get('app_id') or 0),
            status=item['status'],
            conclusion=item.get('conclusion'),
            url=str(item.get('url') or ''),
        )
        for item in payload.get('checks') or []
    )
    override = bind_override(payload, source_sha=source_sha, digest=digest)
    required = tuple(payload.get('required') or WAIVABLE_CHECKS)
    decision = evaluate_checks(checks, required, source_sha, override)
    return {
        'allowed': decision.allowed,
        'blockers': list(decision.blockers),
        'waived': list(decision.waived),
        'approved': override.approved,
    }
