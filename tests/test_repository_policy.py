"""Tests for the pure protected-main policy and reconciliation planner."""
from __future__ import annotations

import copy

import pytest

from repository_policy import (
    RepositoryPolicyError,
    expected_main_state,
    main_ruleset,
    plan_main_updates,
    release_settings_plan,
    verify_main_policy,
    verify_release_settings,
)

APP_ID = 15368
FULL_NAME = 'CrazyBaran/spec-kit-usage-bridge'
CONTEXTS = [
    'lint',
    'test (ubuntu-latest, 3.9)',
    'test (ubuntu-latest, 3.x)',
    'test (windows-latest, 3.9)',
    'test (windows-latest, 3.x)',
    'integration (ubuntu-latest)',
    'integration (windows-latest)',
]
SERVER_FIELDS = {
    'id': 42,
    'node_id': 'RRS_x',
    'source': FULL_NAME,
    'source_type': 'Repository',
    'created_at': '2026-10-03T00:00:00Z',
    'updated_at': '2026-10-03T00:00:00Z',
    'current_user_can_bypass': 'never',
    '_links': {'self': {'href': 'https://api.github.com/x'}},
}


def check_runs(app_id=APP_ID):
    return [
        {'name': name, 'app': {'id': app_id, 'slug': 'github-actions'}}
        for name in CONTEXTS
    ]


def repository(**overrides):
    repo = {
        'full_name': FULL_NAME,
        'default_branch': 'main',
        'allow_auto_merge': False,
        'allow_merge_commit': True,
        'allow_squash_merge': True,
        'allow_rebase_merge': True,
        'permissions': {'admin': True},
    }
    repo.update(overrides)
    return repo


def existing_state(**overrides):
    state = {
        'repository': repository(),
        'rulesets': [],
        'effective_rules': [],
        'check_runs': check_runs(),
    }
    state.update(overrides)
    return state


def owned_ruleset():
    ruleset = main_ruleset(APP_ID)
    ruleset.update(SERVER_FIELDS)
    return ruleset


def rule(ruleset, rule_type):
    return next(r for r in ruleset['rules'] if r['type'] == rule_type)


def effective(types):
    return [
        {'type': t, 'ruleset_source_type': 'Repository', 'ruleset_source': FULL_NAME,
         'ruleset_id': 42}
        for t in types
    ]


def observed_state(ruleset=None, repo=None, types=None):
    return {
        'repository': repo or {'allow_auto_merge': True, 'allow_merge_commit': True},
        'ruleset': ruleset or owned_ruleset(),
        'effective_rules': effective(
            types or ['pull_request', 'required_status_checks', 'deletion',
                      'non_fast_forward']),
    }


def other_ruleset(rules, name='org-baseline'):
    return {
        'id': 7, 'name': name, 'target': 'branch', 'enforcement': 'active',
        'source_type': 'Organization', 'source': 'CrazyBaran',
        'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}},
        'rules': rules, 'bypass_actors': [],
    }


def test_main_requires_pr_and_has_no_bypass():
    policy = main_ruleset(actions_app_id=15368)
    assert policy['enforcement'] == 'active'
    assert policy['bypass_actors'] == []
    assert policy['conditions']['ref_name']['include'] == ['refs/heads/main']
    rules = {r['type']: r for r in policy['rules']}
    assert rules['pull_request']['parameters']['required_approving_review_count'] == 0
    assert rules['required_status_checks']['parameters']['strict_required_status_checks_policy'] is True
    assert 'deletion' in rules and 'non_fast_forward' in rules


