"""Integration and environment checks (spec §6.3).

One pass over nine checks in a fixed order. FAIL checks decide the exit code; WARN checks only
report. The same script serves the mandatory ``before_specify`` hook, manual runs and team setup
scripts, so it never raises: a check that cannot run reports why instead.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import tu_compat
from .adapters import get_adapter
from .adapters.base import ParseContext
from .config import Config, load_config
from .discovery import SessionFiles, discover, projects_roots
from .log import LOG_REL
from .paths import git, runtime_dir, worktrees
from .pipeline import STATUS_FILE
from .timefmt import parse_ts

FAIL = "FAIL"
WARN = "WARN"
MIN_PYTHON = (3, 9)
STOP_MARKERS = (".specify/events.py", "speckit.usage-bridge.capture")
NOT_RUNNING_AFTER = timedelta(days=1)

PYTHON_FIX = ("Install Python 3.9+ with python3 or python on PATH (or in the project .venv), "
              "then run specify extension add usage-bridge again.")
INTEGRATION_FIX = ("Install a supported Spec Kit integration (claude, codex or cursor-agent), "
                   "or enable an installed runtime in usage-bridge-config.yml.")
EVENTS_FIX = ("Runtime events are disabled or were removed. "
              'Run: specify integration upgrade claude --integration-options="--events true"')
GIT_WARNING = "git not found: branch fallback and worktree discovery are off."
NO_TRANSCRIPTS = "No Claude Code transcripts for this repository yet — run one agent turn, then check again."
NO_PROJECTS_DIR = "No Claude projects directory found — set TOKEN_USAGE_PROJECTS_DIR or CLAUDE_CONFIG_DIR."
NOT_RUNNING = "Transcripts are newer than the last capture by more than a day — check the Stop hook."


@dataclass(frozen=True)
class CheckResult:
    id: str
    level: str  # FAIL | WARN: what a failure of this check means
    ok: bool
    message: str
    remediation: str


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _python(version: Sequence[int]) -> CheckResult:
    major, minor = int(version[0]), int(version[1])
    ok = (major, minor) >= MIN_PYTHON
    return CheckResult("python", FAIL, ok, f"Python {major}.{minor}", "" if ok else PYTHON_FIX)


def _installed(project: Path) -> set[str]:
    doc = _read_json(project / ".specify" / "integration.json")
    doc = doc if isinstance(doc, dict) else {}
    installed = doc.get("installed_integrations")
    keys = {k for k in installed if isinstance(k, str)} if isinstance(installed, list) else set()
    keys |= {v for v in (doc.get("default_integration"), doc.get("integration")) if isinstance(v, str)}
    return {"cursor" if key in ("cursor", "cursor-agent") else key for key in keys}


def _integration(project: Path, enabled: Sequence[str] = ("claude", "codex", "cursor")) -> list[CheckResult]:
    keys = _installed(project) & set(enabled) & {"claude", "codex", "cursor"}
    if keys == {"claude"}:
        return [CheckResult("integration", FAIL, True, "Claude Code integration installed", "")]
    return [CheckResult("integration", FAIL, bool(keys),
                        "Supported integrations: " + ", ".join(sorted(keys)) if keys else "No supported integration",
                        "" if keys else INTEGRATION_FIX)]


def _stop_commands(settings: Any) -> list[str]:
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    entries = hooks.get("Stop") if isinstance(hooks, dict) else None
    commands: list[str] = []
    for entry in entries if isinstance(entries, list) else []:
        for hook in (entry.get("hooks") if isinstance(entry, dict) else None) or []:
            command = hook.get("command") if isinstance(hook, dict) else None
            if isinstance(command, str):
                commands.append(command.replace("\\", "/"))
    return commands


def _stop_hook(project: Path) -> CheckResult:
    commands = _stop_commands(_read_json(project / ".claude" / "settings.json"))
    if any(all(marker in command for marker in STOP_MARKERS) for command in commands):
        return CheckResult("stop-hook", FAIL, True, "the Stop hook runs speckit.usage-bridge.capture", "")
    return CheckResult("stop-hook", FAIL, False,
                       "no Stop hook in .claude/settings.json runs .specify/events.py speckit.usage-bridge.capture",
                       EVENTS_FIX)


def _dispatcher(project: Path) -> CheckResult:
    if (project / ".specify" / "events.py").is_file():
        return CheckResult("dispatcher", FAIL, True, ".specify/events.py is present", "")
    return CheckResult("dispatcher", FAIL, False, ".specify/events.py is missing", EVENTS_FIX)


def _git(project: Path) -> CheckResult:
    version = git(["--version"], project)
    if version:
        return CheckResult("git", WARN, True, version, "")
    return CheckResult("git", WARN, False, "git not found", GIT_WARNING)


def _transcripts(project: Path, env: Mapping[str, str], cfg: Config) -> tuple[CheckResult, list[SessionFiles]]:
    try:
        roots = projects_roots({}, env)
        extra = [Path(os.path.expanduser(d)) for d in cfg.extra_dirs]
        sessions = discover(worktrees(project) or [project], roots, extra)
    except Exception as exc:  # noqa: BLE001 - e.g. a damaged vendored copy; report it, keep checking
        text = f"cannot look for transcripts: {type(exc).__name__}: {exc}"
        return CheckResult("transcripts", WARN, False, text, text), []
    if not roots and not sessions:
        return CheckResult("transcripts", WARN, False, "no Claude projects directory", NO_PROJECTS_DIR), []
    if not sessions:
        return CheckResult("transcripts", WARN, False, "no transcripts for this repository", NO_TRANSCRIPTS), []
    count = len(sessions)
    return CheckResult("transcripts", WARN, True, f"{count} session{'s' if count != 1 else ''} found", ""), sessions


def _runtime(project: Path) -> tuple[CheckResult, Path | None]:
    runtime: Path | None = None
    try:
        runtime = runtime_dir(project, project)
        probe = runtime / f".write-test-{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        text = f"Cannot write {exc.filename or runtime or project}: {exc.strerror or exc}"
        return CheckResult("runtime-dir", FAIL, False, text, text), None
    return CheckResult("runtime-dir", FAIL, True, f"{runtime} is writable", ""), runtime


def _parsed(ts: Any) -> datetime | None:
    try:
        return parse_ts(ts) if isinstance(ts, str) else None
    except ValueError:
        return None


def _age(ts: str | None, now: datetime) -> str:
    when = _parsed(ts)
    if when is None:
        return "no capture yet"
    minutes = max(0, int((now - when).total_seconds() // 60))
    if minutes < 60:
        return f"last capture {minutes} min ago"
    hours = minutes // 60
    return f"last capture {hours} h ago" if hours < 48 else f"last capture {hours // 24} days ago"


def _status(runtime: Path) -> dict[str, Any]:
    """The runtime's ``last-capture.json`` (written by the pipeline); {} when missing or unreadable."""
    doc = _read_json(Path(runtime) / STATUS_FILE)
    return doc if isinstance(doc, dict) else {}


