"""GitHub API transport: argv shape, errors, retries, pagination, redaction."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile

import pytest

from github_api import GitHubAPI, GitHubAPIError

PATH = 'repos/CrazyBaran/spec-kit-usage-bridge/rulesets'


def done(stdout='', stderr='', code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def failure(status, message='boom'):
    return done(json.dumps({'message': message}), f'gh: {message} (HTTP {status})', 1)


class Recorder:
    """Fake runner returning queued results; records argv and --input content."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []
        self.inputs = []

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        if '--input' in argv:
            name = argv[argv.index('--input') + 1]
            with open(name, encoding='utf-8') as handle:
                self.inputs.append((name, handle.read()))
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


@pytest.fixture
def denied_runner():
    return Recorder(failure(403, 'Resource not accessible by integration'))


def make(runner):
    return GitHubAPI(runner=runner, sleep=lambda _s: None)


def test_request_uses_structured_body():
    runner = Recorder(done('{"id": 7}'))
    payload = {'name': 'main', 'body': 'line1\nuse `code` here', 'unicode': 'zażółć'}
    assert make(runner).request('POST', PATH, payload) == {'id': 7}

    argv, timeout = runner.calls[0]
    assert argv[:4] == ['gh', 'api', '--method', 'POST']
    assert argv[4:8] == ['-H', 'Accept: application/vnd.github+json',
                         '-H', 'X-GitHub-Api-Version: 2022-11-28']
    assert argv[8] == PATH
    assert timeout == 60
    tmpfile, content = runner.inputs[0]
    assert argv[-2:] == ['--input', tmpfile]
    assert json.loads(content) == payload
    assert not os.path.exists(tmpfile)


def test_no_payload_means_no_input_and_empty_is_none():
    runner = Recorder(done(''))
    assert make(runner).request('DELETE', PATH) is None
    assert '--input' not in runner.calls[0][0]


def test_input_file_removed_when_runner_fails():
    runner = Recorder(failure(422, 'invalid'))
    with pytest.raises(GitHubAPIError):
        make(runner).request('PUT', PATH, {'a': 1})
    assert not os.path.exists(runner.inputs[0][0])


def test_default_runner_never_uses_shell(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs, argv=argv)
        return done('[]')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    GitHubAPI().request('GET', PATH)
    assert isinstance(seen['argv'], list)
    assert seen['shell'] is False
    assert seen['timeout'] == 60
    assert seen['capture_output'] is True and seen['text'] is True
    assert seen['encoding'] == 'utf-8'


def test_403_is_not_empty_success(denied_runner):
    api = GitHubAPI(runner=denied_runner, sleep=lambda _s: None)
    with pytest.raises(GitHubAPIError):
        api.request('GET', PATH)


@pytest.mark.parametrize('status', [403, 429])
def test_403_and_429_are_not_empty_success(status):
    runner = Recorder(failure(status, 'nope'))
    with pytest.raises(GitHubAPIError) as caught:
        make(runner).request('POST', PATH, {})
    assert caught.value.status == status
    assert len(runner.calls) == 1  # writes are never retried


def test_nonzero_exit_without_status_is_error():
    with pytest.raises(GitHubAPIError) as caught:
        make(Recorder(done('', 'gh: not logged in', 4))).request('GET', PATH)
    assert caught.value.status is None


def test_plain_403_get_is_not_retried():
    runner = Recorder(failure(403, 'Resource not accessible'))
    with pytest.raises(GitHubAPIError):
        make(runner).request('GET', PATH)
    assert len(runner.calls) == 1


def test_get_retries_transient_then_succeeds():
    runner = Recorder(failure(502), failure(503), done('{"ok": true}'))
    assert make(runner).request('GET', PATH) == {'ok': True}
    assert len(runner.calls) == 3


def test_get_retries_rate_limit_403_and_is_bounded():
    runner = Recorder(failure(403, 'API rate limit exceeded'))
    with pytest.raises(GitHubAPIError) as caught:
        make(runner).request('GET', PATH)
    assert caught.value.status == 403
    assert len(runner.calls) == 3