def test_ruleset_serializes_documented_parameter_names():
    policy = main_ruleset(APP_ID)
    assert policy['name'] == 'usage-bridge-main'
    assert policy['target'] == 'branch'
    assert policy['conditions']['ref_name']['exclude'] == []
    pr = rule(policy, 'pull_request')['parameters']
    assert pr == {
        'required_approving_review_count': 0,
        'dismiss_stale_reviews_on_push': False,
        'require_code_owner_review': False,
        'require_last_push_approval': False,
        'required_review_thread_resolution': True,
        'allowed_merge_methods': ['merge', 'squash', 'rebase'],
    }
    checks = rule(policy, 'required_status_checks')['parameters']
    assert checks['do_not_enforce_on_create'] is False
    assert set(checks) == {
        'strict_required_status_checks_policy', 'do_not_enforce_on_create',
        'required_status_checks'}


def test_required_contexts_bound_to_actions():
    checks = rule(main_ruleset(APP_ID), 'required_status_checks')['parameters']
    assert checks['required_status_checks'] == [
        {'context': name, 'integration_id': APP_ID} for name in CONTEXTS]
    other = rule(main_ruleset(99), 'required_status_checks')['parameters']
    assert other['required_status_checks'][0] == {'context': 'lint', 'integration_id': 99}


def test_merge_commit_compatible_policy():
    policy = main_ruleset(APP_ID)
    assert 'required_linear_history' not in {r['type'] for r in policy['rules']}
    assert 'merge' in rule(policy, 'pull_request')['parameters']['allowed_merge_methods']


def test_expected_main_state():
    assert expected_main_state(APP_ID) == {
        'repository': {'allow_auto_merge': True, 'allow_merge_commit': True},
        'ruleset': main_ruleset(APP_ID),
    }


def test_policy_error_joins_problems():
    error = RepositoryPolicyError(['a', 'b'])
    assert error.problems == ['a', 'b']
    assert 'a' in str(error) and 'b' in str(error)


def test_plan_creates_ruleset_and_patches_repository_minimally():
    ops = plan_main_updates(existing_state(), APP_ID)
    assert ops == [
        {'method': 'PATCH', 'path': f'repos/{FULL_NAME}',
         'payload': {'allow_auto_merge': True}},
        {'method': 'POST', 'path': f'repos/{FULL_NAME}/rulesets',
         'payload': main_ruleset(APP_ID)},
    ]


def test_repository_patch_includes_merge_commit_only_when_needed():
    state = existing_state(repository=repository(
        allow_auto_merge=True, allow_merge_commit=False))
    ops = plan_main_updates(state, APP_ID)
    assert ops[0] == {'method': 'PATCH', 'path': f'repos/{FULL_NAME}',
                      'payload': {'allow_merge_commit': True}}


def test_plan_is_noop_when_owned_ruleset_matches():
    state = existing_state(
        repository=repository(allow_auto_merge=True),
        rulesets=[owned_ruleset()])
    assert plan_main_updates(state, APP_ID) == []


def test_stricter_existing_policy_is_preserved():
    owned = owned_ruleset()
    rule(owned, 'required_status_checks')['parameters']['required_status_checks'].append(
        {'context': 'extra', 'integration_id': APP_ID})
    rule(owned, 'pull_request')['parameters']['dismiss_stale_reviews_on_push'] = True
    owned['rules'].append({'type': 'required_signatures'})
    inherited = other_ruleset([{'type': 'required_signatures'}, {'type': 'creation'}])
    state = existing_state(
        repository=repository(allow_auto_merge=True),
        rulesets=[owned, inherited])
    assert plan_main_updates(state, APP_ID) == []


