"""Bounded GitHub REST transport over the gh CLI (development tooling only)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time

API_VERSION = '2022-11-28'
TIMEOUT_SECONDS = 60
MAX_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_DIAGNOSTIC_CHARS = 2000
MAX_ATTEMPTS = 3
PAGE_SIZE = 100
MAX_PAGES = 50
TRANSIENT_STATUSES = {429, 502, 503, 504}
TOKEN_VARIABLES = ('GH_TOKEN', 'GITHUB_TOKEN')
STATUS_PATTERN = re.compile(r'\(HTTP (\d{3})\)')


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


class GitHubAPI:
    def __init__(self, runner=None, sleep=time.sleep) -> None:
        self.runner = runner or default_runner
        self.sleep = sleep

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
                '-H', f'X-GitHub-Api-Version: {API_VERSION}', path]
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
            return json.loads(stdout)
        except ValueError:
            raise GitHubAPIError(f'{method} {path}: response is not valid JSON') from None
