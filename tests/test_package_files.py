import ast
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from builders import make_repo, single_session
from usage_bridge import __version__
from usage_bridge.checks import PYTHON_FIX
from usage_bridge.config import Config, load_config

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_MANIFEST = {  # spec §6.1
    "schema_version": "1.0",
    "extension": {
        "id": "usage-bridge",
        "name": "Usage Bridge — token-usage for Spec Kit",
        "version": "0.2.1",
        "description": "Bridges token-usage into Spec Kit: automatic per-phase, per-feature token & cost audit of the "
                       "SDD flow across sessions, from agent transcripts.",
        "author": "CrazyBaran",
        "repository": "https://github.com/CrazyBaran/spec-kit-usage-bridge",
        "homepage": "https://github.com/CrazyBaran/spec-kit-usage-bridge",
        "license": "MIT",
    },
    "requires": {
        "speckit_version": ">=1.0.12",
        "tools": [
            {"name": "python", "version": ">=3.9", "required": True},
            {"name": "claude", "required": False},
            {"name": "git", "required": False},
        ],
    },
    "provides": {
        "commands": [
            {"name": "speckit.usage-bridge.checkpoint", "file": "commands/checkpoint.md",
             "description": "Bind one observed phase invocation to its explicit feature"},
            {"name": "speckit.usage-bridge.capture", "file": "commands/capture.md",
             "description": "Refresh the token-usage audit now (automatic when native events are delivered)"},
            {"name": "speckit.usage-bridge.report", "file": "commands/report.md",
             "description": "Token usage audit per feature / phase / session"},
            {"name": "speckit.usage-bridge.check", "file": "commands/check.md",
             "description": "Check integration, hooks and environment"},
        ],
        "config": [
            {"name": "usage-bridge-config.yml", "template": "config-template.yml",
             "description": "Usage Bridge settings", "required": False},
        ],
    },
    "events": {"stop": {"command": "speckit.usage-bridge.capture", "timeout": 30},
               "user_prompt_submit": {"command": "speckit.usage-bridge.capture", "timeout": 30}},
    "hooks": {
        "after_specify": {"command": "speckit.usage-bridge.checkpoint", "optional": False,
                          "description": "Bind this specify invocation to its resolved feature"},
        "before_specify": {"command": "speckit.usage-bridge.check", "optional": False,
                           "description": "Usage Bridge capture sanity check"},
        "after_implement": {"command": "speckit.usage-bridge.report", "optional": True,
                            "prompt": "Show the token usage audit for this feature?"},
    },
    "tags": ["tokens", "cost", "observability", "token-usage", "claude-code", "codex", "cursor"],
}

SPEC_BODIES = {  # spec §6.2, verbatim
    "capture": (
        "Run `{SCRIPT}` from the project root and relay its one-line summary. Do not compute or add numbers.\n"
        "Automatic capture requires native event delivery; use this command to refresh manually."
    ),
    "report": (
        "Run `{SCRIPT} $ARGUMENTS` from the project root. It refreshes the audit, then prints a Markdown report.\n"
        "1. Show the output verbatim, including the disclaimer.\n"
        '2. Then add at most two sentences: the most expensive phase, and what the "Session splitting" section '
        "concludes.\n"
        "   Never compute, estimate or round numbers yourself.\n"
        "3. If it prints an error (for example an unknown feature), show it together with the features it lists."
    ),
    "check": (
        "Run `{SCRIPT}` from the project root.\n"
        '- If it prints a single line starting with "Usage Bridge: ok", mention nothing else and continue with what '
        "you were\n"
        "  doing.\n"
        "- Otherwise show its output verbatim — it contains the fix commands — and then continue: this check warns, "
        "it never\n"
        "  blocks the workflow."
    ),
}


def manifest():
    return yaml.safe_load((ROOT / "extension.yml").read_text(encoding="utf-8"))


def run_script(name, repo, stdin=b"", *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/python" / f"{name}.py"), *args], input=stdin,
                          cwd=repo, capture_output=True, env=dict(os.environ))


