"""Opt-in native delivery smoke tests; skips never establish automatic support."""
import os
import shutil
import subprocess

import pytest
from test_speckit import init, install

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("integration,executable,args", [
    ("codex", "codex", ["exec", "Reply with OK. Do not change any files."]),
    ("cursor-agent", "cursor-agent", ["--print", "Reply with OK. Do not change any files."]),
])
def test_native_event_delivery(tmp_path, integration, executable, args):
    if os.environ.get("UB_NATIVE_SMOKE") != "1":
        pytest.skip("Set UB_NATIVE_SMOKE=1 with an authenticated native agent to verify event delivery")
    binary = shutil.which(executable)
    if not binary:
        pytest.skip(f"{executable} native agent unavailable")
    project = init(tmp_path, integration=integration)
    install(project)
    result = subprocess.run([binary, *args], cwd=project, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, "Native agent failed; inspect its account and project trust configuration"
    assert (project / ".git/usage-bridge/last-capture.json").exists(), "No native event reached Usage Bridge"
