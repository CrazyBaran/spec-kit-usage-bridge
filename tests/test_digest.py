from builders import SessionBuilder, make_repo, projects_root
from usage_bridge.digest import DigestCache, digest_session
from usage_bridge.discovery import discover


def files_of(repo):
    return discover([repo], [projects_root()], [])[0]


def test_events_and_requests_in_order(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.prompt("hi")
    b.command("/speckit-plan")
    b.reply("r1", output=5, skill="speckit-git-commit")
    b.reply("r2", output=6)
    b.write()
    d = digest_session(files_of(repo))
    assert [e.kind for e in d.events] == ["prompt", "command", "skill"]
    assert [(r.request_id, r.event_index) for r in d.requests] == [("r1", 2), ("r2", 2)]


def test_streamed_duplicates_take_field_maxima(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.reply("r1", output=50, cache_read=7, chunks=3)
    b.write()
    (r,) = digest_session(files_of(repo)).requests
    assert (r.output, r.cache_read) == (50, 7)


def test_requests_without_id_count_per_entry(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.reply(None, output=1)
    b.reply(None, output=2)
    b.write()
    reqs = digest_session(files_of(repo)).requests
    assert [r.output for r in reqs] == [1, 2] and all(r.request_id.startswith("noreq:") for r in reqs)


def test_compaction_event(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.compact("manual", 493564, 29942)
    b.write()
    (e,) = [e for e in digest_session(files_of(repo)).events if e.kind == "compact"]
    assert (e.trigger, e.pre_tokens, e.post_tokens) == ("manual", 493564, 29942)


def test_subagents_flat_and_nested(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.reply("r1", output=1)
    b.subagent("agent-a1").reply("ra", output=2)
    b.subagent("workflows/w1/agent-b2", spawn_depth=2).reply("rb", output=3, stop_reason="tool_use")
    b.write()
    subs = sorted(digest_session(files_of(repo)).subagents, key=lambda s: s.rel_path)
    assert [(s.rel_path, s.finished, s.spawn_depth) for s in subs] == [
        ("agent-a1.jsonl", True, 1), ("workflows/w1/agent-b2.jsonl", False, 2)]
    assert subs[0].start_ts == subs[0].first_ts


def test_malformed_and_truncated_lines_are_tolerated(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.reply("r1", output=1)
    b.raw("{not json")
    b.reply("r2", output=2)
    b.raw('{"type": "assistant", "requestId": "r9", "message": {"usa')
    b.write()
    assert [r.request_id for r in digest_session(files_of(repo)).requests] == ["r1", "r2"]


def test_non_object_json_lines_are_skipped(tmp_path):
    # upstream parse_session raises AttributeError on such a line; the digest must not
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.reply("r1", output=1)
    b.raw("[1, 2, 3]")
    b.raw('"just a string"')
    b.reply("r2", output=2)
    b.write()
    assert [r.request_id for r in digest_session(files_of(repo)).requests] == ["r1", "r2"]


def test_branch_changes_and_cwds(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo, branch="main")
    b.reply("r1", output=1)
    b.set_branch("001-login")
    b.reply("r2", output=1)
    b.write()
    d = digest_session(files_of(repo))
    assert [br for _, br in d.branches] == ["main", "001-login"] and d.cwds == [str(repo)]


def test_previews_only_when_enabled(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.prompt("x" * 300)
    b.reply("r1", output=1)
    b.write()
    assert digest_session(files_of(repo)).events[0].prompt is None
    assert digest_session(files_of(repo), keep_previews=True).events[0].prompt == "x" * 120


def test_timestamps_normalised(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.at("2026-09-29T10:40:12Z")
    b.reply("r1", output=1)
    b.write()
    assert digest_session(files_of(repo)).requests[0].ts == "2026-09-29T10:40:12.000Z"


def test_cache_roundtrip_and_invalidation(tmp_path):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    b.reply("r1", output=1)
    main = b.write()
    files = files_of(repo)
    d = digest_session(files)
    cache = DigestCache(tmp_path / "rt", "sha-a")
    cache.store(files, False, d)
    assert cache.load(files, False).to_json() == d.to_json()
    assert cache.load(files, True) is None and DigestCache(tmp_path / "rt", "sha-b").load(files, False) is None
    with main.open("a", encoding="utf-8") as fh:
        fh.write("{}\n")
    assert cache.load(files_of(repo), False) is None
