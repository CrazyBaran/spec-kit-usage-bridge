"""Official catalog-issue submission. The reviewed form is data, not executable policy."""
from __future__ import annotations

import json
import re
from pathlib import Path

from github_api import GitHubAPIError
from release.policy import ReleasePolicyError, parse_version

_POLICY_PATH = Path(__file__).resolve().parents[2] / '.github' / 'upstream-submission-policy.json'
_VERSION_LINE = re.compile(r'### Version\s+(\S+)')


def load_submission_policy(path: Path | None = None) -> dict:
    return json.loads((path or _POLICY_PATH).read_text(encoding='utf-8'))


def _owned(issue: dict, policy: dict) -> bool:
    author = ((issue.get('user') or {}).get('login'))
    return policy['marker'] in (issue.get('body') or '') and author == policy['author']


def _triaged(issue: dict, policy: dict) -> bool:
    labels = []
    for label in issue.get('labels') or []:
        labels.append(label.get('name') if isinstance(label, dict) else str(label))
    return policy['triage_label'] in labels or bool(issue.get('linked_pull_request'))


def _version_of(issue: dict) -> str | None:
    match = _VERSION_LINE.search(issue.get('body') or '')
    return match.group(1) if match else None


def choose_submission_action(issues: tuple[dict, ...] | list[dict], release: dict,
                             policy: dict | None = None) -> dict:
    policy = policy or load_submission_policy()
    owned = [issue for issue in issues if _owned(issue, policy)]
    open_owned = [issue for issue in owned if issue.get('state') != 'closed']
    if any(issue.get('state') == 'closed' for issue in owned) and not open_owned:
        return {'action': 'block', 'blockers': ('closed submission',)}
    if len(open_owned) > 1:
        return {'action': 'block', 'blockers': ('ambiguous owned submissions',)}
    if not open_owned:
        return {'action': 'create', 'supersedes': None}
    issue = open_owned[0]
    current = _version_of(issue)
    proposed = parse_version(release['version'])
    existing = parse_version(current) if current else (0, 0, 0)
    if _triaged(issue, policy):
        if proposed > existing:
            return {'action': 'create', 'supersedes': issue['number']}
        return {'action': 'reuse', 'number': issue['number']}
    if proposed > existing:
        return {'action': 'update_untriaged', 'number': issue['number']}
    return {'action': 'reuse', 'number': issue['number']}


def _checked(ready: bool, label: str) -> str:
    return f"- [{'x' if ready else ' '}] {label}"


def _attestations_ready(evidence: dict) -> list[str]:
    provided = evidence.get('attestations') or {}
    missing = []
    if not str(provided.get('real_project') or '').strip():
        missing.append('real_project')
    if provided.get('documentation_review') is not True:
        missing.append('documentation_review')
    if not str(provided.get('security_review') or '').strip():
        missing.append('security_review')
    return missing


def render_submission(manifest: dict, release: dict, evidence: dict, form: dict) -> str:
    policy = load_submission_policy()
    extension = manifest['extension']
    attestations = evidence.get('attestations') or {}
    repository = 'https://github.com/' + release['repository']
    catalog = {
        release['extension_id']: {
            'name': extension['name'],
            'id': extension['id'],
            'version': release['version'],
            'download_url': release['download_url'],
            'sha256': release['zip_sha256'],
            'repository': repository,
            'license': extension['license'],
            'requires': manifest['requires'],
            'provides': {'commands': len(manifest['provides']['commands'])},
            'tags': manifest['tags'],
            'verified': False,
        }
    }
    checklist = '\n'.join((
        _checked(bool(evidence.get('install_verified')), 'Extension installs successfully via download URL'),
        _checked(bool(evidence.get('commands_verified')), 'All commands execute without errors'),
        _checked(attestations.get('documentation_review') is True, 'Documentation is complete and accurate'),
        _checked(bool(str(attestations.get('security_review') or '').strip()),
                 'No security vulnerabilities identified'),
        _checked(bool(str(attestations.get('real_project') or '').strip()), 'Tested on at least one real project'),
    ))
    requirements = '\n'.join((
        _checked(False, 'Valid `extension.yml` manifest included'),
        _checked(False, 'README.md with installation and usage instructions'),
        _checked(False, 'LICENSE file included'),
        _checked(False, 'GitHub release created with version tag'),
        _checked(False, 'All command files exist and are properly formatted'),
        _checked(False, 'Extension ID follows naming conventions (lowercase-with-hyphens)'),
    ))
    details = attestations.get('real_project') or 'Real-project testing was not attested.'
    if not str(attestations.get('security_review') or '').strip():
        details += '\n\nSecurity review was not attested.'
    example = (
        'specify extension add usage-bridge --from ' + release['download_url'] + '\n'
        '/speckit.usage-bridge.report'
    )
    values = {
        'Extension ID': extension['id'],
        'Extension Name': extension['name'],
        'Version': release['version'],
        'Description': extension['description'],
        'Author': extension['author'],
        'Repository URL': repository,
        'Download URL': release['download_url'] + '\n\nSHA-256: ' + release['zip_sha256'],
        'License': extension['license'],
        'Required Spec Kit Version': manifest['requires']['speckit_version'],
        'Number of Commands': str(len(manifest['provides']['commands'])),
        'Tags': ', '.join(manifest['tags']),
        'Key Features': extension['description'],
        'Testing Checklist': checklist,
        'Submission Requirements': requirements,
        'Testing Details': details,
        'Example Usage': example,
        'Proposed Catalog Entry': json.dumps(catalog, indent=2),
    }
    lines = [f"<!-- {policy['marker']} -->", '']
    for heading in form['headings']:
        lines.append(f'### {heading}')
        lines.append('')
        lines.append(str(values.get(heading, '')))
        lines.append('')
    return '\n'.join(lines)