def test_write_not_retried_on_transient():
    runner = Recorder(failure(503), done('{}'))
    with pytest.raises(GitHubAPIError):
        make(runner).request('PATCH', PATH, {})
    assert len(runner.calls) == 1


def test_invalid_json_is_error():
    with pytest.raises(GitHubAPIError):
        make(Recorder(done('not json'))).request('GET', PATH)


def test_oversized_output_is_refused():
    with pytest.raises(GitHubAPIError):
        make(Recorder(done('[' + ' ' * (10 * 1024 * 1024 + 1) + ']'))).request('GET', PATH)


def test_pages_collects_every_page():
    records = [{'n': i} for i in range(101)]
    seen = []

    def runner(argv, timeout):
        seen.append(argv[-1])
        page = int(argv[-1].rsplit('&page=', 1)[1])
        return done(json.dumps(records[(page - 1) * 100:page * 100]))

    assert make(runner).pages(PATH) == records
    assert seen == [PATH + '?per_page=100&page=1', PATH + '?per_page=100&page=2']


def test_pages_respects_existing_query():
    runner = Recorder(done('[]'))
    make(runner).pages(PATH + '?ref=main')
    assert runner.calls[0][0][-1] == PATH + '?ref=main&per_page=100&page=1'


def test_pages_accepts_wrapped_list():
    body = {'total_count': 2, 'check_runs': [{'a': 1}, {'a': 2}]}
    assert make(Recorder(done(json.dumps(body)))).pages(PATH) == [{'a': 1}, {'a': 2}]


def test_pages_rejects_ambiguous_shape():
    with pytest.raises(GitHubAPIError):
        make(Recorder(done(json.dumps({'a': [1], 'b': [2]})))).pages(PATH)
    with pytest.raises(GitHubAPIError):
        make(Recorder(done('"text"'))).pages(PATH)


def test_pages_hard_cap():
    runner = Recorder(done(json.dumps([{}] * 100)))
    with pytest.raises(GitHubAPIError):
        make(runner).pages(PATH)
    assert len(runner.calls) == 50


@pytest.mark.parametrize('name', ['GH_TOKEN', 'GITHUB_TOKEN', 'RELEASE_APP_USER_TOKEN'])
def test_diagnostics_redact_token(monkeypatch, name):
    secret = 'ghp_SUPERSECRET123'
    monkeypatch.setenv(name, secret)
    runner = Recorder(done(json.dumps({'message': f'bad {secret}'}),
                           f'gh: token {secret} rejected (HTTP 401)', 1))
    with pytest.raises(GitHubAPIError) as caught:
        make(runner).request('GET', PATH)
    error = caught.value
    assert error.status == 401
    assert secret not in str(error)
    assert secret not in error.stderr
    assert '***' in error.stderr


def test_diagnostics_are_bounded():
    runner = Recorder(done('', 'x' * 50000 + ' (HTTP 500)', 1))
    with pytest.raises(GitHubAPIError) as caught:
        make(runner).request('POST', PATH, {})
    assert len(caught.value.stderr) <= 2000


def test_upload_sends_exact_binary_to_release_upload_host(tmp_path):
    asset = tmp_path / 'archive.zip'
    asset.write_bytes(b'PK\x00\xff\r\n')
    calls = []

    def runner(argv, timeout):
        calls.append(argv)
        assert open(argv[argv.index('--input') + 1], 'rb').read() == b'PK\x00\xff\r\n'
        return done('{"id": 8, "name": "archive zip.zip"}')

    result = make(runner).upload_asset(
        'https://uploads.github.com/repos/a/b/releases/4/assets{?name,label}',
        'archive zip.zip', asset)
    assert result['id'] == 8
    assert 'https://uploads.github.com/repos/a/b/releases/4/assets?name=archive%20zip.zip' in calls[0]
    assert 'Content-Type: application/octet-stream' in calls[0]


def test_upload_rejects_untrusted_host_before_sending(tmp_path):
    runner = Recorder(done('{}'))
    with pytest.raises(GitHubAPIError):
        make(runner).upload_asset('https://example.test/assets', 'a.zip', tmp_path / 'a')
    assert runner.calls == []


