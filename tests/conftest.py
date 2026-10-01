import os
from pathlib import Path

import pytest

GITCONFIG = "[user]\n\tname = Test Author\n\temail = test@example.invalid\n[init]\n\tdefaultBranch = main\n"


def pytest_addoption(parser):
    parser.addoption("--update-golden", action="store_true", default=False, help="rewrite golden files")


@pytest.fixture
def update_golden(request) -> bool:
    return bool(request.config.getoption("--update-golden"))


@pytest.fixture(autouse=True)
def hermetic_env(tmp_path, monkeypatch) -> Path:
    """Point every home, cache, config and git location at the test's temp dir."""
    home = tmp_path / "home"
    home.mkdir()
    for var in list(os.environ):
        if var.startswith(("SPECKIT_USAGE_BRIDGE_", "SPECIFY_FEATURE")):
            monkeypatch.delenv(var)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("TOKEN_USAGE_PROJECTS_DIR", str(home / ".claude" / "projects"))
    monkeypatch.setenv("TOKEN_USAGE_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("TOKEN_USAGE_CURSOR_DIR", str(home / "cursor"))
    monkeypatch.setenv("APPDATA", str(home / "AppData/Roaming"))
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(GITCONFIG, encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return home