def load_entrypoint(name, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location(f"_ub_entry_{name}", ROOT / "scripts/python" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["capture.py", "report.py", "check.py", "checkpoint.py"])
def test_entrypoints_parse_with_python36_grammar(name):
    ast.parse((ROOT / "scripts/python" / name).read_text(encoding="utf-8"), feature_version=(3, 6))


def test_capture_entrypoint_is_silent_on_garbage(tmp_path):
    repo = make_repo(tmp_path)
    p = run_script("capture", repo, b"garbage")
    assert (p.returncode, p.stdout, p.stderr) == (0, b"", b"")


@pytest.mark.parametrize("name", ["capture", "report", "check"])
def test_entrypoints_write_no_bytecode(name, tmp_path):
    repo, payload = single_session(tmp_path)
    installed = tmp_path / "installed" / "scripts" / "python"     # a fresh copy: the test run caches the original
    shutil.copytree(ROOT / "scripts/python", installed, ignore=shutil.ignore_patterns("__pycache__"))
    stdin = payload.encode() if name == "capture" else b""
    subprocess.run([sys.executable, str(installed / f"{name}.py")], input=stdin, cwd=repo, capture_output=True,
                   env=dict(os.environ))
    assert (repo / "specs/001-login/token-usage.md").exists() or name == "check"
    assert not list(installed.rglob("*.pyc"))


def test_report_entrypoint_prints_utf8(tmp_path):
    repo, _ = single_session(tmp_path)
    p = run_script("report", repo)
    assert p.returncode == 0 and "Start → end (UTC)" in p.stdout.decode("utf-8") and p.stderr == b""


def test_check_entrypoint_reports_findings(tmp_path):
    p = run_script("check", make_repo(tmp_path))
    assert p.returncode == 1 and "FAIL integration: Install a supported Spec Kit integration" in p.stdout.decode()


@pytest.mark.parametrize("name,code,expected", [
    ("capture", 0, ""),
    ("report", 1, f"Usage Bridge: Python 3.8 is too old. {PYTHON_FIX}\n"),
    ("check", 1, f"FAIL python: {PYTHON_FIX}\n")], ids=["capture", "report", "check"])
def test_old_python(name, code, expected, monkeypatch, capsys):
    module = load_entrypoint(name, monkeypatch)
    monkeypatch.setattr(sys, "version_info", (3, 8, 18))
    assert module._run() == code and capsys.readouterr().out == expected


@pytest.mark.parametrize("name,code", [("capture", 0), ("report", 1), ("check", 1)])
def test_broken_package_import(name, code, monkeypatch, capsys):
    module = load_entrypoint(name, monkeypatch)
    monkeypatch.setitem(sys.modules, "usage_bridge", None)       # makes `from usage_bridge import cli` fail
    assert module._run() == code
    out = capsys.readouterr().out
    assert out == "" if code == 0 else out.startswith("Usage Bridge: cannot load the extension (")


def test_manifest_matches_spec():
    assert manifest() == EXPECTED_MANIFEST


def test_manifest_version_matches_package():
    assert manifest()["extension"]["version"] == __version__


@pytest.mark.parametrize("cmd", ["capture", "report", "check"])
def test_command_files(cmd):
    text = (ROOT / "commands" / f"{cmd}.md").read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---")[1])
    commands = {c["name"]: c for c in manifest()["provides"]["commands"]}
    assert front["description"] == commands[f"speckit.usage-bridge.{cmd}"]["description"]
    assert front["scripts"] == {"py": f"scripts/python/{cmd}.py"} and "{SCRIPT}" in text
    keys = {"description", "scripts"} | ({"argument-hint"} if cmd == "report" else set())
    assert set(front) == keys
    assert text.split("---", 2)[2].strip() == SPEC_BODIES[cmd]
    assert text.startswith("---\n") and "\r" not in text


def test_report_argument_hint():
    text = (ROOT / "commands/report.md").read_text(encoding="utf-8")
    assert yaml.safe_load(text.split("---")[1])["argument-hint"] == "[feature-id | --all] [--json]"


def test_config_template_yields_defaults(tmp_path):
    d = tmp_path / ".specify/extensions/usage-bridge"
    d.mkdir(parents=True)
    shutil.copy(ROOT / "config-template.yml", d / "usage-bridge-config.yml")
    assert load_config(tmp_path, {}) == Config()


def test_config_template_is_the_spec_block():
    text = (ROOT / "config-template.yml").read_text(encoding="utf-8")
    assert yaml.safe_load(text) == {
        "enabled": True, "output": {"dir": "{feature_dir}"}, "transcripts": {"extra_dirs": []},
        "pricing": {"overrides": {}}, "privacy": {"prompt_previews": False}, "capture": {"deadline_seconds": 15},
        "log": {"level": "info"}, "runtimes": {"enabled": ["claude", "codex", "cursor"],
        "codex": {"extra_dirs": []}, "cursor": {"extra_dirs": [], "data_dir": ""}}}
