import itertools
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

from builders import SessionBuilder, make_repo, single_session, stop_payload
from usage_bridge import pipeline
from usage_bridge.paths import machine_id
from usage_bridge.pipeline import run_capture
from usage_bridge.render import dump_json
from usage_bridge.timeline import read

GOLDEN_ANNA = Path(__file__).parent / "golden" / "feature" / "sources" / "anna.d4e5f6.json"
own = f"test-author.{machine_id(socket.gethostname())}.json"


def payload(sid, main, cwd):
    return stop_payload(sid, main, cwd)


def three_sessions(tmp_path):
    repo = make_repo(tmp_path, features=("001-login",))
    newest = None
    for i, start in enumerate(("2026-09-29T09:00:00.000Z", "2026-09-29T10:00:00.000Z", "2026-09-29T11:00:00.000Z")):
        b = SessionBuilder(f"s{i}", cwd=repo, branch="001-login", start=start)
        b.command("/speckit-plan")
        b.reply(f"r{i}", output=5)
        newest = (f"s{i}", b.write())
    return repo, payload(newest[0], newest[1], repo)


def test_hook_capture_writes_feature_files(tmp_path):
    repo = make_repo(tmp_path, features=("001-login",))
    b = SessionBuilder("s1", cwd=repo, branch="001-login")
    b.command("/speckit-specify")
    b.reply("r1", output=10)
    b.command("/speckit-plan")
    b.reply("r2", output=20)
    res = run_capture(payload("s1", b.write(), repo), repo, dict(os.environ))
    feat = repo / "specs" / "001-login"
    data = json.loads((feat / "token-usage" / own).read_text(encoding="utf-8"))
    assert res.status == "ok" and res.features_written == ["specs/001-login"]
    assert [r["phase"] for s in data["sessions"] for r in s["runs"]] == ["specify", "plan"]
    assert "| plan |" in (feat / "token-usage.md").read_text(encoding="utf-8")


def test_timeline_entry_is_appended_and_used(tmp_path):
    repo = make_repo(tmp_path)
    (repo / ".specify" / "feature.json").write_text('{"feature_directory": "specs/001-login"}', encoding="utf-8")
    b = SessionBuilder("s1", cwd=repo, branch="main")
    b.command("/speckit-plan")
    b.reply("r1", output=1)
    run_capture(payload("s1", b.write(), repo), repo, dict(os.environ))
    data = json.loads((repo / "specs/001-login/token-usage" / own).read_text(encoding="utf-8"))
    entries = read(repo / ".git" / "usage-bridge")
    assert len(entries) == 2
    assert entries[-1].last_request_id == "r1"
    assert data["sessions"][0]["runs"][0]["attributed_by"] == "timeline"


def test_unchanged_second_capture_writes_nothing(tmp_path):
    repo, raw = single_session(tmp_path)
    run_capture(raw, repo, dict(os.environ))
    md = repo / "specs/001-login/token-usage.md"
    before = md.stat().st_mtime_ns
    assert run_capture(raw, repo, dict(os.environ)).features_written == [] and md.stat().st_mtime_ns == before


@pytest.mark.parametrize("raw", ["{bad", "x" * 2_000_000, '{"conversation_id": "c"}'],
                         ids=["garbage", "oversized", "cursor"])
def test_non_claude_input_is_silent_noop(raw, tmp_path, capfd):
    repo = make_repo(tmp_path)
    assert run_capture(raw, repo, dict(os.environ)).status == "noop" and capfd.readouterr() == ("", "")


def test_disabled_config_is_noop(tmp_path):
    repo, raw = single_session(tmp_path)
    cfg = repo / ".specify/extensions/usage-bridge"
    cfg.mkdir(parents=True)
    (cfg / "usage-bridge-config.yml").write_text("enabled: false\n", encoding="utf-8")
    assert run_capture(raw, repo, dict(os.environ)).status == "noop"
    assert not (repo / "specs/001-login/token-usage.md").exists()


def test_deadline_marks_partial(tmp_path):
    repo, raw = three_sessions(tmp_path)
    ticks = itertools.count(0, 10.0)
    res = run_capture(raw, repo, dict(os.environ), clock=lambda: next(ticks))
    last = json.loads((repo / ".git/usage-bridge/last-capture.json").read_text(encoding="utf-8"))
    assert res.status == "partial" and last["status"] == "partial"
    assert (repo / "specs/001-login/token-usage.md").exists()      # the active session is always digested


def test_lock_contention_skips_but_records_timeline(tmp_path):
    repo, raw = single_session(tmp_path)
    rt = repo / ".git" / "usage-bridge"
    rt.mkdir(parents=True)
    (rt / "lock").write_text("x")
    assert run_capture(raw, repo, dict(os.environ), lock_wait=0.2).status == "skipped" and len(read(rt)) == 1


