import importlib.util
from pathlib import Path

from scenarios import ALL_SCENARIOS

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("reconcile", ROOT / "tools/reconcile.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_reconcile_matches_upstream_on_scenarios(tmp_path):
    mains = [
        main
        for name in ("split_sessions", "subagents_flat_and_nested", "requests_without_id")
        for main in ALL_SCENARIOS[name](tmp_path / name)
    ]
    rows = mod.reconcile(mains)
    assert rows and all(row["equal"] for row in rows)


def test_reconcile_reports_difference(tmp_path, monkeypatch):
    (main,) = ALL_SCENARIOS["specify_plan_one_session"](tmp_path)
    monkeypatch.setattr(mod, "upstream_usage", lambda path: {"input": -1})
    assert mod.reconcile([main])[0]["equal"] is False