def last_capture_ts(project: Path) -> str | None:
    try:
        ts = _status(runtime_dir(project, project)).get("ts")
    except OSError:
        return None
    return ts if isinstance(ts, str) else None


def _last_capture(runtime: Path | None, sessions: Sequence[SessionFiles], now: datetime) -> CheckResult:
    if runtime is None:
        return CheckResult("last-capture", WARN, True, "not checked: no runtime directory", "")
    status = _status(runtime)
    if not status:
        return CheckResult("last-capture", WARN, True, "no capture yet", "")
    when = _parsed(status.get("ts"))
    shown = when.strftime("%Y-%m-%d %H:%M UTC") if when else str(status.get("ts"))
    if status.get("status") == "error":
        text = f"Last capture failed at {shown}: {status.get('error')} — see {runtime / LOG_REL}"
        return CheckResult("last-capture", WARN, False, "the last capture failed", text)
    stamps = [mtime for s in sessions for _, _, mtime in s.stamps if mtime >= 0]
    if when and stamps:
        newest = datetime.fromtimestamp(max(stamps) / 1e9, tz=when.tzinfo)
        if newest - when > NOT_RUNNING_AFTER:
            return CheckResult("last-capture", WARN, False, "captures do not seem to run", NOT_RUNNING)
    return CheckResult("last-capture", WARN, True, f"{_age(status.get('ts'), now)} ({status.get('status')})", "")


