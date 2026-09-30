import json
import os
import time

import pytest

from builders import SessionBuilder, make_repo, projects_root, slug
from usage_bridge.pipeline import run_capture

pytestmark = pytest.mark.perf
MARGIN = float(os.environ.get('UB_PERF_MARGIN', '1'))


def test_cold_and_warm_capture(tmp_path):
    repo = make_repo(tmp_path, features=('001-login',))
    for i in range(200):
        b = SessionBuilder(f's{i:03d}', cwd=repo, branch='001-login')
        b.command('/speckit-implement')
        for j in range(50):
            b.reply(f'r{i}-{j}', input=100, output=200, cache_read=50_000, cache_5m=1_000)
        b.write()
    t = time.perf_counter()
    result = run_capture('', repo, dict(os.environ))
    cold = time.perf_counter() - t
    assert result.status == 'ok', result.error
    b = SessionBuilder('s199', cwd=repo, branch='001-login')
    b.reply('extra', output=1)
    with (projects_root() / slug(repo) / 's199.jsonl').open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(b.entries[-1]) + '\n')
    t = time.perf_counter()
    result = run_capture('', repo, dict(os.environ))
    warm = time.perf_counter() - t
    assert result.status == 'ok', result.error
    assert cold < 5.0 * MARGIN and warm < 1.5 * MARGIN, (cold, warm)


def test_large_active_session_warm_path(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder('big', cwd=repo, branch='001-login')
    b.command('/speckit-implement')
    for j in range(40_000):
        b.reply(f'r{j}', input=10, output=20, cache_read=900_000)
    main = b.write()
    result = run_capture('', repo, dict(os.environ))
    assert result.status == 'ok', result.error
    with main.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps({**b.entries[-1], 'requestId': 'late'}) + '\n')
    t = time.perf_counter()
    result = run_capture('', repo, dict(os.environ))
    elapsed = time.perf_counter() - t
    assert result.status == 'ok', result.error
    assert elapsed < 1.5 * MARGIN, elapsed
