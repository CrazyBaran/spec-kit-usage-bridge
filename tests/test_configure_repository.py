"""Tests for the main-protection configure/verify tool (no live GitHub)."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import configure_repository
from configure_repository import configure_main
from github_api import GitHubAPIError
from repository_policy import REQUIRED_CONTEXTS, RULESET_NAME

REPO = 'CrazyBaran/spec-kit-usage-bridge'
BASE = f'repos/{REPO}'
APP = {'id': 15368, 'slug': 'github-actions'}
WRITES = {'POST', 'PUT', 'PATCH', 'DELETE'}


class FakeAPI:
    """Stateful stand-in for GitHubAPI: writes become visible to later reads."""

    def __init__(self):
        self.calls = []
        self.fail_on = None  # (method, path suffix) -> raise GitHubAPIError
        self.next_id = 100
        self.repository = {
            'full_name': REPO, 'default_branch': 'main',
            'allow_auto_merge': False, 'allow_merge_commit': True,
            'permissions': {'admin': True},
        }
        self.rulesets = {}
        self.protected = False
        self.classic = {}
        self.classic_error = None
        self.check_runs = [{'name': n, 'app': dict(APP)} for n in REQUIRED_CONTEXTS]
        self.check_runs += [{'name': 'other', 'app': dict(APP)}]

    def _record(self, method, path, payload=None):
        self.calls.append(SimpleNamespace(method=method, path=path, payload=payload))

    def _effective(self):
        rules = []
        for rs in self.rulesets.values():
            for rule in rs['rules']:
                rules.append({**copy.deepcopy(rule), 'ruleset_id': rs['id'],
                              'ruleset_source_type': 'Repository',
                              'ruleset_source': REPO})
        return rules

    def pages(self, path):
        self._record('GET', path)
        if path == f'{BASE}/rulesets':
            return [{'id': i, 'name': r['name']} for i, r in self.rulesets.items()]
        if path == f'{BASE}/rules/branches/main':
            return self._effective()
        if path == f'{BASE}/commits/main/check-runs':
            return copy.deepcopy(self.check_runs)
        raise AssertionError(f'unexpected pages path {path}')

    def request(self, method, path, payload=None):
        self._record(method, path, payload)
        if self.fail_on and method == self.fail_on[0] and path.endswith(self.fail_on[1]):
            raise GitHubAPIError(f'{method} {path} failed (exit 1, HTTP 403): boom', 403)
        if method == 'GET' and path == BASE:
            return copy.deepcopy(self.repository)
        if method == 'GET' and path == f'{BASE}/branches/main':
            return {'name': 'main', 'protected': self.protected}
        if method == 'GET' and path == f'{BASE}/branches/main/protection':
            if self.classic_error:
                raise GitHubAPIError(
                f'{method} {path} failed', self.classic_error)
            return copy.deepcopy(self.classic)
        if method == 'GET' and path.startswith(f'{BASE}/rulesets/'):
            return copy.deepcopy(self.rulesets[int(path.rsplit('/', 1)[1])])
        if method == 'PATCH' and path == BASE:
            self.repository.update(payload)
            return copy.deepcopy(self.repository)
        if method == 'POST' and path == f'{BASE}/rulesets':
            self.next_id += 1
            self.rulesets[self.next_id] = {**copy.deepcopy(payload), 'id': self.next_id}
            return copy.deepcopy(self.rulesets[self.next_id])
        if method == 'PUT' and path.startswith(f'{BASE}/rulesets/'):
            rid = int(path.rsplit('/', 1)[1])
            self.rulesets[rid] = {**copy.deepcopy(payload), 'id': rid}
            return copy.deepcopy(self.rulesets[rid])
        raise AssertionError(f'unexpected request {method} {path}')


@pytest.fixture
def fake_api():
    return FakeAPI()


def writes(api):
    return [c for c in api.calls if c.method in WRITES]


def owned(api):
    return [r for r in api.rulesets.values() if r['name'] == RULESET_NAME]


def test_dry_run_has_no_writes(fake_api):
    report = configure_main(fake_api, REPO, apply=False)
    assert report['mode'] == 'dry-run'
    assert report['applied'] == []
    assert [op['method'] for op in report['planned']] == ['PATCH', 'POST']
    assert report['verified'] is False
    assert report['problems']
    assert report['errors'] == []
    assert report['actions_app_id'] == 15368
    assert all(call.method == 'GET' for call in fake_api.calls)


def test_apply_verifies_effective_rules(fake_api):
    report = configure_main(fake_api, REPO, apply=True)
    assert report['errors'] == []
    assert [op['method'] for op in report['applied']] == ['PATCH', 'POST']
    assert report['verified'] is True
    assert report['problems'] == []
    last_write = max(i for i, c in enumerate(fake_api.calls) if c.method in WRITES)
    after = fake_api.calls[last_write + 1:]
    assert any(c.path == f'{BASE}/rules/branches/main' for c in after)
    assert any(c.path == BASE and c.method == 'GET' for c in after)
    assert len(owned(fake_api)) == 1


def test_retry_updates_owned_rule_without_duplicate(fake_api):
    configure_main(fake_api, REPO, apply=True)
    before = len(writes(fake_api))
    report = configure_main(fake_api, REPO, apply=True)
    assert report['planned'] == []
    assert report['verified'] is True
    assert len(writes(fake_api)) == before
    assert len(owned(fake_api)) == 1


def test_partial_failure_reports_prior_writes(fake_api):
    fake_api.fail_on = ('POST', '/rulesets')
    report = configure_main(fake_api, REPO, apply=True)
    assert [op['method'] for op in report['applied']] == ['PATCH']
    assert report['verified'] is False
    assert any('403' in e for e in report['errors'])
    assert [c.method for c in writes(fake_api)] == ['PATCH', 'POST']  # no retry
    assert owned(fake_api) == []


@pytest.mark.parametrize('apply', [False, True])
def test_wrong_repository_is_refused(fake_api, apply):
    report = configure_main(fake_api, 'github/spec-kit', apply=apply)
    assert fake_api.calls == []
    assert report['errors']
    assert report['applied'] == [] and report['planned'] == []
    assert report['verified'] is False


def test_non_admin_blocks_without_writes(fake_api):
    fake_api.repository['permissions'] = {'admin': False}
    report = configure_main(fake_api, REPO, apply=True)
    assert any('admin' in e for e in report['errors'])
    assert writes(fake_api) == []
    assert report['verified'] is False


def test_non_default_branch_blocks(fake_api):
    fake_api.repository['default_branch'] = 'trunk'
    report = configure_main(fake_api, REPO, apply=True)
    assert any('default branch' in e for e in report['errors'])
    assert writes(fake_api) == []


def test_foreign_check_app_blocks_without_writes(fake_api):
    fake_api.check_runs[1]['app'] = {'id': 999, 'slug': 'some-other-app'}
    report = configure_main(fake_api, REPO, apply=True)
    assert report['errors']
    assert report['actions_app_id'] is None
    assert writes(fake_api) == []


def test_two_app_ids_block_without_writes(fake_api):
    fake_api.check_runs.append({'name': 'lint', 'app': {'id': 1, 'slug': 'github-actions'}})
    report = configure_main(fake_api, REPO, apply=True)
    assert report['errors']
    assert writes(fake_api) == []


def test_missing_check_blocks_without_writes(fake_api):
    fake_api.check_runs = [r for r in fake_api.check_runs if r['name'] != 'lint']
    report = configure_main(fake_api, REPO, apply=True)
    assert report['errors']
    assert writes(fake_api) == []


def test_policy_error_surfaces_without_writes(fake_api):
    fake_api.rulesets[7] = {
        'id': 7, 'name': 'strict', 'target': 'branch', 'enforcement': 'active',
        'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}},
        'rules': [{'type': 'pull_request',
                   'parameters': {'required_approving_review_count': 1}}],
        'bypass_actors': []}
    report = configure_main(fake_api, REPO, apply=True)
    assert any('approving reviews' in e for e in report['errors'])
    assert writes(fake_api) == []
    assert report['verified'] is False


def test_report_contains_no_credentials(fake_api, monkeypatch):
    monkeypatch.setenv('GH_TOKEN', 'ghp_supersecret')
    report = configure_main(fake_api, REPO, apply=False)
    assert 'ghp_supersecret' not in json.dumps(report)


def test_cli_dry_run_writes_report(fake_api, tmp_path, capsys):
    code = configure_repository.main(
        ['main', '--repo', REPO, '--report-dir', str(tmp_path)], api=fake_api)
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['mode'] == 'dry-run'
    files = list(tmp_path.glob('main-*.json'))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding='utf-8')) == printed
    assert writes(fake_api) == []


def test_cli_apply_exit_codes(fake_api, tmp_path):
    ok = configure_repository.main(
        ['main', '--repo', REPO, '--apply', '--report-dir', str(tmp_path)], api=fake_api)
    assert ok == 0
    bad = configure_repository.main(
        ['main', '--repo', 'github/spec-kit', '--report-dir', str(tmp_path)], api=fake_api)
    assert bad == 1


def test_unprotected_main_never_requests_classic_protection(fake_api):
    report = configure_main(fake_api, REPO, apply=True)
    assert report['verified'] is True
    paths = [c.path for c in fake_api.calls]
    assert f'{BASE}/branches/main' in paths
    assert f'{BASE}/branches/main/protection' not in paths


@pytest.mark.parametrize('classic', [
    {'required_pull_request_reviews': {'required_approving_review_count': 1}},
    {'required_pull_request_reviews': {'require_code_owner_reviews': True}},
    {'required_pull_request_reviews': {'require_last_push_approval': True}},
    {'required_linear_history': {'enabled': True}},
])
def test_blocking_classic_protection_stops_without_writes(fake_api, classic):
    fake_api.protected = True
    fake_api.classic = classic
    report = configure_main(fake_api, REPO, apply=True)
    assert any('classic' in e for e in report['errors'])
    assert writes(fake_api) == []
    assert report['verified'] is False


def test_benign_classic_protection_is_read_and_allowed(fake_api):
    fake_api.protected = True
    fake_api.classic = {'allow_force_pushes': {'enabled': False}}
    report = configure_main(fake_api, REPO, apply=True)
    assert report['errors'] == []
    assert report['verified'] is True
    assert any(c.path == f'{BASE}/branches/main/protection' for c in fake_api.calls)


def test_relative_report_dir_resolves_against_repository_root(fake_api, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = Path(configure_repository.__file__).resolve().parents[1]
    target = root / 'build' / 'test-report-dir-resolution'
    try:
        configure_repository.main(
            ['main', '--repo', REPO, '--report-dir', 'build/test-report-dir-resolution'],
            api=fake_api)
        assert list(target.glob('main-*.json'))
        assert not (tmp_path / 'build').exists()
    finally:
        shutil.rmtree(target, ignore_errors=True)


def test_protection_404_means_no_classic_protection(fake_api):
    fake_api.protected = True  # GitHub reports true when only a ruleset applies
    fake_api.classic_error = 404
    report = configure_main(fake_api, REPO, apply=True)
    assert report['errors'] == []
    assert report['verified'] is True
    assert any(c.path == f'{BASE}/branches/main/protection' for c in fake_api.calls)


def test_protection_403_is_a_blocker_without_writes(fake_api):
    fake_api.protected = True
    fake_api.classic_error = 403
    report = configure_main(fake_api, REPO, apply=True)
    assert report['errors']
    assert writes(fake_api) == []
    assert report['verified'] is False


class ReleaseAPI(FakeAPI):
    def __init__(self):
        super().__init__()
        self.app_id = 4242
        self.installation_id = 9000
        self.environments = {}
        self.immutable = False
        self.ignore_writes = False

    def pages(self, path):
        if path == 'user/installations':
            self._record('GET', path)
            return [{'id': self.installation_id, 'app_id': self.app_id, 'suspended_at': None}]
        if path == f'user/installations/{self.installation_id}/repositories':
            self._record('GET', path)
            return [{'full_name': REPO}]
        return super().pages(path)

    def request(self, method, path, payload=None):
        if path == f'{BASE}/immutable-releases':
            self._record(method, path, payload)
            if method == 'PUT':
                if not self.ignore_writes:
                    self.immutable = True
                return None
            if not self.immutable:
                raise GitHubAPIError('disabled', 404)
            return {'enabled': True, 'enforced_by_owner': False}
        if '/environments/' in path:
            self._record(method, path, payload)
            name = path.rsplit('/', 1)[-1]
            if method == 'PUT':
                if not self.ignore_writes:
                    self.environments[name] = {
                        'name': name, 'can_admins_bypass': payload['can_admins_bypass'],
                        'deployment_branch_policy': payload['deployment_branch_policy'],
                        'protection_rules': [
                            {'type': 'wait_timer', 'wait_timer': payload['wait_timer']},
                            {'type': 'required_reviewers', 'prevent_self_review': payload['prevent_self_review'],
                             'reviewers': [{'type': r['type'], 'reviewer': {'id': r['id'], 'login': 'owner'}}
                                           for r in payload['reviewers']]},
                        ],
                    }
                return self.environments.get(name, {})
            if name not in self.environments:
                raise GitHubAPIError('missing', 404)
            return copy.deepcopy(self.environments[name])
        return super().request(method, path, payload)


def test_release_apply_discovers_app_id_and_verifies_actual_readback():
    api = ReleaseAPI()
    report = configure_repository.configure_release(api, REPO, 4242, 777, True)
    assert report['errors'] == []
    assert report['verified'] is True
    tags = [r for r in api.rulesets.values() if r['name'] == 'usage-bridge-tags']
    assert tags[0]['bypass_actors'][0]['actor_id'] == 4242
    assert api.immutable is True
    assert any(c.path == 'user/installations/9000/repositories' for c in api.calls)


def test_release_reapply_is_idempotent_without_duplicate_rulesets():
    api = ReleaseAPI()
    assert configure_repository.configure_release(api, REPO, 4242, 777, True)['verified']
    api.calls.clear()
    report = configure_repository.configure_release(api, REPO, 4242, 777, True)
    assert report['verified'] is True
    assert report['planned'] == []
    assert writes(api) == []
    assert len(api.rulesets) == 1


def test_release_does_not_confuse_installation_id_with_app_id():
    api = ReleaseAPI()
    report = configure_repository.configure_release(api, REPO, 9000, 777, True)
    assert report['errors']
    assert writes(api) == []


def test_release_readback_drift_fails_apply_cli(tmp_path):
    api = ReleaseAPI()
    api.ignore_writes = True
    assert configure_repository.main([
        'release', '--repo', REPO, '--release-app-id', '4242', '--reviewer-id', '777',
        '--apply', '--report-dir', str(tmp_path)], api=api) == 1


def test_release_duplicate_owned_tag_rulesets_fail_without_mutation():
    api = ReleaseAPI()
    for identity in (1, 2):
        api.rulesets[identity] = {'id': identity, 'name': 'usage-bridge-tags', 'rules': []}
    report = configure_repository.configure_release(api, REPO, 4242, 777, True)
    assert report['errors']
    assert writes(api) == []


def test_release_verification_catches_disabled_or_weakened_tag_rules():
    api = ReleaseAPI()
    assert configure_repository.configure_release(api, REPO, 4242, 777, True)['verified']
    next(iter(api.rulesets.values()))['enforcement'] = 'disabled'
    report = configure_repository.configure_release(api, REPO, 4242, 777, False)
    assert report['verified'] is False
    assert any('tag ruleset' in problem for problem in report['problems'])
