"""Bounded GitHub REST transport over the gh CLI (development tooling only)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

API_VERSION = '2022-11-28'
TIMEOUT_SECONDS = 60
MAX_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_ASSET_BYTES = 25 * 1024 * 1024
MAX_DIAGNOSTIC_CHARS = 2000
MAX_ATTEMPTS = 3
PAGE_SIZE = 100
MAX_PAGES = 50
TRANSIENT_STATUSES = {429, 502, 503, 504}
TOKEN_VARIABLES = ('GH_TOKEN', 'GITHUB_TOKEN')
STATUS_PATTERN = re.compile(r'\(HTTP (\d{3})\)')
RELEASE_PREDICATE = 'https://github.com/CrazyBaran/spec-kit-usage-bridge/release-source/v1'


def redact(text: str) -> str:
    """Mask credentials from the environment and bound the text's length."""
    for name in TOKEN_VARIABLES:
        secret = os.environ.get(name)
        if secret:
            text = text.replace(secret, '***')
    return text[:MAX_DIAGNOSTIC_CHARS]


class GitHubAPIError(RuntimeError):
    """A failed gh api call carrying the HTTP status and redacted diagnostics."""

    def __init__(self, message: str, status: int | None = None, stderr: str = '') -> None:
        self.status = status
        self.stderr = redact(stderr)
        super().__init__(redact(message))


def default_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, encoding='utf-8',
                          timeout=timeout, shell=False)


def default_binary_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, timeout=timeout, shell=False)


