"""GitHub API transport: argv shape, errors, retries, pagination, redaction."""
from __future__ import annotations

import json
import os
import subprocess

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


@pytest.mark.parametrize('name', ['GH_TOKEN', 'GITHUB_TOKEN'])
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
