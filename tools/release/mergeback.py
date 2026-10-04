"""Mark a verified release pull request ready and enable merge-commit auto-merge."""
from __future__ import annotations

DEFAULT_REPO = 'CrazyBaran/spec-kit-usage-bridge'


def enable_mergeback(api, version: str, release_sha: str, *, repo: str = DEFAULT_REPO) -> dict:
    branch = f'release/{version}'
    matches = [
        pull for pull in api.pages(f'/repos/{repo}/pulls?state=all')
        if (pull.get('head') or {}).get('ref') == branch
    ]
    if len(matches) != 1:
        return {'status': 'manual_action_required', 'branch': branch}
    pull = matches[0]
    if (pull.get('head') or {}).get('sha') != release_sha and not pull.get('merged'):
        return {'status': 'manual_action_required', 'branch': branch}
    if pull.get('checks') and any(item.get('conclusion') != 'success' for item in pull['checks']):
        return {'status': 'manual_action_required', 'pull_request': pull.get('html_url')}
    if pull.get('merged'):
        api.request('DELETE', f'/repos/{repo}/git/refs/heads/{branch}')
        return {'status': 'already_merged', 'pull_request': pull.get('html_url')}
    if pull.get('mergeable') is False:
        return {'status': 'manual_action_required', 'pull_request': pull.get('html_url')}
    number = pull['number']
    api.request('PATCH', f'/repos/{repo}/pulls/{number}', {'draft': False})
    api.request('PUT', f'/repos/{repo}/graphql', {
        'query': 'mutation { enablePullRequestAutoMerge }',
        'mergeMethod': 'MERGE',
        'pullRequestId': number,
    })
    return {'status': 'auto_merge_enabled', 'pull_request': pull.get('html_url')}