def test_stale_lock_is_broken(tmp_path):
    repo, raw = single_session(tmp_path)
    rt = repo / ".git" / "usage-bridge"
    rt.mkdir(parents=True)
    lock = rt / "lock"
    lock.write_text("x")
    old = time.time() - 120
    os.utime(lock, (old, old))
    assert run_capture(raw, repo, dict(os.environ), lock_wait=0.2).status == "ok"


def test_worktree_payload_writes_into_worktree(tmp_path):
    repo = make_repo(tmp_path, features=())
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt), "-b", "002-x"], check=True, capture_output=True)
    (wt / "specs" / "002-x").mkdir(parents=True)
    b = SessionBuilder("s1", cwd=wt, branch="002-x")
    b.command("/speckit-plan")
    b.reply("r1", output=1)
    run_capture(payload("s1", b.write(), wt), repo, dict(os.environ))
    assert (wt / "specs/002-x/token-usage.md").exists() and not (repo / "specs" / "002-x").exists()


def test_own_file_removed_when_no_runs(tmp_path):
    repo = make_repo(tmp_path)
    stale = repo / "specs/001-login/token-usage" / own
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    run_capture("", repo, dict(os.environ))
    assert not stale.exists() and not (repo / "specs/001-login/token-usage.md").exists()


def test_other_authors_sources_are_kept_and_merged(tmp_path):
    repo, raw = single_session(tmp_path)
    src = repo / "specs/001-login/token-usage" / "anna.d4e5f6.json"
    data = json.loads(GOLDEN_ANNA.read_text(encoding="utf-8"))
    data["feature"] = {"id": "001-login", "directory": "specs/001-login"}
    src.parent.mkdir(parents=True)
    src.write_text(dump_json(data), encoding="utf-8")
    before = src.read_bytes()
    run_capture(raw, repo, dict(os.environ))
    merged = (repo / "specs/001-login/token-usage.md").read_text(encoding="utf-8")
    assert src.read_bytes() == before and "anna" in merged


