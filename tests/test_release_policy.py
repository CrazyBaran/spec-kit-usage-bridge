import json
from pathlib import Path

import pytest

from release.models import CheckResult, OverrideRequest
from release.policy import (
    ReleasePolicyError,
    evaluate_checks,
    next_candidate_tag,
    parse_version,
    require_candidate,
    require_metadata,
)

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40
OTHER = 'b' * 40
REQUIRED = (
    'lint',
    'test (ubuntu-latest, 3.9)',
    'test (ubuntu-latest, 3.x)',
    'test (windows-latest, 3.9)',
    'test (windows-latest, 3.x)',
    'integration (ubuntu-latest)',
    'integration (windows-latest)',
)


def _check(name, *, status='completed', conclusion='success', sha=SHA, run_id=10, attempt=1, app_id=15368):
    return CheckResult(name, sha, run_id, attempt, app_id, status, conclusion, 'https://example.test/' + name)


def _green():
    return tuple(_check(name) for name in REQUIRED)


def _override(waived=('lint',), *, attempt=1, sha=SHA, run_id=10, approved=True):
    return OverrideRequest(True, 'known lint defect', tuple(waived), run_id, attempt, sha, approved, 'CrazyBaran')


def test_candidate_numbers_are_numeric():
    assert next_candidate_tag('0.2.2', ('v0.2.2-rc.9',)) == 'v0.2.2-rc.10'
    assert next_candidate_tag('0.2.2', ()) == 'v0.2.2-rc.1'
    assert next_candidate_tag('0.2.2', ('v0.2.1-rc.9', 'v0.2.2-rc.2')) == 'v0.2.2-rc.3'


@pytest.mark.parametrize('value', ['01.2.3', '1.02.3', '1.2.03', '1.2', 'v1.2.3', '1.2.3;rm -rf /', '1.2.3 && true'])
def test_parse_version_rejects_unsafe_input(value):
    with pytest.raises(ReleasePolicyError):
        parse_version(value)


def test_parse_version_accepts_plain_semver():
    assert parse_version('0.2.2') == (0, 2, 2)


def test_no_candidate_cannot_be_overridden():
    with pytest.raises(ReleasePolicyError):
        require_candidate('0.2.2', SHA, None)


def test_candidate_must_be_published_prerelease_at_tip():
    good = {'tag': 'v0.2.2-rc.3', 'version': '0.2.2', 'sha': SHA, 'prerelease': True, 'draft': False}
    require_candidate('0.2.2', SHA, good)
    for broken in (
        {**good, 'draft': True},
        {**good, 'prerelease': False},
        {**good, 'version': '0.2.3'},
        {**good, 'sha': OTHER},
        {**good, 'tag': 'v0.2.2'},
    ):
        with pytest.raises(ReleasePolicyError):
            require_candidate('0.2.2', SHA, broken)


@pytest.mark.parametrize('kind', ['pending', 'missing', 'skipped', 'cancelled'])
def test_incomplete_check_never_waived(kind):
    checks = [item for item in _green() if item.name != 'lint']
    if kind == 'pending':
        checks.append(_check('lint', status='pending', conclusion=None))
    elif kind == 'skipped':
        checks.append(_check('lint', conclusion='skipped'))
    elif kind == 'cancelled':
        checks.append(_check('lint', conclusion='cancelled'))
    decision = evaluate_checks(tuple(checks), REQUIRED, SHA, _override())
    assert decision.allowed is False
    assert 'lint' not in decision.waived


def test_approved_exact_run_lint_failure_can_be_waived():
    checks = [_check('lint', conclusion='failure'), *[item for item in _green() if item.name != 'lint']]
    decision = evaluate_checks(tuple(checks), REQUIRED, SHA, _override())
    assert decision.allowed is True
    assert decision.waived == ('lint',)


@pytest.mark.parametrize('mutator', ['attempt', 'head', 'app'])
def test_stale_evidence_cannot_be_waived(mutator):
    if mutator == 'attempt':
        lint = _check('lint', conclusion='failure', attempt=2)
        override = _override(attempt=1)
        source = SHA
    elif mutator == 'head':
        lint = _check('lint', conclusion='failure')
        override = _override()
        source = OTHER
    else:
        lint = _check('lint', conclusion='failure', app_id=1)
        override = _override()
        source = SHA
    checks = [lint, *[item for item in _green() if item.name != 'lint']]
    decision = evaluate_checks(tuple(checks), REQUIRED, source, override)
    assert decision.allowed is False


def test_all_seven_contexts_are_necessary():
    checks = tuple(item for item in _green() if item.name != 'integration (windows-latest)')
    decision = evaluate_checks(checks, REQUIRED, SHA, OverrideRequest(False, '', (), 0, 0, SHA, False, None))
    assert decision.allowed is False
    assert any('integration (windows-latest)' in blocker for blocker in decision.blockers)


def test_nonwaivable_check_stays_blocked():
    required = REQUIRED + ('install',)
    checks = (*_green(), _check('install', conclusion='failure'))
    decision = evaluate_checks(checks, required, SHA, _override(waived=('install',)))
    assert decision.allowed is False
    assert 'install' not in decision.waived


def test_release_policy_file_matches_task1_bounds():
    policy = json.loads((ROOT / '.github/release-policy.json').read_text(encoding='utf-8'))
    assert policy['required_checks'] == list(REQUIRED)
    assert policy['artifact_limits'] == {
        'max_compressed_bytes': 25 * 1024 * 1024,
        'max_expanded_bytes': 100 * 1024 * 1024,
        'max_members': 1000,
    }
    assert policy['environments'] == ['release-publish', 'release-override', 'catalog-submit']
    assert policy['repository'] == 'CrazyBaran/spec-kit-usage-bridge'
    assert policy['canonical_branch'] == 'main'


def test_unknown_schema_is_rejected():
    with pytest.raises(ReleasePolicyError):
        require_metadata({'schema_version': 2, 'repository': 'CrazyBaran/spec-kit-usage-bridge'})
