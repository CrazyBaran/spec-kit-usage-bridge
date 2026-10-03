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
RULESET_FIELDS = ('name', 'target', 'enforcement', 'bypass_actors', 'conditions', 'rules')
# Booleans where True is the weaker setting; every other boolean is stricter when True.
WEAKER_WHEN_TRUE = ('do_not_enforce_on_create',)


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
    if rule_type != 'pull_request':
        return []
    problems = []
    if (params.get('required_approving_review_count') or 0) > 0:
        problems.append(
            f'{origin} requires approving reviews, which blocks the sole maintainer')
    methods = params.get('allowed_merge_methods')
    if methods is not None and 'merge' not in methods:
        problems.append(f'{origin} does not allow merge-commit merges')
    return problems


def _incompatible_rules(existing: dict) -> list[str]:
    problems: list[str] = []
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
        elif key == 'required_approving_review_count':
            merged[key] = value
        elif isinstance(value, bool):
            merged[key] = bool(existing[key] and value if key in WEAKER_WHEN_TRUE
                               else existing[key] or value)
    return merged


def _merge_rules(existing: list[dict], desired: list[dict]) -> list[dict]:
    by_type = {rule['type']: rule for rule in existing
               if rule['type'] != 'required_linear_history'}
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
            if 'merge' not in (have or []):
                problems.append(f'{rule_type}: {key} must allow merge, got {have!r}')
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
    effective_types = {r.get('type') for r in observed.get('effective_rules', [])}
    for rule_type in REQUIRED_EFFECTIVE_TYPES:
        if rule_type not in effective_types:
            problems.append(f'effective rules on main lack {rule_type}')
    return problems
