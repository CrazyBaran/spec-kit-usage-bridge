import os
import re
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from builders import make_repo
from usage_bridge.paths import (
    author_slug,
    claude_slug,
    current_branch,
    git,
    git_user_name,
    is_inside,
    machine_id,
    project_root,
    runtime_dir,
    same_path,
    slugify,
    work_root,
    worktrees,
)


def test_claude_slug_matches_observed_names():
    assert claude_slug(PureWindowsPath(r"D:\spec-kit-usage-bridge")) == "D--spec-kit-usage-bridge"
    assert claude_slug(PureWindowsPath(r"D:\socialschools-spec-store\.claude\skills")) == (
        "D--socialschools-spec-store--claude-skills")
    assert claude_slug(PurePosixPath("/home/a/my repo")) == "-home-a-my-repo"


def test_claude_slug_non_ascii():
    assert claude_slug(PureWindowsPath(r"C:\Users\Łukasz\proj")) == "C--Users--ukasz-proj"


def test_slug_and_author_precedence():
    assert slugify("  Jakub Baranowski!! ") == "jakub-baranowski" and len(slugify("x" * 99)) == 40
    assert author_slug("JB", "Git Name", "os") == "jb"
    assert author_slug("", "Git Name", "os") == "git-name"
    assert author_slug("", None, "cr4zy") == "cr4zy" and author_slug("", "ŁŁ", "") == "unknown"


def test_machine_id():
    assert machine_id("JAKUB-PC") == machine_id("jakub-pc") and re.fullmatch(r"[0-9a-f]{6}", machine_id("x"))


def test_project_root_walks_up(tmp_path):
    (tmp_path / ".specify").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert project_root(sub) == tmp_path


def test_worktrees_work_root_and_runtime_dir(tmp_path):
    repo = make_repo(tmp_path)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt), "-b", "002-x"], check=True, capture_output=True)
    assert {p.name for p in worktrees(repo)} == {"repo", "wt"}
    assert same_path(work_root(str(wt / "sub"), repo), wt)
    assert same_path(work_root(str(tmp_path / "elsewhere"), repo), repo) and same_path(work_root(None, repo), repo)
    shared = repo / ".git" / "usage-bridge"
    assert same_path(runtime_dir(wt, repo), shared) and shared.is_dir()


def test_runtime_dir_without_git(tmp_path):
    (tmp_path / ".specify").mkdir()
    expected = tmp_path / ".specify" / "extensions" / "usage-bridge" / ".runtime"
    assert same_path(runtime_dir(tmp_path, tmp_path), expected)


def test_branch_and_user(tmp_path):
    repo = make_repo(tmp_path)
    assert current_branch(repo) == "main" and git_user_name(repo) == "Test Author"
    subprocess.run(["git", "-C", str(repo), "checkout", "--detach"], check=True, capture_output=True)
    assert current_branch(repo) is None


def test_git_missing_is_tolerated(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert git(["status"], tmp_path) is None and worktrees(tmp_path) == []


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths")
def test_is_inside_case_insensitive_on_windows():
    assert is_inside(r"d:\REPO\x", [Path(r"D:\repo")]) and not is_inside(r"D:\repo-other", [Path(r"D:\repo")])