def test_put_preserves_extra_owned_context_and_rule():
    owned = owned_ruleset()
    owned['rules'] = [r for r in owned['rules'] if r['type'] != 'deletion']
    checks = rule(owned, 'required_status_checks')['parameters']
    checks['required_status_checks'] = [
        {'context': 'extra', 'integration_id': 1},
        {'context': 'lint', 'integration_id': APP_ID},
    ]
    checks['strict_required_status_checks_policy'] = False
    owned['rules'].append({'type': 'required_signatures'})
    owned['bypass_actors'] = [{'actor_id': 5, 'actor_type': 'RepositoryRole',
                               'bypass_mode': 'always'}]
    owned['enforcement'] = 'evaluate'
    state = existing_state(
        repository=repository(allow_auto_merge=True), rulesets=[owned])
    [op] = plan_main_updates(state, APP_ID)
    assert op['method'] == 'PUT'
    assert op['path'] == f'repos/{FULL_NAME}/rulesets/42'
    payload = op['payload']
    assert not set(payload) & {'id', 'source', 'node_id', '_links', 'created_at'}
    assert payload['enforcement'] == 'active'
    assert payload['bypass_actors'] == []
    types = {r['type'] for r in payload['rules']}
    assert {'deletion', 'non_fast_forward', 'pull_request',
            'required_status_checks', 'required_signatures'} <= types
    merged = rule(payload, 'required_status_checks')['parameters']
    pairs = {(c['context'], c['integration_id']) for c in merged['required_status_checks']}
    assert ('extra', 1) in pairs
    assert {(n, APP_ID) for n in CONTEXTS} <= pairs
    assert merged['strict_required_status_checks_policy'] is True
    # Applying the PUT payload then planning again is a no-op.
    stable = existing_state(
        repository=repository(allow_auto_merge=True),
        rulesets=[dict(payload, **SERVER_FIELDS)])
    assert plan_main_updates(stable, APP_ID) == []


def test_put_adds_main_to_ref_include():
    owned = owned_ruleset()
    owned['conditions']['ref_name']['include'] = ['refs/heads/release']
    state = existing_state(
        repository=repository(allow_auto_merge=True), rulesets=[owned])
    [op] = plan_main_updates(state, APP_ID)
    include = op['payload']['conditions']['ref_name']['include']
    assert 'refs/heads/main' in include
    assert 'refs/heads/release' in include


def test_missing_or_ambiguous_actions_checks_blocks_apply():
    runs = [r for r in check_runs() if r['name'] != 'lint']
    with pytest.raises(RepositoryPolicyError) as missing:
        plan_main_updates(existing_state(check_runs=runs), APP_ID)
    assert 'lint' in str(missing.value)

    ambiguous = check_runs() + [
        {'name': 'lint', 'app': {'id': 123, 'slug': 'other-ci'}}]
    with pytest.raises(RepositoryPolicyError) as bad:
        plan_main_updates(existing_state(check_runs=ambiguous), APP_ID)
    assert 'lint' in str(bad.value)

    with pytest.raises(RepositoryPolicyError):
        plan_main_updates(existing_state(check_runs=check_runs(999)), APP_ID)


def test_duplicate_owned_ruleset_blocks():
    other = owned_ruleset()
    other['id'] = 43
    with pytest.raises(RepositoryPolicyError):
        plan_main_updates(existing_state(rulesets=[owned_ruleset(), other]), APP_ID)


BLOCKING_RULES = [
    {'type': 'required_linear_history'},
    {'type': 'pull_request', 'parameters': {
        'required_approving_review_count': 1, 'allowed_merge_methods': ['merge']}},
    {'type': 'pull_request', 'parameters': {
        'required_approving_review_count': 0, 'allowed_merge_methods': ['squash']}},
]


@pytest.mark.parametrize('blocking_rule', BLOCKING_RULES)
def test_incompatible_inherited_rules_block(blocking_rule):
    state = existing_state(rulesets=[other_ruleset([blocking_rule])])
    with pytest.raises(RepositoryPolicyError):
        plan_main_updates(state, APP_ID)
    effective_only = existing_state(effective_rules=[
        dict(blocking_rule, ruleset_source_type='Organization',
             ruleset_source='CrazyBaran', ruleset_id=7)])
    with pytest.raises(RepositoryPolicyError):
        plan_main_updates(effective_only, APP_ID)


def _put_payload(owned):
    state = existing_state(
        repository=repository(allow_auto_merge=True), rulesets=[owned])
    [op] = plan_main_updates(state, APP_ID)
    assert op['method'] == 'PUT'
    stable = existing_state(
        repository=repository(allow_auto_merge=True),
        rulesets=[dict(op['payload'], **SERVER_FIELDS)])
    assert plan_main_updates(stable, APP_ID) == []
    return op['payload']