def test_unpriced_model_is_listed_even_when_its_last_request_is_empty(tmp_path):
    repo = make_repo(tmp_path, features=("001-login",))
    b = SessionBuilder("s1", cwd=repo, branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", model="mystery-model", input=50, output=10)
    b.reply("r2", model="mystery-model")
    run_capture(payload("s1", b.write(), repo), repo, dict(os.environ))
    data = json.loads((repo / "specs/001-login/token-usage" / own).read_text(encoding="utf-8"))
    assert data["unpriced_models"] == ["mystery-model"]


def test_manual_mode_summary(tmp_path):
    repo, _ = single_session(tmp_path)
    res = run_capture("", repo, dict(os.environ))
    assert res.mode == "manual" and res.summary.startswith("Usage Bridge: ")


def test_exception_is_logged_not_raised(tmp_path, monkeypatch):
    repo, raw = single_session(tmp_path)
    monkeypatch.setattr(pipeline, "digest_session", lambda *a, **k: 1 / 0)
    res = run_capture(raw, repo, dict(os.environ))
    log = (repo / ".git/usage-bridge/logs/usage-bridge.log").read_text(encoding="utf-8")
    assert res.status == "error" and "ZeroDivisionError" in log


def test_splitting_selects_latest_ended_session_not_overlapping_session(tmp_path):
    repo = make_repo(tmp_path)
    intervals = [('long', '09:00:00', '12:00:00'), ('ended', '09:30:00', '09:45:00'),
                 ('overlap', '10:00:00', '10:05:00')]
    for sid, start, end in intervals:
        b = SessionBuilder(sid, cwd=repo, branch='001-login', start=f'2026-09-29T{start}.000Z')
        b.command('/speckit-plan')
        b.reply(sid + '-first', input=10, cache_read=100)
        b.at(f'2026-09-29T{end}.000Z')
        b.reply(sid + '-last', input=20, cache_read=200)
        b.write()
    assert run_capture('', repo, dict(os.environ)).status == 'ok'
    src = json.loads((repo / 'specs/001-login/token-usage' / own).read_text(encoding='utf-8'))
    sessions = {s['session_id']: s for s in src['sessions']}
    assert sessions['ended']['splitting'] is None
    assert sessions['overlap']['splitting']['previous_session_id'] == 'ended'
    assert sessions['overlap']['splitting']['gap_seconds'] == 901


def test_output_directory_stays_within_checkout(tmp_path):
    from usage_bridge.config import Config
    repo = make_repo(tmp_path)
    assert pipeline._output_dir(repo, Config(output_dir='../outside'), 'specs/001-login') == repo / 'specs/001-login'


@pytest.mark.parametrize('failure', ['stat', 'unlink'])
def test_lock_io_failure_checks_deadline_instead_of_spinning(failure, monkeypatch):
    from types import SimpleNamespace
    attempts = []
    class BrokenLock:
        def stat(self):
            if failure == 'stat':
                raise PermissionError('denied')
            return SimpleNamespace(st_mtime=0)
        def unlink(self):
            raise PermissionError('denied')
    lock = pipeline._Lock(Path('unused'))
    lock.path = BrokenLock()
    def occupied(*args):
        attempts.append(1)
        if len(attempts) > 3:
            pytest.fail('lock retry bypassed deadline')
        raise FileExistsError()
    monkeypatch.setattr(pipeline.os, 'open', occupied)
    ticks = iter([0, 10])
    monkeypatch.setattr(pipeline.time, 'monotonic', lambda: next(ticks))
    assert lock.acquire(1) is False
    assert len(attempts) == 1


def test_missed_stop_does_not_move_earlier_phase_to_new_feature(tmp_path):
    repo = make_repo(tmp_path, features=('001-old', '002-new'))
    b = SessionBuilder('s1', cwd=repo, branch='001-old')
    b.command('/speckit-plan')
    b.reply('old-request', output=10)
    b.set_branch('002-new')
    b.command('/speckit-tasks')
    b.reply('new-request', output=20)
    main = b.write()
    env = dict(os.environ, SPECIFY_FEATURE_DIRECTORY='specs/002-new')
    assert run_capture(payload('s1', main, repo), repo, env).status == 'ok'
    old = json.loads((repo / 'specs/001-old/token-usage' / own).read_text(encoding='utf-8'))
    new = json.loads((repo / 'specs/002-new/token-usage' / own).read_text(encoding='utf-8'))
    assert [(r['phase'], r['attributed_by']) for r in old['sessions'][0]['runs']] == [('plan', 'branch')]
    assert [(r['phase'], r['attributed_by']) for r in new['sessions'][0]['runs']] == [('tasks', 'timeline')]


def test_alias_change_counts_sessions_once_preserving_every_source(tmp_path):
    from usage_bridge.config import load_config
    from usage_bridge.render import merge_feature
    repo, raw = single_session(tmp_path)
    old_env = dict(os.environ, SPECKIT_USAGE_BRIDGE_AUTHOR_ALIAS='old-name')
    assert run_capture(raw, repo, old_env).status == 'ok'
    source_dir = repo / 'specs/001-login/token-usage'
    previous = next(source_dir.glob('old-name.*.json'))
    other = source_dir / f'other-author.{machine_id(socket.gethostname())}.json'
    data = json.loads(previous.read_text(encoding='utf-8'))
    data['author']['name'] = 'other-author'
    data['sessions'][0]['session_id'] = 'another-person-session'
    other.write_text(dump_json(data), encoding='utf-8')
    old_bytes, other_bytes = previous.read_bytes(), other.read_bytes()
    env = dict(os.environ, SPECKIT_USAGE_BRIDGE_AUTHOR_ALIAS='new-name')
    assert run_capture(raw, repo, env).status == 'ok'
    sources = pipeline.feature_sources(repo, load_config(repo, env), 'specs/001-login')
    report = merge_feature(sources)
    assert report['totals']['calls'] == 2
    assert report['totals']['sessions'] == 2
    assert previous.read_bytes() == old_bytes
    assert other.read_bytes() == other_bytes
    assert len(sources) == 3
    assert merge_feature(list(reversed(sources))) == report


def test_alias_recapture_uses_current_pricing_and_stays_byte_stable(tmp_path):
    from usage_bridge.config import COMMITTED_FILE, CONFIG_REL, load_config
    from usage_bridge.render import merge_feature
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo, branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", input=0, output=1_000_000)
    raw = payload("s1", b.write(), repo)
    config = repo / CONFIG_REL / COMMITTED_FILE
    config.parent.mkdir(parents=True, exist_ok=True)
    for alias, rate in (("old-name", 9), ("new-name", 1), ("old-name", 2)):
        config.write_text(f"pricing:\n  overrides:\n    claude-opus-5-5:\n      input: 0\n"
                          f"      output: {rate}\n      cache_read: 0\n", encoding="utf-8")
        env = dict(os.environ, SPECKIT_USAGE_BRIDGE_AUTHOR_ALIAS=alias)
        assert run_capture(raw, repo, env).status == "ok"
        sources = pipeline.feature_sources(repo, load_config(repo, env), "specs/001-login")
        report = merge_feature(sources)
        assert report["totals"]["cost_usd"] == rate
        assert report["runs"][0]["author"] == alias
        assert report == merge_feature(list(reversed(sources)))
        directory = repo / "specs/001-login/token-usage"
        before = {p.name: p.read_bytes() for p in directory.glob("*.json")}
        assert run_capture(raw, repo, env).status == "ok"
        assert before == {p.name: p.read_bytes() for p in directory.glob("*.json")}


def test_closing_request_without_timestamp_falls_back_to_branch(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo, branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", output=7)
    main = b.write()
    rows = [json.loads(line) for line in main.read_text(encoding="utf-8").splitlines()]
    rows[-1].pop("timestamp")
    main.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert run_capture(payload("s1", main, repo), repo, dict(os.environ)).status == "ok"
    data = json.loads((repo / "specs/001-login/token-usage" / own).read_text(encoding="utf-8"))
    run = data["sessions"][0]["runs"][0]
    assert run["attributed_by"] == "branch"
    assert run["usage"]["output"] == 7
