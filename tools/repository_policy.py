"""Protected-main policy and safe reconciliation planning (development tooling only).

Pure functions: no I/O and no GitHub client. A caller gathers ``existing`` from the
API, applies the planned operations, reads state back and calls ``verify_main_policy``.
"""
from __future__ import annotations

import copy
import fnmatch

RULESET_NAME = 'usage-bridge-main'
MAIN_REF = 'refs/heads/main'
REQUIRED_CONTEXTS = (
    'lint',
    'test (ubuntu-latest, 3.9)',
    'test (ubuntu-latest, 3.x)',
    'test (windows-latest, 3.9)',
    'test (windows-latest, 3.x)',
    'integration (ubuntu-latest)',
    'integration (windows-latest)',
)
REQUIRED_EFFECTIVE_TYPES = (
    'pull_request', 'required_status_checks', 'deletion', 'non_fast_forward')
REPOSITORY_SETTINGS = ('allow_auto_merge', 'allow_merge_commit')
# Booleans where True is the weaker setting; every other boolean is stricter when True.
WEAKER_WHEN_TRUE = ('do_not_enforce_on_create',)
# pull_request parameters forced to the spec value on the owned ruleset (solo merge).
FORCED_PARAMS = ('required_approving_review_count', 'require_code_owner_review',
                 'require_last_push_approval')
# Rule types that block a solo maintainer merging; dropped from the owned ruleset.
BLOCKING_RULE_TYPES = ('required_linear_history', 'update', 'merge_queue',
                       'required_deployments')
# GitHub's server-side default when allowed_merge_methods is absent from a read-back.
DEFAULT_MERGE_METHODS = ('merge', 'squash', 'rebase')