def test_owned_review_count_is_reconciled_to_zero():
    owned = owned_ruleset()
    rule(owned, 'pull_request')['parameters']['required_approving_review_count'] = 2
    payload = _put_payload(owned)
    assert rule(payload, 'pull_request')['parameters'][
        'required_approving_review_count'] == 0


def test_owned_merge_methods_gain_merge():
    owned = owned_ruleset()
    rule(owned, 'pull_request')['parameters']['allowed_merge_methods'] = ['squash']
    payload = _put_payload(owned)
    assert rule(payload, 'pull_request')['parameters']['allowed_merge_methods'] == [
        'squash', 'merge']


def test_owned_linear_history_is_dropped():
    owned = owned_ruleset()
    owned['rules'].append({'type': 'required_linear_history'})
    payload = _put_payload(owned)
    assert 'required_linear_history' not in {r['type'] for r in payload['rules']}


def test_owned_do_not_enforce_on_create_is_corrected():
    owned = owned_ruleset()
    rule(owned, 'required_status_checks')['parameters']['do_not_enforce_on_create'] = True
    payload = _put_payload(owned)
    assert rule(payload, 'required_status_checks')['parameters'][
        'do_not_enforce_on_create'] is False


def test_owned_exclude_of_main_is_removed():
    for pattern in ('refs/heads/main', 'refs/heads/m*', '~DEFAULT_BRANCH', '~ALL'):
        owned = owned_ruleset()
        owned['conditions']['ref_name']['exclude'] = [pattern, 'refs/heads/other']
        payload = _put_payload(owned)
        assert payload['conditions']['ref_name']['exclude'] == ['refs/heads/other']


def test_owned_effective_rules_do_not_block():
    bad = {'type': 'required_linear_history', 'ruleset_source_type': 'Repository',
           'ruleset_source': FULL_NAME, 'ruleset_id': 42}
    state = existing_state(
        repository=repository(allow_auto_merge=True),
        rulesets=[owned_ruleset()], effective_rules=[bad])
    assert plan_main_updates(state, APP_ID) == []


def test_missing_review_count_does_not_crash():
    inherited = other_ruleset([{'type': 'pull_request', 'parameters': {
        'required_approving_review_count': None}}])
    assert plan_main_updates(existing_state(rulesets=[inherited]), APP_ID)


def test_non_owned_rulesets_not_applying_to_main_do_not_block():
    bad = [{'type': 'required_linear_history'}]
    other_ref = other_ruleset(bad)
    other_ref['conditions']['ref_name']['include'] = ['refs/heads/release/*']
    disabled = other_ruleset(bad, name='off')
    disabled['enforcement'] = 'disabled'
    evaluate = other_ruleset(bad, name='eval')
    evaluate['enforcement'] = 'evaluate'
    state = existing_state(rulesets=[other_ref, disabled, evaluate])
    assert plan_main_updates(state, APP_ID)[-1]['method'] == 'POST'


def test_plan_does_not_mutate_input():
    state = existing_state(rulesets=[owned_ruleset()])
    snapshot = copy.deepcopy(state)
    plan_main_updates(state, APP_ID)
    assert state == snapshot


def test_verify_accepts_exact_match_with_server_fields():
    assert verify_main_policy(observed_state(), expected_main_state(APP_ID)) == []


def test_verify_accepts_stricter_extras_and_reordered_checks():
    owned = owned_ruleset()
    rule(owned, 'pull_request')['parameters']['dismiss_stale_reviews_on_push'] = True
    checks = rule(owned, 'required_status_checks')['parameters']
    checks['required_status_checks'].reverse()
    checks['required_status_checks'].append({'context': 'extra', 'integration_id': 1})
    owned['rules'].append({'type': 'required_signatures'})
    observed = observed_state(ruleset=owned)
    assert verify_main_policy(observed, expected_main_state(APP_ID)) == []