class GitHubAPI:
    def __init__(self, runner=None, sleep=time.sleep, binary_runner=None) -> None:
        self.runner = runner or default_runner
        self.binary_runner = binary_runner or default_binary_runner
        self.sleep = sleep

    @staticmethod
    def _asset_url(url: str, *, upload: bool = False) -> str:
        url = str(url).split('{', 1)[0]
        parsed = urlsplit(url)
        hosts = {'uploads.github.com'} if upload else {'api.github.com', 'github.com'}
        valid_path = (re.fullmatch(r'/repos/[^/]+/[^/]+/releases/\d+/assets', parsed.path)
                      if upload else
                      re.fullmatch(r'/repos/[^/]+/[^/]+/releases/assets/\d+', parsed.path)
                      if parsed.hostname == 'api.github.com' else
                      re.fullmatch(r'/[^/]+/[^/]+/releases/download/[^/]+/[^/]+', parsed.path))
        if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username
                or parsed.password or parsed.port not in (None, 443) or not valid_path
                or parsed.query or parsed.fragment):
            raise GitHubAPIError('refusing an untrusted release asset URL')
        return url

    def upload_asset(self, upload_url: str, name: str, path: Path) -> dict:
        url = self._asset_url(upload_url, upload=True)
        if not name or '/' in name or '\\' in name:
            raise GitHubAPIError('invalid release asset name')
        url += '?name=' + quote(name, safe='')
        argv = ['gh', 'api', '--method', 'POST', '-H', 'Accept: application/vnd.github+json',
                '-H', 'Content-Type: application/octet-stream', '-H',
                f'X-GitHub-Api-Version: {API_VERSION}', url, '--input', str(path)]
        result = self._run(self.runner, argv)
        return self._parse('POST', url, result)

    def download_asset(self, url: str, dest: Path) -> Path:
        url = self._asset_url(url)
        argv = ['gh', 'api', '--method', 'GET', '--allow-escape-sequences',
                '-H', 'Accept: application/octet-stream', url]
        result = self._run(self.binary_runner, argv)
        if result.returncode:
            self._parse('GET', url, subprocess.CompletedProcess(
                argv, result.returncode, '', (result.stderr or b'').decode('utf-8', errors='replace')))
        content = result.stdout or b''
        if not isinstance(content, bytes) or not content or len(content) > MAX_ASSET_BYTES:
            raise GitHubAPIError('downloaded release asset is empty, oversized, or not binary')
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('wb', dir=dest.parent, delete=False) as handle:
                temporary = handle.name
                handle.write(content)
            os.replace(temporary, dest)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return dest

    def verify_attestation(self, path: Path, repo: str, source_sha: str, *,
                           run_id=None, attempt=None) -> bool:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        argv = ['gh', 'attestation', 'verify', str(path), '--repo', repo,
                '--signer-workflow', f'{repo}/.github/workflows/release-pipeline.yml',
                '--source-ref', 'refs/heads/main', '--predicate-type', RELEASE_PREDICATE,
                '--format', 'json']
        result = self._parse('VERIFY', 'attestation', self._run(self.runner, argv))
        for item in result if isinstance(result, list) else []:
            statement = (item.get('verificationResult') or {}).get('statement') or {}
            predicate = statement.get('predicate') or {}
            if (statement.get('predicateType') == RELEASE_PREDICATE
                    and predicate.get('repository') == repo
                    and predicate.get('source_sha') == source_sha
                    and predicate.get('zip_sha256') == digest
                    and (run_id is None or str(predicate.get('run_id')) == str(run_id))
                    and (attempt is None or str(predicate.get('attempt')) == str(attempt))
                    and any((subject.get('digest') or {}).get('sha256') == digest
                            for subject in statement.get('subject') or [])):
                return True
        raise GitHubAPIError('attestation does not bind the archive to the expected release source')

    @staticmethod
    def _run(runner, argv):
        try:
            return runner(argv, TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as error:
            raise GitHubAPIError(f'gh could not run: {error}') from None

    def request(self, method: str, path: str, payload: dict | None = None):
        method = method.upper()
        attempts = MAX_ATTEMPTS if method == 'GET' else 1
        for attempt in range(1, attempts + 1):
            try:
                return self._once(method, path, payload)
            except GitHubAPIError as error:
                if attempt == attempts or not self._retryable(error):
                    raise
                self.sleep(2 ** (attempt - 1))
        raise AssertionError('unreachable')  # pragma: no cover

    def pages(self, path: str) -> list:
        joiner = '&' if '?' in path else '?'
        items: list = []
        for page in range(1, MAX_PAGES + 1):
            body = self.request('GET', f'{path}{joiner}per_page={PAGE_SIZE}&page={page}')
            chunk = self._items(body, path)
            items.extend(chunk)
            if len(chunk) < PAGE_SIZE:
                return items
        raise GitHubAPIError(f'{path}: more than {MAX_PAGES} pages; refusing to continue')

    @staticmethod
    def _items(body, path: str) -> list:
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            lists = [v for k, v in body.items() if k != 'total_count' and isinstance(v, list)]
            if len(lists) == 1:
                return lists[0]
        raise GitHubAPIError(f'{path}: response is not a list or a single wrapped list')

    @staticmethod
    def _retryable(error: GitHubAPIError) -> bool:
        if error.status in TRANSIENT_STATUSES:
            return True
        return error.status == 403 and 'rate limit' in str(error).lower()

    def _once(self, method: str, path: str, payload: dict | None):
        argv = ['gh', 'api', '--method', method,
                '-H', 'Accept: application/vnd.github+json',
                '-H', f'X-GitHub-Api-Version: {API_VERSION}', path.lstrip('/')]
        tmpname = None
        try:
            if payload is not None:
                with tempfile.NamedTemporaryFile(
                        'w', encoding='utf-8', suffix='.json', delete=False) as handle:
                    tmpname = handle.name
                    json.dump(payload, handle)
                argv += ['--input', tmpname]
            try:
                result = self.runner(argv, TIMEOUT_SECONDS)
            except (OSError, subprocess.SubprocessError) as error:
                raise GitHubAPIError(f'{method} {path}: gh could not run: {error}') from None
        finally:
            if tmpname:
                try:
                    os.unlink(tmpname)
                except OSError:
                    pass
        return self._parse(method, path, result)

    @staticmethod
    def _parse(method: str, path: str, result):
        stdout, stderr = result.stdout or '', result.stderr or ''
        if result.returncode != 0:
            found = STATUS_PATTERN.search(stderr)
            status = int(found.group(1)) if found else None
            detail = (stderr.strip() or stdout.strip())[:MAX_DIAGNOSTIC_CHARS]
            raise GitHubAPIError(
                f'{method} {path} failed (exit {result.returncode}, HTTP {status}): {detail}',
                status, stderr + stdout)
        if len(stdout) > MAX_OUTPUT_BYTES:
            raise GitHubAPIError(f'{method} {path}: response exceeds {MAX_OUTPUT_BYTES} bytes')
        if not stdout.strip():
            return None
        try:
            body = json.loads(stdout)
        except ValueError:
            raise GitHubAPIError(f'{method} {path}: response is not valid JSON') from None
        if path.rstrip('/') in ('graphql', '/graphql') and isinstance(body, dict) and body.get('errors'):
            raise GitHubAPIError(f'GraphQL request failed: {json.dumps(body["errors"])}')
        return body