class RepositoryPolicyError(Exception):
    """Policy cannot be applied safely; ``problems`` lists every blocker found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__('; '.join(self.problems))


def main_ruleset(actions_app_id: int) -> dict:
    """Return the POST/PUT payload for the owned ruleset protecting main."""
    return {
        'name': RULESET_NAME,
        'target': 'branch',
        'enforcement': 'active',
        'bypass_actors': [],
        'conditions': {'ref_name': {'include': [MAIN_REF], 'exclude': []}},
        'rules': [
            {'type': 'deletion'},
            {'type': 'non_fast_forward'},
            {'type': 'pull_request', 'parameters': {
                'required_approving_review_count': 0,
                'dismiss_stale_reviews_on_push': False,
                'require_code_owner_review': False,
                'require_last_push_approval': False,
                'required_review_thread_resolution': True,
                'allowed_merge_methods': ['merge', 'squash', 'rebase'],
            }},
            {'type': 'required_status_checks', 'parameters': {
                'strict_required_status_checks_policy': True,
                'do_not_enforce_on_create': False,
                'required_status_checks': [
                    {'context': name, 'integration_id': actions_app_id}
                    for name in REQUIRED_CONTEXTS],
            }},
        ],
    }


def expected_main_state(actions_app_id: int) -> dict:
    """Return the repository settings and ruleset that must hold after applying."""
    return {
        'repository': {'allow_auto_merge': True, 'allow_merge_commit': True},
        'ruleset': main_ruleset(actions_app_id),
    }


# --- planning -------------------------------------------------------------


def _check_evidence(check_runs: list[dict], actions_app_id: int) -> list[str]:
    problems = []
    for context in REQUIRED_CONTEXTS:
        runs = [run for run in check_runs if run.get('name') == context]
        if not runs:
            problems.append(f'no check run named {context!r} found on main')
            continue
        apps = {(run.get('app') or {}).get('id') for run in runs}
        if apps != {actions_app_id}:
            problems.append(
                f'check {context!r} is not exclusively produced by app {actions_app_id} '
                f'(seen app ids: {sorted(str(a) for a in apps)})')
    return problems


def _matches_main(pattern: str) -> bool:
    if pattern in ('~DEFAULT_BRANCH', '~ALL'):
        return True
    return fnmatch.fnmatchcase(MAIN_REF, pattern)


def _applies_to_main(ruleset: dict) -> bool:
    if ruleset.get('target') != 'branch' or ruleset.get('enforcement') != 'active':
        return False
    ref_name = (ruleset.get('conditions') or {}).get('ref_name') or {}
    included = any(_matches_main(p) for p in ref_name.get('include', []))
    excluded = any(_matches_main(p) for p in ref_name.get('exclude', []))
    return included and not excluded


def _blockers(rule: dict, origin: str) -> list[str]:
    rule_type = rule.get('type')
    params = rule.get('parameters') or {}
    if rule_type == 'required_linear_history':
        return [f'{origin} requires linear history, which breaks merge-commit releases']
    if rule_type in ('update', 'merge_queue', 'required_deployments'):
        return [f'{origin} has a {rule_type} rule, which blocks the sole maintainer '
                f'merging their own pull request']
    if rule_type != 'pull_request':
        return []
    problems = []
    if (params.get('required_approving_review_count') or 0) > 0:
        problems.append(
            f'{origin} requires approving reviews, which blocks the sole maintainer')
    if params.get('require_code_owner_review'):
        problems.append(f'{origin} requires code owner review, which blocks the sole maintainer')
    if params.get('require_last_push_approval'):
        problems.append(
            f'{origin} requires last-push approval, which blocks the sole maintainer')
    if params.get('required_reviewers'):
        problems.append(f'{origin} has required reviewers, which blocks the sole maintainer')
    methods = params.get('allowed_merge_methods')
    if methods is not None and 'merge' not in methods:
        problems.append(f'{origin} does not allow merge-commit merges')
    return problems


def _classic_blockers(classic: dict | None) -> list[str]:
    """Blockers in classic branch protection (never modified by this tool)."""
    if not classic:
        return []
    origin = 'classic branch protection on main'
    problems = []
    reviews = classic.get('required_pull_request_reviews') or {}
    if (reviews.get('required_approving_review_count') or 0) > 0:
        problems.append(
            f'{origin} requires approving reviews, which blocks the sole maintainer')
    if reviews.get('require_code_owner_reviews'):
        problems.append(f'{origin} requires code owner reviews, which blocks the sole maintainer')
    if reviews.get('require_last_push_approval'):
        problems.append(
            f'{origin} requires last-push approval, which blocks the sole maintainer')
    if (classic.get('required_linear_history') or {}).get('enabled'):
        problems.append(
            f'{origin} requires linear history, which breaks merge-commit releases')
    return problems


def _incompatible_rules(existing: dict) -> list[str]:
    problems: list[str] = _classic_blockers(existing.get('classic_protection'))
    owned_ids = {r.get('id') for r in existing.get('rulesets', [])
                 if r.get('name') == RULESET_NAME}
    for ruleset in existing.get('rulesets', []):
        if ruleset.get('name') != RULESET_NAME and _applies_to_main(ruleset):
            origin = f'ruleset {ruleset.get("name")!r}'
            for rule in ruleset.get('rules', []):
                problems.extend(_blockers(rule, origin))
    for rule in existing.get('effective_rules', []):
        if rule.get('ruleset_id') in owned_ids:
            continue
        origin = (f'effective rule from {rule.get("ruleset_source_type")} '
                  f'{rule.get("ruleset_source")} (ruleset {rule.get("ruleset_id")})')
        problems.extend(_blockers(rule, origin))
    return list(dict.fromkeys(problems))


def _repository_patch(repository: dict) -> dict:
    return {name: True for name in REPOSITORY_SETTINGS if repository.get(name) is not True}


def _merge_params(existing: dict, desired: dict) -> dict:
    merged = copy.deepcopy(existing)
    for key, value in desired.items():
        if key not in existing:
            merged[key] = copy.deepcopy(value)
        elif key == 'required_status_checks':
            wanted = {c['context'] for c in value}
            kept = [c for c in existing[key] if c.get('context') not in wanted]
            merged[key] = kept + copy.deepcopy(value)
        elif key == 'allowed_merge_methods':
            methods = list(existing[key] or [])
            merged[key] = methods if 'merge' in methods else methods + ['merge']
        elif key in FORCED_PARAMS:
            merged[key] = value
        elif isinstance(value, bool):
            merged[key] = bool(existing[key] and value if key in WEAKER_WHEN_TRUE
                               else existing[key] or value)
    if merged.get('required_reviewers'):
        merged['required_reviewers'] = []
    return merged


def _merge_rules(existing: list[dict], desired: list[dict]) -> list[dict]:
    by_type = {rule['type']: rule for rule in existing
               if rule['type'] not in BLOCKING_RULE_TYPES}
    merged = []
    for rule in desired:
        current = by_type.pop(rule['type'], None)
        if current is None:
            merged.append(copy.deepcopy(rule))
        elif 'parameters' in rule:
            merged.append({'type': rule['type'], 'parameters': _merge_params(
                current.get('parameters') or {}, rule['parameters'])})
        else:
            merged.append(copy.deepcopy(current))
    merged.extend(copy.deepcopy(rule) for rule in by_type.values())
    return merged


def _union_ruleset(owned: dict, desired: dict) -> dict:
    conditions = copy.deepcopy(owned.get('conditions') or {})
    ref_name = conditions.setdefault('ref_name', {})
    include = list(ref_name.get('include', []))
    if MAIN_REF not in include:
        include.append(MAIN_REF)
    ref_name['include'] = include
    ref_name['exclude'] = [p for p in ref_name.get('exclude', [])
                           if not _matches_main(p)]
    return {
        'name': RULESET_NAME,
        'target': 'branch',
        'enforcement': 'active',
        'bypass_actors': [],
        'conditions': conditions,
        'rules': _merge_rules(owned.get('rules', []), desired['rules']),
    }


def _normalize_rule(rule: dict) -> dict:
    params = copy.deepcopy(rule.get('parameters'))
    if params is None:
        return {'type': rule['type']}
    if rule['type'] == 'required_status_checks':
        params.setdefault('do_not_enforce_on_create', False)
    elif rule['type'] == 'pull_request':
        if params.get('allowed_merge_methods') is None:
            params['allowed_merge_methods'] = list(DEFAULT_MERGE_METHODS)
    checks = params.get('required_status_checks')
    if checks is not None:
        params['required_status_checks'] = sorted(
            checks, key=lambda c: (c.get('context', ''), str(c.get('integration_id'))))
    return {'type': rule['type'], 'parameters': params}


def _normalize(ruleset: dict) -> dict:
    ref_name = (ruleset.get('conditions') or {}).get('ref_name') or {}
    return {
        'name': ruleset.get('name'),
        'target': ruleset.get('target'),
        'enforcement': ruleset.get('enforcement'),
        'bypass_actors': ruleset.get('bypass_actors') or [],
        'include': sorted(ref_name.get('include', [])),
        'exclude': sorted(ref_name.get('exclude', [])),
        'rules': sorted((_normalize_rule(r) for r in ruleset.get('rules', [])),
                        key=lambda r: r['type']),
    }


def plan_main_updates(existing: dict, actions_app_id: int) -> list[dict]:
    """Return the minimal API operations that bring main to the desired policy.

    Raises ``RepositoryPolicyError`` when check evidence is missing or ambiguous, when
    the owned ruleset is duplicated, or when any rule blocks solo merge-commit merges.
    """
    problems = _check_evidence(existing.get('check_runs', []), actions_app_id)
    problems.extend(_incompatible_rules(existing))
    owned = [r for r in existing.get('rulesets', []) if r.get('name') == RULESET_NAME]
    if len(owned) > 1:
        problems.append(
            f'{len(owned)} rulesets are named {RULESET_NAME!r}; resolve the duplicates')
    if problems:
        raise RepositoryPolicyError(problems)

    repository = existing['repository']
    base = f'repos/{repository["full_name"]}'
    operations = []
    patch = _repository_patch(repository)
    if patch:
        operations.append({'method': 'PATCH', 'path': base, 'payload': patch})

    desired = main_ruleset(actions_app_id)
    if not owned:
        operations.append(
            {'method': 'POST', 'path': f'{base}/rulesets', 'payload': desired})
    else:
        union = _union_ruleset(owned[0], desired)
        if _normalize(union) != _normalize(owned[0]):
            operations.append({
                'method': 'PUT', 'path': f'{base}/rulesets/{owned[0]["id"]}',
                'payload': union})
    return operations


# --- verification ---------------------------------------------------------


def _check_pairs(checks: list[dict]) -> set:
    return {(c.get('context'), c.get('integration_id')) for c in checks}


def _verify_params(rule_type: str, observed: dict, expected: dict) -> list[str]:
    problems = []
    for key, want in expected.items():
        have = observed.get(key)
        if key == 'required_status_checks':
            for context, integration in sorted(
                    _check_pairs(want) - _check_pairs(have or []), key=str):
                problems.append(
                    f'{rule_type}: required check {context!r} is not bound to '
                    f'integration {integration}')
        elif key == 'allowed_merge_methods':
            if 'merge' not in (DEFAULT_MERGE_METHODS if have is None else have):
                problems.append(f'{rule_type}: {key} must allow merge, got {have!r}')
        elif key in FORCED_PARAMS and key != 'required_approving_review_count':
            if have:
                problems.append(f'{rule_type}: {key} must be false, got {have!r}')
        elif key == 'do_not_enforce_on_create':
            if bool(have):
                problems.append(f'{rule_type}: {key} must be false')
        elif isinstance(want, bool) and key not in WEAKER_WHEN_TRUE:
            if want and have is not True:
                problems.append(f'{rule_type}: {key} must be true')
            if not want and have is None:
                problems.append(f'{rule_type}: {key} is missing')
        elif have != want:
            problems.append(f'{rule_type}: {key} is {have!r}, expected {want!r}')
    return problems


def _verify_ruleset(observed: dict | None, expected: dict) -> list[str]:
    if not observed:
        return [f'ruleset {expected["name"]!r} is missing']
    problems = []
    for key in ('name', 'target', 'enforcement'):
        if observed.get(key) != expected[key]:
            problems.append(
                f'ruleset {key} is {observed.get(key)!r}, expected {expected[key]!r}')
    if observed.get('bypass_actors'):
        problems.append('ruleset has bypass actors; none are allowed')
    ref_name = (observed.get('conditions') or {}).get('ref_name') or {}
    for ref in expected['conditions']['ref_name']['include']:
        if ref not in ref_name.get('include', []):
            problems.append(f'ruleset does not include {ref}')
    if ref_name.get('exclude'):
        problems.append(f'ruleset excludes refs: {ref_name["exclude"]!r}')
    observed_rules = {r['type']: r for r in observed.get('rules', [])}
    for rule_type in BLOCKING_RULE_TYPES:
        if rule_type in observed_rules:
            problems.append(f'ruleset has a {rule_type} rule, which blocks the sole maintainer')
    for rule in expected['rules']:
        found = observed_rules.get(rule['type'])
        if found is None:
            problems.append(f'ruleset is missing the {rule["type"]} rule')
        elif 'parameters' in rule:
            problems.extend(_verify_params(
                rule['type'], found.get('parameters') or {}, rule['parameters']))
    return problems


def verify_main_policy(observed: dict, expected: dict) -> list[str]:
    """Compare read-back state with ``expected_main_state``; ``[]`` means verified.

    Server-generated fields are ignored and observed state may be stricter than
    expected (extra rules, extra contexts, extra true booleans).
    """
    problems = []
    repository = observed.get('repository') or {}
    for name, want in expected['repository'].items():
        if repository.get(name) != want:
            problems.append(f'repository {name} is {repository.get(name)!r}, expected {want!r}')
    problems.extend(_verify_ruleset(observed.get('ruleset'), expected['ruleset']))
    problems.extend(_classic_blockers(observed.get('classic_protection')))
    effective_types = {r.get('type') for r in observed.get('effective_rules', [])}
    for rule_type in REQUIRED_EFFECTIVE_TYPES:
        if rule_type not in effective_types:
            problems.append(f'effective rules on main lack {rule_type}')
    return problems


RELEASE_ENVIRONMENTS = ('release-publish', 'release-override', 'catalog-submit')
TAG_RULESET_NAME = 'usage-bridge-tags'
REVIEWED_ENVIRONMENTS = ('release-override', 'catalog-submit')
IMMUTABLE_RELEASE_UI = (
    'Enable immutable releases with PUT repos/CrazyBaran/spec-kit-usage-bridge/immutable-releases '
    'or in repository settings, then verify the setting through its GET endpoint.'
)


def _environment_payload(name: str, reviewer_id: int) -> dict:
    payload = {
        'wait_timer': 0,
        'prevent_self_review': False,
        'can_admins_bypass': False,
        'reviewers': [],
        'deployment_branch_policy': {'protected_branches': True, 'custom_branch_policies': False},
    }
    if name in REVIEWED_ENVIRONMENTS:
        payload['reviewers'] = [{'type': 'User', 'id': reviewer_id}]
    return payload


def release_settings_plan(existing: dict, release_app_id: int, reviewer_id: int) -> list[dict]:
    """Plan tag authority and release environments. Never grants a main bypass."""
    full_name = ((existing.get('repository') or {}).get('full_name')
                 or 'CrazyBaran/spec-kit-usage-bridge')
    base = f'repos/{full_name}'
    owned = [item for item in existing.get('rulesets') or [] if item.get('name') == TAG_RULESET_NAME]
    if len(owned) > 1:
        raise RepositoryPolicyError(['duplicate owned tag rulesets; resolve them before applying'])
    owned_tags = owned[0] if owned else None
    tag_payload = {
        'name': TAG_RULESET_NAME,
        'target': 'tag',
        'enforcement': 'active',
        'bypass_actors': [{
            'actor_id': release_app_id,
            'actor_type': 'Integration',
            'bypass_mode': 'always',
        }],
        'conditions': {'ref_name': {'include': ['refs/tags/v*'], 'exclude': []}},
        'rules': [{'type': 'creation'}, {'type': 'update'}, {'type': 'deletion'}],
    }
    if owned_tags and owned_tags.get('id'):
        tag_op = {'method': 'PUT', 'path': f"{base}/rulesets/{owned_tags['id']}", 'payload': tag_payload}
    else:
        tag_op = {'method': 'POST', 'path': f'{base}/rulesets', 'payload': tag_payload}
    operations = ([] if owned_tags and _normalize(owned_tags) == _normalize(tag_payload)
                  else [tag_op])
    for name in RELEASE_ENVIRONMENTS:
        payload = _environment_payload(name, reviewer_id)
        current = (existing.get('environments') or {}).get(name)
        if current is not None and _normalize_environment(current) == _normalize_environment(payload):
            continue
        operations.append({
            'method': 'PUT',
            'path': f'{base}/environments/{name}',
            'payload': payload,
        })
    if existing.get('immutable_releases') is not True:
        operations.append({'method': 'PUT', 'path': f'{base}/immutable-releases', 'payload': {}})
    return operations


def _normalize_environment(environment: dict) -> dict:
    """Normalize REST read-back protection rules into the update request shape."""
    rules = {rule['type']: rule for rule in environment.get('protection_rules') or []}
    reviewers = rules.get('required_reviewers') or {}
    normalized = {
        'wait_timer': (rules.get('wait_timer') or {}).get('wait_timer', environment.get('wait_timer', 0)),
        'prevent_self_review': reviewers.get('prevent_self_review', environment.get('prevent_self_review', False)),
        'can_admins_bypass': environment.get('can_admins_bypass'),
        'deployment_branch_policy': environment.get('deployment_branch_policy'),
        'reviewers': sorted(
            [(r.get('type'), (r.get('reviewer') or r).get('id'))
             for r in reviewers.get('reviewers', environment.get('reviewers') or [])], key=str),
    }
    normalized['custom_rules'] = sorted(rule['type'] for rule in environment.get('protection_rules') or []
                                        if rule['type'] not in ('wait_timer', 'required_reviewers', 'branch_policy'))
    return normalized


def verify_release_settings(observed: dict, expected: dict) -> list[str]:
    """Return problems. ``expected`` maps an operation path to its payload."""
    problems = []
    if observed.get('immutable_releases') is not True:
        problems.append('immutable releases are not enabled: ' + IMMUTABLE_RELEASE_UI)
    environments = observed.get('environments') or {}
    rulesets = observed.get('rulesets') or []
    for path, payload in expected.items():
        if path.endswith('/immutable-releases'):
            continue
        if path.endswith('/rulesets') or '/rulesets/' in path:
            found = [item for item in rulesets if item.get('name') == payload.get('name')]
            if len(found) != 1 or _normalize(found[0]) != _normalize(payload):
                problems.append(f'tag ruleset at {path} does not match the release authority policy')
            continue
        name = path.rsplit('/', 1)[-1]
        current = environments.get(name) or {}
        have, want = _normalize_environment(current), _normalize_environment(payload)
        for field, value in want.items():
            if have.get(field) != value:
                problems.append(f'environment {name} {field} does not match')
    return problems