def test_verify_flags_missing_context_and_wrong_integration():
    owned = owned_ruleset()
    checks = rule(owned, 'required_status_checks')['parameters']['required_status_checks']
    checks[:] = [c for c in checks if c['context'] != 'lint']
    checks[0]['integration_id'] = 1
    problems = verify_main_policy(observed_state(ruleset=owned), expected_main_state(APP_ID))
    assert any('lint' in p for p in problems)
    assert any(CONTEXTS[1] in p for p in problems)


def test_verify_flags_bypass_enforcement_and_weakened_params():
    owned = owned_ruleset()
    owned['bypass_actors'] = [{'actor_id': 5, 'actor_type': 'RepositoryRole',
                               'bypass_mode': 'always'}]
    owned['enforcement'] = 'disabled'
    rule(owned, 'required_status_checks')['parameters'][
        'strict_required_status_checks_policy'] = False
    rule(owned, 'pull_request')['parameters']['required_review_thread_resolution'] = False
    rule(owned, 'pull_request')['parameters']['required_approving_review_count'] = 2
    owned['rules'] = [r for r in owned['rules'] if r['type'] != 'deletion']
    problems = verify_main_policy(observed_state(ruleset=owned), expected_main_state(APP_ID))
    joined = '\n'.join(problems)
    for needle in ('bypass', 'enforcement', 'strict', 'thread', 'approving', 'deletion'):
        assert needle in joined


def test_verify_flags_missing_effective_rule_and_repository_settings():
    observed = observed_state(
        types=['pull_request', 'required_status_checks', 'deletion'],
        repo={'allow_auto_merge': False, 'allow_merge_commit': True})
    problems = verify_main_policy(observed, expected_main_state(APP_ID))
    joined = '\n'.join(problems)
    assert 'non_fast_forward' in joined
    assert 'allow_auto_merge' in joined
    assert 'allow_merge_commit' not in joined


def test_verify_flags_missing_ruleset():
    observed = observed_state()
    observed['ruleset'] = None
    assert verify_main_policy(observed, expected_main_state(APP_ID))


# --- classic protection, wider blockers, server defaults ----------------------

CLASSIC_BLOCKERS = [
    {'required_pull_request_reviews': {'required_approving_review_count': 1}},
    {'required_pull_request_reviews': {'require_code_owner_reviews': True}},
    {'required_pull_request_reviews': {'require_last_push_approval': True}},
    {'required_linear_history': {'enabled': True}},
]
EXTRA_BLOCKING_RULES = [
    {'type': 'update'},
    {'type': 'merge_queue', 'parameters': {}},
    {'type': 'required_deployments', 'parameters': {
        'required_deployment_environments': ['prod']}},
    {'type': 'pull_request', 'parameters': {'require_code_owner_review': True}},
    {'type': 'pull_request', 'parameters': {'require_last_push_approval': True}},
    {'type': 'pull_request', 'parameters': {
        'required_reviewers': [{'reviewer': {'id': 1, 'type': 'Team'}}]}},
]


def test_classic_protection_none_or_benign_does_not_block():
    assert plan_main_updates(existing_state(classic_protection=None), APP_ID)
    benign = {'required_pull_request_reviews': {'required_approving_review_count': 0,
                                                'require_code_owner_reviews': False},
              'required_linear_history': {'enabled': False}}
    assert plan_main_updates(existing_state(classic_protection=benign), APP_ID)


@pytest.mark.parametrize('classic', CLASSIC_BLOCKERS)
def test_classic_protection_blocks_planning(classic):
    with pytest.raises(RepositoryPolicyError) as raised:
        plan_main_updates(existing_state(classic_protection=classic), APP_ID)
    assert 'classic' in str(raised.value)


@pytest.mark.parametrize('classic', CLASSIC_BLOCKERS)
def test_classic_protection_fails_verification(classic):
    observed = observed_state()
    observed['classic_protection'] = classic
    problems = verify_main_policy(observed, expected_main_state(APP_ID))
    assert any('classic' in p for p in problems)
    observed['classic_protection'] = None
    assert verify_main_policy(observed, expected_main_state(APP_ID)) == []