def test_download_preserves_binary_and_failure_preserves_destination(tmp_path):
    dest = tmp_path / 'nested/archive.zip'
    calls = []

    def runner(argv, timeout):
        calls.append(argv)
        if '--allow-escape-sequences' not in argv:
            return done(b'', b'response contains terminal escape sequences', 1)
        return done(b'PK\x00\xff\r\n\x1b[0m', b'')

    api = GitHubAPI(binary_runner=runner)
    assert api.download_asset('https://api.github.com/repos/a/b/releases/assets/4', dest) == dest
    assert dest.read_bytes() == b'PK\x00\xff\r\n\x1b[0m'
    assert 'Accept: application/octet-stream' in calls[0]
    api.binary_runner = lambda *args: done(b'failure', b'HTTP 403', 1)
    with pytest.raises(GitHubAPIError):
        api.download_asset('https://github.com/a/b/releases/download/v1/a.zip', dest)
    assert dest.read_bytes() == b'PK\x00\xff\r\n\x1b[0m'


def test_download_rejects_untrusted_host(tmp_path):
    with pytest.raises(GitHubAPIError):
        GitHubAPI().download_asset('https://evil.test/a.zip', tmp_path / 'a')


def test_download_accepts_valid_archive_above_json_transport_limit(tmp_path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as handle:
        handle.writestr('usage-bridge/data.bin', b'x' * (11 * 1024 * 1024))
    content = archive.getvalue()
    dest = tmp_path / 'archive.zip'
    api = GitHubAPI(binary_runner=lambda *args: done(content, b''))
    api.download_asset('https://api.github.com/repos/a/b/releases/assets/4', dest)
    assert dest.read_bytes() == content
    with zipfile.ZipFile(dest) as handle:
        assert handle.testzip() is None


def test_download_rejects_above_release_asset_limit_without_replacing_destination(tmp_path):
    dest = tmp_path / 'archive.zip'
    dest.write_bytes(b'original')
    content = b'x' * (25 * 1024 * 1024 + 1)
    api = GitHubAPI(binary_runner=lambda *args: done(content, b''))
    with pytest.raises(GitHubAPIError, match='oversized'):
        api.download_asset('https://api.github.com/repos/a/b/releases/assets/4', dest)
    assert dest.read_bytes() == b'original'


def test_real_binary_transport_stops_oversized_producer_before_completion(tmp_path, monkeypatch):
    import github_api

    monkeypatch.setattr(github_api, 'MAX_ASSET_BYTES', 1024)
    completed = tmp_path / 'producer-completed'
    script = ('import sys; from pathlib import Path; '
              '[(sys.stdout.buffer.write(b"x" * 65536), sys.stdout.buffer.flush()) for _ in range(256)]; '
              f'Path({str(completed)!r}).write_text("completed")')
    with pytest.raises(GitHubAPIError, match='oversized'):
        github_api.default_binary_runner([sys.executable, '-c', script], 5)
    assert not completed.exists()


@pytest.mark.parametrize('size', [0, 1024])
def test_real_binary_transport_preserves_bytes_at_or_below_limit(monkeypatch, size):
    import github_api

    monkeypatch.setattr(github_api, 'MAX_ASSET_BYTES', 1024)
    script = f'import sys; sys.stdout.buffer.write(bytes(range(256)) * {size // 256})'
    result = github_api.default_binary_runner([sys.executable, '-c', script], 5)
    assert result.returncode == 0
    assert result.stdout == bytes(range(256)) * (size // 256)
    assert result.stderr == b''


def test_real_binary_transport_bounds_stderr_and_preserves_error_status():
    import github_api

    script = 'import sys; sys.stderr.buffer.write(b"HTTP 403 " + b"x" * 65536); sys.exit(1)'
    result = github_api.default_binary_runner([sys.executable, '-c', script], 5)
    assert result.returncode == 1
    assert result.stdout == b''
    assert result.stderr.startswith(b'HTTP 403 ')
    assert len(result.stderr) == 2000


def test_real_binary_transport_times_out_stalled_producer(monkeypatch):
    import github_api

    started = []
    popen = subprocess.Popen

    def start(*args, **kwargs):
        process = popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(github_api.subprocess, 'Popen', start)
    with pytest.raises(subprocess.TimeoutExpired):
        github_api.default_binary_runner([sys.executable, '-c', 'import time; time.sleep(10)'], 0.5)
    assert len(started) == 1
    assert started[0].poll() is not None


@pytest.mark.parametrize('name', ['GH_TOKEN', 'GITHUB_TOKEN', 'RELEASE_APP_USER_TOKEN'])
@pytest.mark.parametrize('prefix', ['x' * 1990, 'é' * 990], ids=['ascii', 'utf8'])
def test_real_download_redacts_token_crossing_diagnostic_byte_limit(tmp_path, monkeypatch, name, prefix):
    import github_api

    token = 'SYNTHETIC_SECRET_ABCDEFGHIJ'
    monkeypatch.setenv(name, token)
    script = f'import sys; sys.stderr.buffer.write({(prefix + token).encode()!r}); sys.exit(1)'
    api = GitHubAPI(binary_runner=lambda argv, timeout:
                    github_api.default_binary_runner([sys.executable, '-c', script], timeout))
    with pytest.raises(GitHubAPIError) as caught:
        api.download_asset('https://api.github.com/repos/a/b/releases/assets/4', tmp_path / 'archive.zip')
    assert 'SYNTHETIC_' not in str(caught.value)
    assert 'SYNTHETIC_' not in caught.value.stderr


def attestation_result(repo, sha, digest, **extra):
    return json.dumps([{'verificationResult': {'statement': {
        'predicateType': 'https://github.com/CrazyBaran/spec-kit-usage-bridge/release-source/v1',
        'subject': [{'name': 'a.zip', 'digest': {'sha256': digest}}],
        'predicate': {'repository': repo, 'source_sha': sha, 'zip_sha256': digest, **extra},
    }}}])


def test_attestation_verifies_trusted_workflow_and_release_predicate(tmp_path):
    asset = tmp_path / 'a.zip'
    asset.write_bytes(b'archive')
    runner = Recorder(done(attestation_result('a/b', 'a' * 40, hashlib.sha256(b'archive').hexdigest())))
    assert make(runner).verify_attestation(asset, 'a/b', 'a' * 40) is True
    argv = runner.calls[0][0]
    assert argv[:4] == ['gh', 'attestation', 'verify', str(asset)]
    assert argv[argv.index('--repo') + 1] == 'a/b'
    assert '--source-digest' not in argv
    assert argv[argv.index('--source-ref') + 1] == 'refs/heads/main'
    assert argv[argv.index('--signer-workflow') + 1] == 'a/b/.github/workflows/release-pipeline.yml'


@pytest.mark.parametrize('field,value', [('source_sha', 'b' * 40), ('repository', 'evil/repo'),
                                       ('zip_sha256', '0' * 64), ('run_id', 'other'), ('attempt', '2')])
def test_attestation_rejects_wrong_signed_release_evidence(tmp_path, field, value):
    asset = tmp_path / 'a.zip'
    asset.write_bytes(b'archive')
    body = json.loads(attestation_result('a/b', 'a' * 40, hashlib.sha256(b'archive').hexdigest(),
                                        run_id='1', attempt='1'))
    body[0]['verificationResult']['statement']['predicate'][field] = value
    with pytest.raises(GitHubAPIError):
        make(Recorder(done(json.dumps(body)))).verify_attestation(
            asset, 'a/b', 'a' * 40, run_id='1', attempt='1')


def test_graphql_errors_are_not_success():
    with pytest.raises(GitHubAPIError, match='GraphQL'):
        make(Recorder(done('{"data": null, "errors": [{"message": "denied"}]}'))).request(
            'POST', '/graphql', {'query': 'mutation { fake }'})


def test_leading_slash_graphql_uses_cli_graphql_endpoint():
    runner = Recorder(done('{"data": {"ok": true}}'))
    make(runner).request('POST', '/graphql', {'query': 'mutation { fake }', 'variables': {'input': {}}})
    assert runner.calls[0][0][8] == 'graphql'
