"""Mark a verified release pull request ready and enable merge-commit auto-merge."""
from __future__ import annotations

from github_api import GitHubAPIError

DEFAULT_REPO = 'CrazyBaran/spec-kit-usage-bridge'


def enable_mergeback(api, version: str, release_sha: str, *, repo: str = DEFAULT_REPO) -> dict:
    branch = f'release/{version}'
    matches = [
        pull for pull in api.pages(f'/repos/{repo}/pulls?state=all')
        if (pull.get('head') or {}).get('ref') == branch
    ]
    if len(matches) != 1:
        return {'status': 'manual_action_required', 'branch': branch}
    pull = api.request('GET', f'/repos/{repo}/pulls/{matches[0]["number"]}')
    if ((pull.get('base') or {}).get('ref') != 'main'
            or (pull.get('head') or {}).get('sha') != release_sha):
        return {'status': 'manual_action_required', 'branch': branch}
    if pull.get('checks') and any(item.get('conclusion') != 'success' for item in pull['checks']):
        return {'status': 'manual_action_required', 'pull_request': pull.get('html_url')}
    if pull.get('merged'):
        try:
            api.request('DELETE', f'/repos/{repo}/git/refs/heads/{branch}')
        except GitHubAPIError as error:
            if error.status != 404:
                raise
        return {'status': 'already_merged', 'pull_request': pull.get('html_url')}
    if pull.get('state') != 'open' or pull.get('mergeable') is False or not pull.get('node_id'):
        return {'status': 'manual_action_required', 'pull_request': pull.get('html_url')}
    try:
        if pull.get('draft'):
            _mutation(api, 'markPullRequestReadyForReview',
                      'MarkPullRequestReadyForReviewInput', {'pullRequestId': pull['node_id']})
        _mutation(api, 'enablePullRequestAutoMerge', 'EnablePullRequestAutoMergeInput',
                  {'pullRequestId': pull['node_id'], 'mergeMethod': 'MERGE'})
    except GitHubAPIError as error:
        return {'status': 'manual_action_required', 'pull_request': pull.get('html_url'),
                'problem': str(error)}
    return {'status': 'auto_merge_enabled', 'pull_request': pull.get('html_url')}


def _mutation(api, field: str, input_type: str, input_value: dict) -> None:
    result = api.request('POST', '/graphql', {
        'query': f'mutation($input: {input_type}!) {{ {field}(input: $input) {{ pullRequest {{ id }} }} }}',
        'variables': {'input': input_value},
    })
    if (not isinstance(result, dict) or result.get('errors')
            or not ((result.get('data') or {}).get(field) or {}).get('pullRequest')):
        raise GitHubAPIError(f'GraphQL {field} did not confirm the pull request update')