def submit_release(api, release: dict, evidence: dict, *, manifest: dict | None = None) -> dict:
    if release.get('prerelease') or '-' in str(release.get('tag') or ''):
        raise ReleasePolicyError('only a verified stable release can be submitted')
    policy = load_submission_policy()
    if evidence.get('policy_fingerprint') != policy['form_sha256']:
        return {'action': 'block', 'status': 'policy_drift', 'body': '', 'blockers': ('upstream form changed',)}
    form = {'headings': policy['required_headings']}
    body = render_submission(manifest or {}, release, evidence, form)
    missing = _attestations_ready(evidence)
    if missing:
        return {'action': 'block', 'status': 'pending', 'body': body,
                'blockers': tuple('missing attestation: ' + name for name in missing)}
    upstream = policy['upstream_repository']
    try:
        issues = api.pages(f'/repos/{upstream}/issues?state=all&creator={policy["author"]}')
    except GitHubAPIError as exc:
        status = 'forbidden' if exc.status == 403 else 'error'
        return {'action': 'block', 'status': status, 'body': body, 'blockers': (str(exc),)}
    action = choose_submission_action(tuple(issues), release, policy)
    if action['action'] == 'block':
        return {'action': 'block', 'status': 'blocked', 'body': body, 'blockers': action.get('blockers', ())}
    if action['action'] == 'reuse':
        return {'action': 'reuse', 'status': 'reused', 'body': body, 'number': action['number']}
    if action['action'] == 'update_untriaged':
        try:
            current = api.request('GET', f"/repos/{upstream}/issues/{action['number']}")
        except GitHubAPIError as exc:
            status = 'forbidden' if exc.status == 403 else 'error'
            return {'action': 'block', 'status': status, 'body': body, 'blockers': (str(exc),)}
        if _triaged(current, policy):
            return {'action': 'block', 'status': 'race', 'body': body,
                    'blockers': ('issue was triaged between reads',)}
        updated = api.request('PATCH', f"/repos/{upstream}/issues/{action['number']}", {'body': body})
        return {'action': 'update_untriaged', 'status': 'updated', 'body': body,
                'number': updated.get('number', action['number']), 'url': updated.get('html_url')}
    title = '[Extension]: Add usage-bridge'
    if action.get('supersedes'):
        title = '[Extension]: Update usage-bridge'
        body += f"\nSupersedes #{action['supersedes']}\n"
    try:
        created = api.request('POST', f'/repos/{upstream}/issues', {'title': title, 'body': body})
    except GitHubAPIError as exc:
        status = 'forbidden' if exc.status == 403 else 'error'
        return {'action': 'block', 'status': status, 'body': body, 'blockers': (str(exc),)}
    return {'action': 'create', 'status': 'created', 'body': body, 'number': created.get('number'),
            'url': created.get('html_url'), 'supersedes': action.get('supersedes')}
