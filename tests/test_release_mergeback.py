from github_api import GitHubAPIError
from release.mergeback import enable_mergeback

REPO = 'CrazyBaran/spec-kit-usage-bridge'
SHA = 'a' * 40


class FakeAPI:
    def __init__(self):
        self.direct_main_updates = []
        self.deleted_branches = []
        self.auto_merges = []
        self.graphql_calls = []
        self.extra_pulls = []
        self.pull_request = {
            'number': 7, 'node_id': 'PR_node_7', 'state': 'open',
            'draft': True, 'merged': False, 'mergeable': True,
            'html_url': 'https://example.test/pull/7',
            'head': {'ref': 'release/0.2.2', 'sha': SHA},
            'base': {'ref': 'main'},
        }

    def pages(self, path):
        if '/pulls' in path:
            return [self.pull_request, *self.extra_pulls]
        return []

    def request(self, method, path, payload=None):
        if method == 'GET' and path.endswith('/pulls/7'):
            return dict(self.pull_request)
        if method == 'PATCH' and path.endswith('/pulls/7'):
            self.pull_request.update(payload or {})
            return self.pull_request
        if method == 'POST' and path.endswith('/pulls/7/merge'):
            self.direct_main_updates.append(payload)
            raise GitHubAPIError('direct merge is forbidden', status=403)
        if method == 'POST' and path == '/graphql':
            self.graphql_calls.append(payload)
            assert payload['variables']['input']['pullRequestId'] == 'PR_node_7'
            if 'markPullRequestReadyForReview' in payload['query']:
                self.pull_request['draft'] = False
                return {'data': {'markPullRequestReadyForReview': {'pullRequest': {'id': 'PR_node_7'}}}}
            assert 'enablePullRequestAutoMerge' in payload['query']
            self.auto_merges.append(payload)
            return {'data': {'enablePullRequestAutoMerge': {'pullRequest': {'id': 'PR_node_7'}}}}
        if method == 'DELETE' and '/git/refs/heads/' in path:
            self.deleted_branches.append(path)
            return {}
        raise GitHubAPIError('unexpected ' + method + ' ' + path, status=500)


def test_conflict_leaves_release_pr_open():
    api = FakeAPI()
    api.pull_request['mergeable'] = False
    result = enable_mergeback(api, '0.2.2', SHA, repo=REPO)
    assert result['status'] == 'manual_action_required'
    assert api.direct_main_updates == []
    assert api.deleted_branches == []
    assert api.auto_merges == []


def test_ready_pr_enables_merge_commit_auto_merge():
    api = FakeAPI()
    result = enable_mergeback(api, '0.2.2', SHA, repo=REPO)
    assert result['status'] == 'auto_merge_enabled'
    assert api.pull_request['draft'] is False
    assert api.auto_merges[0]['variables']['input']['mergeMethod'] == 'MERGE'
    assert len(api.graphql_calls) == 2
    assert api.direct_main_updates == []
    assert api.deleted_branches == []


def test_already_merged_is_a_noop():
    api = FakeAPI()
    api.pull_request['merged'] = True
    result = enable_mergeback(api, '0.2.2', SHA, repo=REPO)
    assert result['status'] == 'already_merged'
    assert api.auto_merges == []
    assert api.direct_main_updates == []
    assert api.deleted_branches == [f'/repos/{REPO}/git/refs/heads/release/0.2.2']


def test_unrelated_pr_is_untouched():
    api = FakeAPI()
    api.pull_request['merged'] = True
    api.extra_pulls = [{
        'number': 9, 'draft': False, 'merged': False, 'mergeable': True,
        'html_url': 'https://example.test/pull/9',
        'head': {'ref': 'docs/readme', 'sha': 'b' * 40},
        'base': {'ref': 'main'},
    }]
    result = enable_mergeback(api, '0.2.2', SHA, repo=REPO)
    assert result['status'] == 'already_merged'
    assert all('/pulls/9' not in path for path in api.deleted_branches)
    assert api.auto_merges == []


def test_failed_required_checks_do_not_merge():
    api = FakeAPI()
    api.pull_request['checks'] = [{'name': 'lint', 'conclusion': 'failure'}]
    result = enable_mergeback(api, '0.2.2', SHA, repo=REPO)
    assert result['status'] == 'manual_action_required'
    assert api.auto_merges == []
    assert api.deleted_branches == []


def test_closed_unmerged_pr_never_enables_auto_merge():
    api = FakeAPI()
    api.pull_request['state'] = 'closed'
    assert enable_mergeback(api, '0.2.2', SHA, repo=REPO)['status'] == 'manual_action_required'
    assert api.auto_merges == []


def test_graphql_rejection_is_manual_action():
    api = FakeAPI()
    original = api.request

    def request(method, path, payload=None):
        if path == '/graphql':
            raise GitHubAPIError('auto merge unavailable')
        return original(method, path, payload)

    api.request = request
    assert enable_mergeback(api, '0.2.2', SHA, repo=REPO)['status'] == 'manual_action_required'