@pytest.mark.parametrize('blocking_rule', EXTRA_BLOCKING_RULES)
def test_extra_non_owned_blockers(blocking_rule):
    with pytest.raises(RepositoryPolicyError):
        plan_main_updates(existing_state(rulesets=[other_ruleset([blocking_rule])]), APP_ID)
    effective_only = existing_state(effective_rules=[
        dict(blocking_rule, ruleset_source_type='Organization',
             ruleset_source='CrazyBaran', ruleset_id=7)])
    with pytest.raises(RepositoryPolicyError):
        plan_main_updates(effective_only, APP_ID)


def test_owned_code_owner_and_last_push_are_forced_false():
    owned = owned_ruleset()
    params = rule(owned, 'pull_request')['parameters']
    params['require_code_owner_review'] = True
    params['require_last_push_approval'] = True
    payload = _put_payload(owned)
    merged = rule(payload, 'pull_request')['parameters']
    assert merged['require_code_owner_review'] is False
    assert merged['require_last_push_approval'] is False


def test_owned_blocking_rule_types_are_dropped():
    owned = owned_ruleset()
    owned['rules'] += [{'type': 'update'}, {'type': 'merge_queue', 'parameters': {}},
                       {'type': 'required_deployments', 'parameters': {}}]
    payload = _put_payload(owned)
    assert not {'update', 'merge_queue', 'required_deployments'} & {
        r['type'] for r in payload['rules']}


def test_verify_flags_owned_code_owner_and_blocking_rules():
    owned = owned_ruleset()
    rule(owned, 'pull_request')['parameters']['require_code_owner_review'] = True
    owned['rules'].append({'type': 'update'})
    joined = '\n'.join(verify_main_policy(observed_state(ruleset=owned),
                                          expected_main_state(APP_ID)))
    assert 'require_code_owner_review' in joined
    assert 'update' in joined


def test_absent_server_default_parameters_are_not_drift():
    owned = owned_ruleset()
    del rule(owned, 'required_status_checks')['parameters']['do_not_enforce_on_create']
    del rule(owned, 'pull_request')['parameters']['allowed_merge_methods']
    state = existing_state(repository=repository(allow_auto_merge=True), rulesets=[owned])
    assert plan_main_updates(state, APP_ID) == []
    assert verify_main_policy(observed_state(ruleset=owned), expected_main_state(APP_ID)) == []


def test_release_app_cannot_bypass_main():
    assert main_ruleset(actions_app_id=15368)['bypass_actors'] == []
    operations = release_settings_plan(existing={}, release_app_id=4242, reviewer_id=777)
    override = next(op['payload'] for op in operations if op['path'].endswith('/environments/release-override'))
    assert override['prevent_self_review'] is False
    assert override['can_admins_bypass'] is False
    assert override['reviewers'] == [{'type': 'User', 'id': 777}]
    tag = next(op['payload'] for op in operations if op['payload'].get('name') == 'usage-bridge-tags')
    assert tag['bypass_actors'] == [{
        'actor_id': 4242, 'actor_type': 'Integration', 'bypass_mode': 'always',
    }]
    assert all(op['payload'].get('name') != 'usage-bridge-main' for op in operations)
    submit = next(op['payload'] for op in operations if op['path'].endswith('/environments/catalog-submit'))
    assert submit['reviewers'] == [{'type': 'User', 'id': 777}]
    assert submit['can_admins_bypass'] is False


def test_release_settings_verification_reports_drift():
    operations = release_settings_plan(existing={}, release_app_id=4242, reviewer_id=777)
    expected = {op['path']: op['payload'] for op in operations}
    problems = verify_release_settings({'environments': {}, 'rulesets': [], 'immutable_releases': False}, expected)
    assert problems
    assert any('immutable' in problem for problem in problems)
