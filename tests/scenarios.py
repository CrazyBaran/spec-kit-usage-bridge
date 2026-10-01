"""Named transcript scenarios (spec §8.2), each writing sessions and returning their main paths.

Used by the parse_session reconciliation oracle and by later rendering/pipeline tests.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from builders import SessionBuilder, make_repo
from usage_bridge.discovery import SessionFiles, discover


def files_for(main: Path) -> SessionFiles:
    """SessionFiles for one main transcript (its folder scanned without the membership check)."""
    (found,) = [s for s in discover([], [], [main.parent]) if s.main == main]
    return found


def specify_plan_one_session(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/speckit-specify", "login page")
    b.reply("r1", input=120, output=900, cache_read=20_000, cache_5m=5_000, chunks=3)
    b.prompt("also mention SSO")
    b.reply("r2", input=80, output=300, cache_read=24_000, cache_5m=800)
    b.command("/speckit-plan")
    b.reply("r3", input=60, output=1_200, cache_read=26_000, cache_5m=1_500)
    return [b.write()]


def split_sessions(tmp: Path) -> list[Path]:
    repo = make_repo(tmp)
    first = SessionBuilder("s1", cwd=repo, branch="001-login")
    first.command("/speckit-specify")
    first.reply("r1", input=100, output=500, cache_read=18_000, cache_5m=26_000)
    first.command("/speckit-plan")
    first.reply("r2", input=50, output=700, cache_read=40_000, cache_5m=2_000)
    second = SessionBuilder("s2", cwd=repo, branch="001-login", start="2026-09-30T08:00:00.000Z")
    second.command("/speckit-tasks")
    second.reply("r3", input=30, output=400, cache_read=30_000, cache_5m=24_000)
    second.reply("r4", input=10, output=200, cache_read=52_000, cache_5m=900)
    return [first.write(), second.write()]


def fork_duplicate_requests(tmp: Path) -> list[Path]:
    repo = make_repo(tmp)
    original = SessionBuilder("s1", cwd=repo, branch="001-login")
    original.command("/speckit-plan")
    original.reply("r1", input=10, output=100, cache_read=1_000)
    original.reply("r2", input=10, output=200, cache_read=2_000)
    fork = SessionBuilder("s2", cwd=repo, branch="001-login")
    fork.command("/speckit-plan")
    fork.reply("r1", input=10, output=100, cache_read=1_000)
    fork.reply("r2", input=10, output=200, cache_read=2_000)
    fork.prompt("continue")
    fork.reply("r3", input=10, output=300, cache_read=3_000)
    return [original.write(), fork.write()]


def branch_created_mid_specify(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="main")
    b.command("/speckit-specify")
    b.reply("r1", output=100)
    b.set_branch("001-login")
    b.reply("r2", output=200)
    return [b.write()]


def subagents_flat_and_nested(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", output=100, cache_read=5_000)
    explore = b.subagent("agent-a1", agent_type="Explore")
    explore.reply("ra1", model="claude-sonnet-5-5", input=50, output=60, cache_read=3_000)
    explore.reply("ra2", model="claude-sonnet-5-5", input=5, output=70, cache_read=3_500)
    nested = b.subagent("workflows/w1/agent-b2", spawn_depth=2)
    nested.reply("rb1", model="claude-haiku-4-5", input=7, output=8)
    b.tick(900)
    b.command("/speckit-tasks")
    b.reply("r2", output=100)
    late = b.subagent("agent-c3")
    late.reply("rc1", output=9)
    return [b.write()]


def compact_manual_and_auto(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/speckit-implement")
    b.reply("r1", output=100, cache_read=400_000)
    b.command("/compact")
    b.compact("manual", 493_564, 29_942)
    b.reply("r2", output=100, cache_5m=30_000)
    b.compact("auto", 967_128, 24_252)
    b.reply("r3", output=100, cache_5m=24_000)
    return [b.write()]


def clear_in_file(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/clear")
    b.command("/speckit-tasks")
    b.reply("r1", output=100)
    return [b.write()]


def clear_new_file(tmp: Path) -> list[Path]:
    repo = make_repo(tmp)
    before = SessionBuilder("s1", cwd=repo, branch="001-login")
    before.command("/speckit-plan")
    before.reply("r1", output=100)
    after = SessionBuilder("s2", cwd=repo, branch="001-login", start="2026-09-29T11:00:00.000Z")
    after.command("/speckit-tasks")
    after.reply("r2", output=100)
    return [before.write(), after.write()]


def sticky_followups(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", output=100)
    b.prompt("also cover rate limiting")
    b.reply("r2", output=50)
    b.prompt("and caching")
    b.reply("r3", output=40)
    return [b.write()]


def two_features_one_session(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp, features=("001-a", "002-b")), branch="001-a")
    b.command("/speckit-specify")
    b.reply("r1", output=100)
    b.set_branch("002-b")
    b.command("/speckit-specify")
    b.reply("r2", output=100)
    return [b.write()]


def non_speckit_work(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="main")
    b.prompt("fix the flaky test")
    b.reply("r1", output=100)
    b.command("/review")
    b.reply("r2", output=100)
    b.reply("r3", output=100, skill="superpowers:brainstorming")
    b.reply("r4", output=100)
    return [b.write()]


def malformed_lines(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", output=100)
    b.raw("{not json")
    b.reply("r2", output=100)
    b.raw('{"type": "assistant", "requestId": "r9", "message": {"usa')
    return [b.write()]


def spaces_in_dir(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp, "my repo"), branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", output=100)
    return [b.write()]


def no_git_extension(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch=None)
    b.command("/speckit-specify")
    b.reply("r1", output=100)
    b.command("/speckit-plan")
    b.reply("r2", output=100)
    return [b.write()]


def feature_switched_mid_session(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp, features=("001-a", "002-b")), branch="001-a")
    b.command("/speckit-plan")
    b.reply("r1", output=100)
    b.set_branch("002-b")
    b.command("/speckit-tasks")
    b.reply("r2", output=100)
    return [b.write()]


def all_invocation_forms(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", output=10)
    b.command("/speckit.plan")
    b.reply("r2", output=20)
    b.command("$speckit-plan")
    b.reply("r3", output=30)
    b.reply("r4", output=40, skill="speckit-plan")
    b.command("/spec-kit:speckit-plan")
    b.reply("r5", output=50)
    return [b.write()]


def hook_and_plugin_skills(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/speckit-plan")
    b.reply("r1", output=10, skill="speckit-git-commit")
    b.reply("r2", output=20, skill="superpowers:writing-plans")
    b.reply("r3", output=30)
    return [b.write()]


def model_mid_phase(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/speckit-implement")
    b.reply("r1", output=10)
    b.command("/model")
    b.reply("r2", model="claude-sonnet-5-5", output=20)
    return [b.write()]


def constitution_then_specify(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp, features=()), branch="main")
    b.command("/speckit-constitution")
    b.reply("r1", output=10)
    b.command("/speckit-specify")
    b.reply("r2", output=20)
    return [b.write()]


def background_subagent_running(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.command("/speckit-implement")
    b.reply("r1", output=10)
    worker = b.subagent("agent-w1")
    worker.tick(300)
    worker.reply("rw1", output=20, stop_reason="tool_use")
    return [b.write()]


def requests_without_id(tmp: Path) -> list[Path]:
    b = SessionBuilder("s1", cwd=make_repo(tmp), branch="001-login")
    b.reply(None, output=5)
    b.command("/speckit-plan")
    b.reply(None, output=6)
    b.reply("r2", output=7)
    return [b.write()]


ALL_SCENARIOS: dict[str, Callable[[Path], list[Path]]] = {
    fn.__name__: fn
    for fn in (
        specify_plan_one_session, split_sessions, fork_duplicate_requests, branch_created_mid_specify,
        subagents_flat_and_nested, compact_manual_and_auto, clear_in_file, clear_new_file, sticky_followups,
        two_features_one_session, non_speckit_work, malformed_lines, spaces_in_dir, no_git_extension,
        feature_switched_mid_session, all_invocation_forms, hook_and_plugin_skills, model_mid_phase,
        constitution_then_specify, background_subagent_running, requests_without_id,
    )
}
