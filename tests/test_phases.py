import pytest

from builders import SessionBuilder, make_repo, projects_root
from usage_bridge.digest import digest_session
from usage_bridge.discovery import discover
from usage_bridge.phases import (
    BUILTIN_COMMANDS,
    Invocation,
    build_runs,
    classify_command,
    installed_extension_ids,
    skill_phase,
)


@pytest.mark.parametrize("name,kind,phase", [
    ("/speckit-plan", "core", "plan"), ("/speckit.plan", "core", "plan"), ("$speckit-plan", "core", "plan"),
    ("/spec-kit:speckit-plan", "core", "plan"), ("/speckit-git-commit", "extension", "git.commit"),
    ("/speckit.git.commit", "extension", "git.commit"),
    ("/speckit-multi-repo-sync-analyze", "extension", "multi-repo-sync.analyze"),
    ("/speckit-unknown-thing", "extension", "speckit-unknown-thing"),
    ("/model", "builtin", "/model"), ("/compact", "builtin", "/compact"), ("/init", "other", "other"),
    ("/review", "other", "other")])
def test_classify_command(name, kind, phase):
    assert classify_command(name, ["git", "multi", "multi-repo-sync"]) == Invocation(kind, phase)


def test_skill_phase():
    assert skill_phase("speckit-tasks") == "tasks" and skill_phase("superpowers:brainstorming") is None
    assert skill_phase("speckit-git-commit") is None


def test_builtin_list_is_exact():
    assert BUILTIN_COMMANDS == frozenset(
        "/add-dir /agents /bug /clear /compact /config /context /cost /doctor /effort "
        "/exit /export /fast /help /hooks /ide /login /logout /mcp /memory /model /permissions /release-notes /resume "
        "/rewind /status /statusline /terminal-setup /theme /upgrade /usage /vim".split())


def runs_of(tmp_path, build, ext=()):
    repo = make_repo(tmp_path)
    b = SessionBuilder("s1", cwd=repo)
    build(b)
    b.write()
    return build_runs(digest_session(discover([repo], [projects_root()], [])[0]), list(ext))


def test_sticky_prompts_and_transparent_model(tmp_path):
    def build(b):
        b.command("/speckit-plan")
        b.reply("r1", output=1)
        b.prompt("more")
        b.command("/model")
        b.reply("r2", output=1)
    (run,) = runs_of(tmp_path, build)
    assert (run.phase, [r.request_id for r in run.requests]) == ("plan", ["r1", "r2"])


def test_hook_skill_folds_core_skill_starts(tmp_path):
    def build(b):
        b.command("/speckit-plan")
        b.reply("r1", output=1, skill="speckit-git-commit")
        b.reply("r2", output=1, skill="speckit-tasks")
        b.reply("r3", output=1)
    plan, tasks = runs_of(tmp_path, build)
    assert (plan.phase, plan.skills, [r.request_id for r in plan.requests]) == ("plan", ["speckit-git-commit"], ["r1"])
    assert (tasks.phase, [r.request_id for r in tasks.requests]) == ("tasks", ["r2", "r3"])


def test_other_runs_and_extension_rows(tmp_path):
    def build(b):
        b.prompt("hi")
        b.reply("r0", output=1)
        b.command("/review")
        b.reply("r1", output=1)
        b.command("/speckit-superspec-brainstorm")
        b.reply("r2", output=1)
    runs = runs_of(tmp_path, build, ext=["superspec"])
    assert [(r.kind, r.phase, r.label) for r in runs] == [
        ("other", "other", "(no command)"), ("other", "other", "/review"),
        ("extension", "superspec.brainstorm", "/speckit-superspec-brainstorm")]


def test_request_before_any_event_starts_other_run(tmp_path):
    (run,) = runs_of(tmp_path, lambda b: b.reply("r0", output=1))
    assert (run.kind, run.label, run.start_ts) == ("other", "(no command)", run.requests[0].ts)


def test_subagent_assigned_to_run_active_at_start(tmp_path):
    def build(b):
        b.command("/speckit-plan")
        b.reply("r1", output=1)
        b.subagent("agent-a1").reply("ra", output=1)
        b.tick(600)
        b.command("/speckit-tasks")
        b.reply("r2", output=1)
    plan, tasks = runs_of(tmp_path, build)
    assert [s.rel_path for s in plan.subagents] == ["agent-a1.jsonl"] and tasks.subagents == []


def test_runs_without_requests_are_dropped_and_after_clear(tmp_path):
    def build(b):
        b.command("/clear")
        b.command("/speckit-plan")
        b.command("/speckit-tasks")
        b.reply("r1", output=1)
    (run,) = runs_of(tmp_path, build)
    assert (run.phase, run.after_clear) == ("tasks", True)


def test_last_branch_is_branch_at_last_request(tmp_path):
    def build(b):
        b.command("/speckit-specify")
        b.reply("r1", output=1)
        b.set_branch("001-login")
        b.reply("r2", output=1)
    assert runs_of(tmp_path, build)[0].last_branch == "001-login"


def test_installed_extension_ids(tmp_path):
    reg = tmp_path / ".specify" / "extensions" / ".registry"
    reg.parent.mkdir(parents=True)
    reg.write_text('{"schema_version": "1.0", "extensions": {"superspec": {}, "git": {}}}', encoding="utf-8")
    assert installed_extension_ids(tmp_path) == ["git", "superspec"] and installed_extension_ids(tmp_path / "x") == []
