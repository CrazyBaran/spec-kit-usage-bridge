"""Official catalog-issue submission. The reviewed form is data, not executable policy."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from github_api import GitHubAPIError
from release.policy import ReleasePolicyError, parse_version

_POLICY_PATH = Path(__file__).resolve().parents[2] / '.github' / 'upstream-submission-policy.json'
_VERSION_LINE = re.compile(r'### Version\s+(\S+)')
_SUPERSEDES = re.compile(r'^Supersedes #(\d+)\s*$', re.M)
_BINDING_FIELDS = ('repository', 'version', 'tag', 'source_sha', 'zip_sha256')
_VERIFIED_FLAGS = ('provenance', 'install_verified', 'commands_verified', 'packaging_verified')
_MAX_POLICY_BYTES = 1024 * 1024


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
    if not owned:
        return {'action': 'create', 'supersedes': None}
    open_owned = [issue for issue in owned if issue.get('state') != 'closed']
    try:
        ordered = sorted(owned, key=lambda item: parse_version(_version_of(item) or ''))
    except ReleasePolicyError:
        return {'action': 'block', 'blockers': ('owned submission has no valid version',)}
    if len(open_owned) > 1:
        # Old triaged issues stay open. Only an explicit, ordered supersession
        # chain distinguishes that expected history from unrelated submissions.
        by_number = {item['number']: item for item in owned}
        linked = set()
        for item in open_owned:
            match = _SUPERSEDES.search(item.get('body') or '')
            if not match:
                continue
            previous = by_number.get(int(match.group(1)))
            if (previous is None or not _triaged(previous, policy)
                    or parse_version(_version_of(previous)) >= parse_version(_version_of(item))):
                return {'action': 'block', 'blockers': ('invalid submission supersession',)}
            linked.add(previous['number'])
        leaves = [item for item in open_owned if item['number'] not in linked]
        if len(leaves) != 1:
            return {'action': 'block', 'blockers': ('ambiguous owned submissions',)}
        issue = leaves[0]
    else:
        issue = open_owned[0] if open_owned else ordered[-1]
    current = _version_of(issue)
    proposed = parse_version(release['version'])
    existing = parse_version(current)
    if issue.get('state') == 'closed':
        linked = issue.get('linked_pull_request') or {}
        if not isinstance(linked, dict) or linked.get('merged') is not True:
            return {'action': 'block', 'blockers': ('closed rejected or unverified submission',)}
    if _triaged(issue, policy):
        if proposed > existing:
            return {'action': 'create', 'supersedes': issue['number']}
        return {'action': 'reuse', 'number': issue['number']}
    if proposed > existing:
        action = {'action': 'update_untriaged', 'number': issue['number']}
        match = _SUPERSEDES.search(issue.get('body') or '')
        if match:
            action['supersedes'] = int(match.group(1))
        return action
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


def validate_submission_evidence(release: dict, evidence: dict, manifest: dict) -> None:
    """Validate artifact-bound evidence before any upstream mutation.

    The caller obtains verification and approval in trusted workflow jobs. A
    checkbox or a digest alone cannot substitute for their bound result.
    """
    policy = load_submission_policy()
    parse_version(str(release.get('version') or ''))
    if release.get('tag') != 'v' + release['version'] or release.get('prerelease'):
        raise ReleasePolicyError('only a verified stable release can be submitted')
    if (release.get('repository') != policy['marker'].split(':')[1]
            or release.get('extension_id') != policy['extension_id']
            or release.get('author') != policy['author']):
        raise ReleasePolicyError('submission release identity does not match the reviewed policy')
    if not re.fullmatch(r'[0-9a-f]{40}', str(release.get('source_sha') or '')):
        raise ReleasePolicyError('submission requires the exact source SHA')
    if not re.fullmatch(r'[0-9a-f]{64}', str(release.get('zip_sha256') or '')):
        raise ReleasePolicyError('submission requires the verified archive SHA-256')
    expected_url = (f"https://github.com/{release['repository']}/releases/download/"
                    f"{release['tag']}/usage-bridge-v{release['version']}.zip")
    if release.get('download_url') != expected_url:
        raise ReleasePolicyError('submission download must be the verified stable tag-pinned archive')
    verification = evidence.get('verification') or {}
    if not isinstance(verification, dict):
        raise ReleasePolicyError('submission requires release verification')
    for field in _BINDING_FIELDS:
        if verification.get(field) != release.get(field):
            raise ReleasePolicyError('submission verification does not match ' + field)
    if verification.get('build_sha') != release['source_sha']:
        raise ReleasePolicyError('submission build provenance does not match the source SHA')
    for field in _VERIFIED_FLAGS:
        if verification.get(field) is not True:
            raise ReleasePolicyError('submission is missing successful ' + field)
    for record in (release, verification, evidence):
        override = record.get('override') or {}
        if record.get('waived') or (isinstance(override, dict) and override.get('waived_checks')):
            raise ReleasePolicyError('a release with waived checks cannot be submitted automatically')
    binding = evidence.get('attestation_binding') or {}
    for field in _BINDING_FIELDS:
        if binding.get(field) != release.get(field):
            raise ReleasePolicyError('submission attestations do not match ' + field)
    if _attestations_ready(evidence):
        raise ReleasePolicyError('submission is missing maintainer attestations')
    if evidence.get('readme_verified') is not True:
        raise ReleasePolicyError('source README installation and usage evidence is missing')
    extension = manifest.get('extension') or {}
    for field, expected in (('version', release['version']), ('id', release['extension_id']),
                            ('author', release['author'])):
        if extension.get(field) != expected:
            raise ReleasePolicyError('submission manifest does not match ' + field)


def inspect_upstream_policy(api, policy: dict | None = None) -> dict:
    """Hash all reviewed files at one freshly resolved upstream commit."""
    policy = policy or load_submission_policy()
    upstream = policy['upstream_repository']
    commit = api.request('GET', f'/repos/{upstream}/commits/main')
    sha = str((commit or {}).get('sha') or '')
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ReleasePolicyError('upstream policy commit could not be resolved')
    fingerprints = {}
    for path in policy['reviewed_fingerprints']:
        item = api.request('GET', f'/repos/{upstream}/contents/{quote(path, safe="/")}?ref={sha}')
        if (not isinstance(item, dict) or item.get('type') != 'file'
                or item.get('encoding') != 'base64'
                or not isinstance(item.get('size'), int)
                or not 0 < item['size'] <= _MAX_POLICY_BYTES):
            raise ReleasePolicyError('unsupported upstream policy file: ' + path)
        try:
            raw = base64.b64decode(str(item.get('content') or '').replace('\n', ''), validate=True)
        except (ValueError, binascii.Error):
            raise ReleasePolicyError('invalid upstream policy content: ' + path) from None
        if not raw or len(raw) > _MAX_POLICY_BYTES:
            raise ReleasePolicyError('empty or oversized upstream policy file: ' + path)
        fingerprints[path] = hashlib.sha256(raw).hexdigest()
    changed = [path for path, digest in fingerprints.items()
               if digest != policy['reviewed_fingerprints'][path]]
    return {'commit': sha, 'fingerprints': fingerprints, 'changed': changed}


def _require_published_release(api, release: dict) -> None:
    repo, tag = release['repository'], release['tag']
    published = api.request('GET', f'/repos/{repo}/releases/tags/{tag}')
    if (published.get('draft') is not False or published.get('prerelease') is not False
            or published.get('tag_name') != tag):
        raise ReleasePolicyError('submission requires a published stable release')
    ref = api.request('GET', f'/repos/{repo}/git/ref/tags/{tag}')['object']
    for _ in range(5):
        if ref.get('type') != 'tag':
            break
        ref = api.request('GET', f"/repos/{repo}/git/tags/{ref['sha']}")['object']
    if ref.get('type') != 'commit' or ref.get('sha') != release['source_sha']:
        raise ReleasePolicyError('published tag does not match verified source SHA')
    assets = [item for item in published.get('assets') or []
              if item.get('name') == f"usage-bridge-v{release['version']}.zip"]
    if len(assets) != 1 or assets[0].get('digest') != 'sha256:' + release['zip_sha256']:
        raise ReleasePolicyError('published archive does not match the verified digest')


def _read_submission_state(api, issue: dict, policy: dict) -> dict:
    """Resolve generated PRs from REST timeline events, not synthetic issue fields."""
    state = dict(issue)
    state['linked_pull_request'] = None
    upstream = policy['upstream_repository']
    prefix = f'https://api.github.com/repos/{upstream}/pulls/'
    branches = {f"add-{policy['extension_id']}-extension",
                f"update-{policy['extension_id']}-extension"}
    for event in api.pages(f"/repos/{upstream}/issues/{issue['number']}/timeline"):
        source = ((event.get('source') or {}).get('issue') or {})
        url = str((source.get('pull_request') or {}).get('url') or '')
        if not url.startswith(prefix) or not url[len(prefix):].isdigit():
            continue
        pull = api.request('GET', f"/repos/{upstream}/pulls/{url[len(prefix):]}")
        base = pull.get('base') or {}
        if ((pull.get('head') or {}).get('ref') not in branches or base.get('ref') != 'main'
                or (base.get('repo') or {}).get('full_name') != upstream):
            continue
        state['linked_pull_request'] = {
            'number': pull['number'], 'merged': pull.get('merged') is True,
            'html_url': pull.get('html_url'),
        }
        if pull.get('merged') is True:
            break
    return state


def render_submission(manifest: dict, release: dict, evidence: dict, form: dict) -> str:
    policy = load_submission_policy()
    extension = manifest['extension']
    attestations = evidence.get('attestations') or {}
    verification = evidence.get('verification') or {}
    packaging = verification.get('packaging_verified') is True
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
        _checked(verification.get('install_verified') is True, 'Extension installs successfully via download URL'),
        _checked(verification.get('commands_verified') is True, 'All commands execute without errors'),
        _checked(attestations.get('documentation_review') is True, 'Documentation is complete and accurate'),
        _checked(bool(str(attestations.get('security_review') or '').strip()),
                 'No security vulnerabilities identified'),
        _checked(bool(str(attestations.get('real_project') or '').strip()), 'Tested on at least one real project'),
    ))
    requirements = '\n'.join((
        _checked(packaging, 'Valid `extension.yml` manifest included'),
        _checked(evidence.get('readme_verified') is True, 'README.md with installation and usage instructions'),
        _checked(packaging, 'LICENSE file included'),
        _checked(evidence.get('release_verified') is True, 'GitHub release created with version tag'),
        _checked(packaging and verification.get('commands_verified') is True,
                 'All command files exist and are properly formatted'),
        _checked(bool(re.fullmatch(r'[a-z]+(?:-[a-z]+)*', str(extension.get('id') or ''))),
                 'Extension ID follows naming conventions (lowercase-with-hyphens)'),
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
    form = {'headings': policy['required_headings']}
    body = render_submission(manifest or {}, release, evidence, form)
    missing = _attestations_ready(evidence)
    if missing:
        return {'action': 'block', 'status': 'pending', 'body': body,
                'blockers': tuple('missing attestation: ' + name for name in missing)}
    try:
        validate_submission_evidence(release, evidence, manifest or {})
    except ReleasePolicyError as exc:
        return {'action': 'block', 'status': 'invalid_verification', 'body': body,
                'blockers': (str(exc),)}
    upstream = policy['upstream_repository']
    try:
        inspected = inspect_upstream_policy(api, policy)
        if inspected['changed']:
            return {'action': 'block', 'status': 'policy_drift', 'body': body,
                    'blockers': tuple('upstream policy changed: ' + path for path in inspected['changed']),
                    'upstream_commit': inspected['commit']}
        _require_published_release(api, release)
        body = render_submission(manifest or {}, release, dict(evidence, release_verified=True), form)
        issues = [
            _read_submission_state(api, issue, policy)
            for issue in api.pages(f'/repos/{upstream}/issues?state=all&creator={policy["author"]}')
            if _owned(issue, policy) and not issue.get('pull_request')
        ]
    except ReleasePolicyError as exc:
        return {'action': 'block', 'status': 'invalid_verification', 'body': body,
                'blockers': (str(exc),)}
    except GitHubAPIError as exc:
        status = 'forbidden' if exc.status == 403 else 'error'
        return {'action': 'block', 'status': status, 'body': body, 'blockers': (str(exc),)}
    action = choose_submission_action(tuple(issues), release, policy)
    if action['action'] == 'block':
        return {'action': 'block', 'status': 'blocked', 'body': body, 'blockers': action.get('blockers', ())}
    if action['action'] == 'reuse':
        return {'action': 'reuse', 'status': 'reused', 'body': body, 'number': action['number']}
    if action.get('supersedes'):
        body += f"\nSupersedes #{action['supersedes']}\n"
        previous = next((item for item in issues if item['number'] == action['supersedes']), {})
        pull_url = (previous.get('linked_pull_request') or {}).get('html_url')
        if pull_url:
            body += 'Previous catalog pull request: ' + str(pull_url) + '\n'
    if action['action'] == 'update_untriaged':
        try:
            current = _read_submission_state(api, api.request(
                'GET', f"/repos/{upstream}/issues/{action['number']}"), policy)
        except GitHubAPIError as exc:
            status = 'forbidden' if exc.status == 403 else 'error'
            return {'action': 'block', 'status': status, 'body': body, 'blockers': (str(exc),)}
        if (not _owned(current, policy) or current.get('state') == 'closed'
                or _triaged(current, policy)
                or _version_of(current) != _version_of(next(
                    item for item in issues if item.get('number') == action['number']))):
            return {'action': 'block', 'status': 'race', 'body': body,
                    'blockers': ('issue changed between reads',)}
        updated = api.request('PATCH', f"/repos/{upstream}/issues/{action['number']}", {'body': body})
        return {'action': 'update_untriaged', 'status': 'updated', 'body': body,
                'number': updated.get('number', action['number']), 'url': updated.get('html_url'),
                'supersedes': action.get('supersedes')}
    title = '[Extension]: Add usage-bridge'
    if action.get('supersedes'):
        title = '[Extension]: Update usage-bridge'
    try:
        created = api.request('POST', f'/repos/{upstream}/issues', {'title': title, 'body': body})
    except GitHubAPIError as exc:
        status = 'forbidden' if exc.status == 403 else 'error'
        return {'action': 'block', 'status': status, 'body': body, 'blockers': (str(exc),)}
    return {'action': 'create', 'status': 'created', 'body': body, 'number': created.get('number'),
            'url': created.get('html_url'), 'supersedes': action.get('supersedes')}
