import os
import subprocess

from builders import SessionBuilder, make_repo, projects_root, slug
from usage_bridge.discovery import discover, projects_roots


def ids(found):
    return [s.session_id for s in found]


def test_repo_sessions_found_and_prefix_collision_rejected(tmp_path):
    repo = make_repo(tmp_path, "spec-kit")
    other = make_repo(tmp_path, "spec-kit-usage-bridge")
    for sid, cwd in (("s1", repo), ("s2", other)):
        b = SessionBuilder(sid, cwd=cwd)
        b.reply(f"r-{sid}", output=1)
        b.write()
    assert ids(discover([repo], [projects_root()], [])) == ["s1"]


def test_subdir_and_external_worktree_sessions(tmp_path):
    repo = make_repo(tmp_path)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt), "-b", "002-x"], check=True, capture_output=True)
    (repo / "sub").mkdir()
    for sid, cwd in (("a", repo / "sub"), ("b", wt)):
        b = SessionBuilder(sid, cwd=cwd)
        b.reply(f"r{sid}", output=1)
        b.write()
    assert ids(discover([repo, wt], [projects_root()], [])) == ["a", "b"]


def test_worktree_session_started_in_main_checkout(tmp_path):
    repo = make_repo(tmp_path)
    wt = tmp_path / "wt"
    wt.mkdir()
    b = SessionBuilder("c", cwd=wt)
    b.reply("rc", output=1)
    b.write(projects_root())                                              # written under slug(wt) …
    (projects_root() / slug(wt)).rename(projects_root() / slug(repo))   # … moved to the main checkout's folder
    assert ids(discover([repo, wt], [projects_root()], [])) == ["c"]


def test_extra_dirs_skip_membership(tmp_path):
    repo = make_repo(tmp_path)
    elsewhere = make_repo(tmp_path, "clone")
    b = SessionBuilder("x", cwd=elsewhere)
    b.reply("rx", output=1)
    main = b.write()
    assert ids(discover([repo], [projects_root()], [main.parent])) == ["x"]


def test_recursive_subagents_with_meta(tmp_path):
    b = SessionBuilder("s1", cwd=make_repo(tmp_path))
    b.reply("r1", output=1)
    b.subagent("agent-a1").reply("ra", output=1)
    b.subagent("workflows/w1/agent-b2").reply("rb", output=1)
    b.write()
    (found,) = discover([tmp_path / "repo"], [projects_root()], [])
    assert sorted(p.path.name for p in found.subagents) == ["agent-a1.jsonl", "agent-b2.jsonl"]
    assert all(p.meta is not None and p.meta.exists() for p in found.subagents)


def test_projects_roots_from_payload_and_env(tmp_path):
    root = projects_root()
    (root / "d").mkdir(parents=True)
    roots = projects_roots({"transcript_path": str(root / "d" / "s.jsonl")}, dict(os.environ))
    assert roots[0] == root and len(roots) == len({str(r).lower() for r in roots})


def test_non_ascii_repo_path(tmp_path):
    repo = make_repo(tmp_path, "łukasz repo")
    b = SessionBuilder("s1", cwd=repo)
    b.reply("r1", output=1)
    b.write()
    assert ids(discover([repo], [projects_root()], [])) == ["s1"]


def test_key_changes_when_subagent_grows(tmp_path):
    b = SessionBuilder("s1", cwd=make_repo(tmp_path))
    b.reply("r1", output=1)
    child = b.subagent("agent-a1")
    child.reply("ra", output=1)
    b.write()
    (f1,) = discover([tmp_path / "repo"], [projects_root()], [])
    with f1.subagents[0].path.open("a", encoding="utf-8") as fh:
        fh.write("{}\n")
    (f2,) = discover([tmp_path / "repo"], [projects_root()], [])
    assert f1.key() != f2.key()