def _config(cfg: Config) -> list[CheckResult]:
    if not cfg.warnings:
        return [CheckResult("config", WARN, True, "configuration ok", "")]
    return [CheckResult("config", WARN, False, "configuration warning", warning) for warning in cfg.warnings]


def run_checks(project: Path, env: Mapping[str, str], now: datetime,
               python_version: tuple[int, int] = tuple(sys.version_info[:2])) -> list[CheckResult]:
    """All checks in the spec's order (the Cursor warning follows ``integration``)."""
    project = Path(project)
    cfg = load_config(project, env)
    installed = _installed(project) & set(cfg.runtime_names)
    if "claude" in installed:
        transcripts, sessions = _transcripts(project, env, cfg)
    else:
        transcripts, sessions = CheckResult("transcripts", WARN, True, "Claude history not required", ""), []
    runtime_result, runtime = _runtime(project)
    native = []
    for name in sorted(installed - {"claude"}):
        native.append(CheckResult(name + ".capture-mode", WARN, True,
                                  "manual capture available; automatic native delivery unverified", ""))
        native.append(CheckResult(name + ".measurement", WARN, True,
                                  "best available measured tokens or activity; missing counts are unavailable", ""))
        if runtime:
            try:
                context = ParseContext(tuple(worktrees(project) or [project]), env, runtime,
                                       cfg.prompt_previews, time.monotonic() + 2, time.monotonic)
                found = list(get_adapter(name).discover(context, cfg))
                native.append(CheckResult(name + ".sources", WARN, bool(found), f"{len(found)} local sessions found",
                                          "" if found else
                                          "Run an agent turn or configure runtime source directories."))
            except Exception as exc:  # noqa: BLE001 - optional sources are diagnostic failures.
                native.append(CheckResult(name + ".sources", WARN, False, "source discovery unavailable",
                                          type(exc).__name__ + ": use manual refresh after restoring local sources."))
    try:
        tu_compat.module()
        vendor = CheckResult("vendor", FAIL, True, "vendored files verified", "")
    except Exception:  # noqa: BLE001 - a damaged package must fail check rather than raise.
        vendor = CheckResult("vendor", FAIL, False, "vendor integrity failed", "Reinstall the extension.")
    hook = (_stop_hook(project) if "claude" in installed else
            CheckResult("stop-hook", WARN, True, "manual capture: no Claude hook required", ""))
    dispatcher = (_dispatcher(project) if "claude" in installed else
                  CheckResult("dispatcher", WARN, True, "manual capture does not require the dispatcher", ""))
    return [_python(python_version), *_integration(project, cfg.runtime_names), hook, dispatcher, _git(project),
            transcripts, runtime_result, _last_capture(runtime, sessions, now), vendor, *native, *_config(cfg)]


def _line(result: CheckResult) -> str:
    if result.ok:
        return f"ok {result.id}: {result.message}"
    return f"{result.level} {result.id}: {result.remediation or result.message}"


def format_results(results: Sequence[CheckResult], verbose: bool, now: datetime, last_capture_ts: str | None) -> str:
    """Healthy → one ``Usage Bridge: ok (…)`` line; otherwise one line per finding (every check with verbose)."""
    shown = list(results) if verbose else [r for r in results if not r.ok]
    if not shown:
        return f"Usage Bridge: ok ({_age(last_capture_ts, now)})\n"
    return "\n".join(_line(r) for r in shown) + "\n"


def failed(results: Sequence[CheckResult]) -> bool:
    """True when a FAIL-level check did not pass (exit 1)."""
    return any(r.level == FAIL and not r.ok for r in results)


def as_json(results: Sequence[CheckResult]) -> dict[str, Any]:
    return {"ok": not failed(results),
            "checks": [{"id": r.id, "level": r.level, "status": "ok" if r.ok else r.level.lower(),
                        "message": r.message, "remediation": r.remediation} for r in results]}
