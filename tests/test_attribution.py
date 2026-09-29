import pytest

from usage_bridge.attribution import (
    Bucket,
    attribute_runs,
    dedup_across_sessions,
    existing_feature_dirs,
    resolve_branch,
)
from usage_bridge.digest import Request, SessionDigest, SubagentDigest
from usage_bridge.phases import Run
from usage_bridge.timeline import TimelineEntry


def entry(ts, sid="s1", fd=None):
    return TimelineEntry(ts, sid, "w", fd, "feature.json" if fd else "none", None)


def run(phase="plan", end="2026-09-29T10:05:00.000Z", branch=None, sid="s1"):
    return Run(sid, "core", phase, "/speckit-" + phase, end, end, [], [], [], branch, None, False)


def make_digest(session_id, first_ts, request_ids, subagent_ids=()):
    def req(rid):
        return Request(rid, first_ts, "claude-test-1", 0, 0, 0, 0, 0, 0)
    subagents = []
    if subagent_ids:
        subagents = [SubagentDigest("agent-x.jsonl", "agent", 1, first_ts, first_ts, first_ts, True,
                                    [req(rid) for rid in subagent_ids])]
    return SessionDigest(session_id, f"{session_id}.jsonl", first_ts, first_ts, first_ts, [], [], [],
                         [req(rid) for rid in request_ids], subagents)


def test_dedup_keeps_earliest_session():
    d1 = make_digest("s1", "2026-09-29T09:00:00.000Z", ["r1", "r2"])
    d2 = make_digest("s2", "2026-09-29T10:00:00.000Z", ["r2", "r3"], subagent_ids=["r1"])
    (a, b), dropped = dedup_across_sessions([d2, d1])
    assert [r.request_id for r in b.requests] == ["r3"] and b.subagents[0].requests == [] and dropped == 2
    assert [r.request_id for r in a.requests] == ["r1", "r2"]


def test_dedup_ignores_synthetic_ids():
    d1 = make_digest("s1", "2026-09-29T09:00:00.000Z", ["noreq:1"])
    d2 = make_digest("s2", "2026-09-29T10:00:00.000Z", ["noreq:1"])
    assert dedup_across_sessions([d1, d2])[1] == 0


def test_timeline_first_entry_at_or_after_run_end():
    tl = {"s1": [entry("2026-09-29T10:03:00.000Z", fd="specs/001-a"),
                 entry("2026-09-29T10:06:00.000Z", fd="specs/002-b")]}
    (a,) = attribute_runs([run()], tl, ["specs/001-a", "specs/002-b"])
    assert (a.bucket, a.attributed_by) == (Bucket("feature", "specs/002-b"), "timeline")


@pytest.mark.parametrize("branch,known,expected", [
    ("001-login", ["specs/001-login"], "specs/001-login"),
    ("feature/001-login", ["specs/001-login"], "specs/001-login"),
    ("jb/myapp/001-login", ["specs/001-login"], "specs/001-login"),
    ("20260929-140211-login", ["specs/20260929-140211-login-flow"], "specs/20260929-140211-login-flow"),
    ("001-x", ["specs/001-login"], "specs/001-login"),
    ("001-x", ["specs/001-login", "specs/001-logout"], None),
    ("main", ["specs/001-login"], None), (None, ["specs/001-login"], None),
    ("feature/login", ["specs/001-login"], None)])
def test_resolve_branch(branch, known, expected):
    assert resolve_branch(branch, known) == expected


def test_branch_fallback_and_unattributed():
    got = attribute_runs([run(branch="001-login"), run(branch="main")], {}, ["specs/001-login"])
    assert [(a.bucket.kind, a.attributed_by) for a in got] == [("feature", "branch"), ("unattributed", "none")]


def test_first_entry_without_feature_falls_back_to_branch():
    tl = {"s1": [entry("2026-09-29T10:06:00.000Z"), entry("2026-09-29T10:09:00.000Z", fd="specs/002-b")]}
    (a,) = attribute_runs([run(branch="001-login")], tl, ["specs/001-login", "specs/002-b"])
    assert (a.bucket.feature_dir, a.attributed_by) == ("specs/001-login", "branch")


def test_constitution_is_project():
    tl = {"s1": [entry("2026-09-29T10:06:00.000Z", fd="specs/001-a")]}
    (a,) = attribute_runs([run("constitution")], tl, ["specs/001-a"])
    assert a.bucket == Bucket("project", None)


def test_renamed_feature_dir_falls_back_to_branch():
    tl = {"s1": [entry("2026-09-29T10:06:00.000Z", fd="specs/001-login")]}      # renamed since
    (a,) = attribute_runs([run(branch="001-login")], tl, ["specs/001-user-login"])
    assert (a.bucket.feature_dir, a.attributed_by) == ("specs/001-user-login", "branch")


def test_existing_feature_dirs(tmp_path):
    for d in ("specs/001-a", "specs/002-b", "custom/x"):
        (tmp_path / d).mkdir(parents=True)
    tl = [entry("t", fd="custom/x"), entry("t", fd="gone/y")]
    assert existing_feature_dirs(tmp_path, tl) == ["custom/x", "specs/001-a", "specs/002-b"]
