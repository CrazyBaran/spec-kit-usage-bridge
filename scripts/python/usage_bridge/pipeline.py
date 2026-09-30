"""The capture pipeline (spec §2): one run per Claude ``Stop`` and per manual refresh.

Silent by contract: nothing is printed, every failure is logged under the runtime dir and reported
in ``last-capture.json``, and the work is bounded by a deadline well inside the hook timeout (the
dispatcher exits 2 on timeout, which would keep Claude from stopping — spec F9/F18).
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import socket
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__, tu_compat
from .attribution import AttributedRun, attribute_runs, dedup_across_sessions, existing_feature_dirs
from .config import MAX_DEADLINE_SECONDS, Config, load_config
from .digest import DigestCache, SessionDigest, digest_session
from .discovery import SessionFiles, discover, projects_roots
from .log import get_logger
from .metrics import completeness, renumber_runs, run_summary, session_entry
from .paths import (
    author_slug,
    current_branch,
    git_user_name,
    machine_id,
    project_root,
    runtime_dir,
    work_root,
    worktrees,
)
from .phases import build_runs, installed_extension_ids
from .render import (
    SCHEMA_FEATURE,
    author_file,
    dump_json,
    fmt_cost,
    fmt_tokens,
    merge_feature,
    render_feature_md,
    write_if_changed,
)
from .runtime import CLAUDE, CURSOR, MANUAL, detect
from .timefmt import iso
from .timeline import active_feature, append, by_session, make_entry, read

LOCK_STALE_SECONDS = 60.0
LOCK_POLL_SECONDS = 0.1
STATUS_FILE = "last-capture.json"


@dataclass
class CaptureResult:
    mode: str
    status: str  # ok | partial | error | skipped | noop
    features_written: list[str] = field(default_factory=list)
    summary: str = ""
    duration_ms: int = 0
    error: str | None = None
    local: dict[str, Any] = field(default_factory=dict)


class _Lock:
    """An exclusive lock file under the runtime dir; stale after 60 s."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.held = False

    def acquire(self, wait: float) -> bool:
        deadline = time.monotonic() + wait
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                self.held = True
                return True
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_SECONDS:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
            except OSError:
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(LOCK_POLL_SECONDS)

    def release(self) -> None:
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.held = False


def _output_dir(work: Path, cfg: Config, feature_dir: str, log: logging.Logger | None = None) -> Path:
    try:
        relative = cfg.output_dir.format(feature_dir=feature_dir, feature_id=PurePosixPath(feature_dir).name)
    except (KeyError, IndexError, ValueError) as exc:
        if log:
            log.warning("invalid output.dir %r (%s); using the feature directory", cfg.output_dir, exc)
        relative = feature_dir
    candidate = Path(work) / relative
    try:
        candidate.resolve().relative_to(Path(work).resolve())
    except (OSError, ValueError, RuntimeError):
        if log:
            log.warning("output.dir leaves the checkout; using the feature directory")
        candidate = Path(work) / feature_dir
    return candidate


def feature_sources(work: Path, cfg: Config, feature_dir: str) -> list[dict[str, Any]]:
    """Every readable per-author source file of a feature (other authors' files included)."""
    sources: list[dict[str, Any]] = []
    for path in sorted((_output_dir(work, cfg, feature_dir) / "token-usage").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("schema") == SCHEMA_FEATURE and isinstance(data.get("sessions"), list):
            sources.append(data)
    return sources


def _generator(rates: tu_compat.Rates) -> dict[str, str]:
    info = tu_compat.vendored_info()
    return {"usage_bridge": __version__, "token_usage": f"{info.get('ref', '?')}@{str(info.get('commit', ''))[:7]}",
            "pricing": rates.label, "pricing_sha256": rates.sha256}


def _load_digests(sessions: Sequence[SessionFiles], active_id: str | None, cache: DigestCache, keep_previews: bool,
                  clock: Callable[[], float], deadline: float, log: logging.Logger) -> tuple[list[SessionDigest],
                                                                                          int, int, bool]:
    ordered = sorted(sessions, key=lambda s: s.session_id != active_id)
    digests: list[SessionDigest] = []
    parsed = cached = 0
    deadline_hit = False
    for files in ordered:
        digest = cache.load(files, keep_previews)
        if digest is not None:
            cached += 1
        elif files.session_id == active_id or clock() < deadline:
            digest = digest_session(files, keep_previews)
            cache.store(files, keep_previews, digest)
            parsed += 1
        else:
            deadline_hit = True
            continue
        digests.append(digest)
    if deadline_hit:
        log.warning("deadline reached: %d session(s) skipped until the next capture",
                    len(ordered) - len(digests))
    return digests, parsed, cached, deadline_hit


def _usage_by_model(runs: Sequence[AttributedRun]) -> dict[str, dict[str, int]]:
    """Summed vendored-key usage per model over the runs' main and subagent requests."""
    buckets: dict[str, dict[str, int]] = {}
    for attributed in runs:
        for request in [*attributed.run.requests, *(r for s in attributed.run.subagents for r in s.requests)]:
            bucket = buckets.setdefault(request.model, dict.fromkeys(("input", "output", "cache_read", "cache_5m",
                                                                      "cache_1h"), 0))
            for key, value in request.flat().items():
                bucket[key] += value
    return buckets


def _local_summary(runs: Sequence[AttributedRun], rates: tu_compat.Rates) -> dict[str, Any]:
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
    calls = 0
    costs: list[float] = []
    for attributed in runs:
        summary = run_summary(attributed.run, rates)
        calls += summary["calls"]
        for key in usage:
            usage[key] += summary["usage"][key]
        if summary["cost_usd"] is not None:
            costs.append(summary["cost_usd"])
    return {"sessions": len({a.run.session_id for a in runs}), "calls": calls, "usage": usage,
            "tokens": sum(usage.values()), "cost_usd": sum(costs) if costs else None}


def _write_status(runtime: Path, now: datetime, result: CaptureResult, parsed: int, cached: int, dropped: int) -> None:
    status = {"ts": iso(now), "mode": result.mode, "status": result.status, "duration_ms": result.duration_ms,
              "sessions_parsed": parsed, "sessions_cached": cached, "features_written": result.features_written,
              "dropped_duplicates": dropped, "error": result.error}
    write_if_changed(Path(runtime) / STATUS_FILE, dump_json(status))


def run_capture(raw_stdin: str, cwd: Path, env: Mapping[str, str], now: datetime | None = None,
                clock: Callable[[], float] = time.monotonic, lock_wait: float = 5.0) -> CaptureResult:
    """Capture token usage for this repository and rewrite changed feature files. Never raises."""
    started = time.perf_counter()
    now = now or datetime.now(timezone.utc)
    detected = detect(raw_stdin)
    mode = MANUAL if detected.kind == MANUAL else "hook"
    result = CaptureResult(mode=mode, status="noop")
    log: logging.Logger | None = None
    runtime: Path | None = None
    lock: _Lock | None = None
    parsed = cached = dropped = 0
    try:
        project = project_root(Path(cwd)) or Path(cwd)
        cfg = load_config(project, env)
        if not cfg.enabled:
            return result
        payload = detected.payload
        work = work_root(payload.get("cwd") if detected.kind == CLAUDE else None, project)
        runtime = runtime_dir(work, project)
        log = get_logger(runtime, cfg.log_level)
        for warning in cfg.warnings:
            log.warning("config: %s", warning)
        if detected.kind == CURSOR:
            log.info("Cursor capture is not supported in v0.1; payload ignored")
            return result
        if detected.kind not in (CLAUDE, MANUAL):
            log.info("unrecognised stdin payload ignored")
            return result
        deadline = clock() + min(cfg.deadline_seconds, MAX_DEADLINE_SECONDS)
        active_id = payload.get("session_id") if detected.kind == CLAUDE else None
        if detected.kind == CLAUDE:
            append(runtime, make_entry(active_id, work, env, current_branch(work), now))
        lock = _Lock(runtime / "lock")
        if not lock.acquire(lock_wait):
            result.status = "skipped"
            log.info("another capture holds the lock; skipped")
            return result

        checkouts = worktrees(project) or [project]
        extra = [Path(os.path.expanduser(d)) for d in cfg.extra_dirs]
        sessions = discover(checkouts, projects_roots(payload, env), extra)
        cache = DigestCache(runtime, tu_compat.vendored_sha())
        digests, parsed, cached, deadline_hit = _load_digests(sessions, active_id, cache, cfg.prompt_previews,
                                                              clock, deadline, log)
        digests, dropped = dedup_across_sessions(digests)
        extension_ids = installed_extension_ids(project)
        by_id = {d.session_id: d for d in digests}
        runs = [run for d in digests for run in build_runs(d, extension_ids)]
        timeline_entries = read(runtime)
        known = existing_feature_dirs(work, timeline_entries)
        attributed = attribute_runs(runs, by_session(timeline_entries), known)
        rates = tu_compat.load_rates(cfg.pricing_overrides, runtime)
        for warning in rates.warnings:
            log.warning("pricing: %s", warning)
        author = author_slug(cfg.author_alias, git_user_name(work), _os_user())
        machine = machine_id(socket.gethostname())
        generator = _generator(rates)

        written: list[str] = []
        for feature_dir in known:
            out_dir = _output_dir(work, cfg, feature_dir, log)
            feature_runs = [a for a in attributed if a.bucket.kind == "feature" and a.bucket.feature_dir == feature_dir]
            session_ids = {a.run.session_id for a in feature_runs}
            feature_digests = sorted((by_id[s] for s in session_ids), key=lambda d: (d.first_ts or "", d.session_id))
            entries = []
            for digest in feature_digests:
                own_runs = [a for a in feature_runs if a.run.session_id == digest.session_id]
                eligible = [d for d in feature_digests if d.last_ts and digest.first_ts
                            and d.last_ts < digest.first_ts]
                previous = max(eligible, key=lambda d: (d.last_ts, d.session_id), default=None)
                entries.append(session_entry(digest, own_runs, rates, previous, cfg.prompt_previews))
            renumber_runs(entries)
            changed = False
            own_path = out_dir / "token-usage" / f"{author}.{machine}.json"
            if entries:
                state, reasons = completeness(feature_digests, deadline_hit)
                unpriced = tu_compat.unpriced(_usage_by_model(feature_runs), rates)
                document = author_file(PurePosixPath(feature_dir).name, feature_dir, author, machine, generator,
                                       entries, state, reasons, unpriced)
                changed |= write_if_changed(own_path, dump_json(document), log)
            elif own_path.exists():
                changed |= _remove(own_path, log)
            md_path = out_dir / "token-usage.md"
            sources = feature_sources(work, cfg, feature_dir)
            if sources:
                changed |= write_if_changed(md_path, render_feature_md(sources), log)
            elif md_path.exists():
                changed |= _remove(md_path, log)
            if changed:
                written.append(feature_dir)

        result.features_written = sorted(written)
        result.local = {
            "project": _local_summary([a for a in attributed if a.bucket.kind == "project"], rates),
            "unattributed": _local_summary([a for a in attributed if a.bucket.kind == "unattributed"], rates),
        }
        result.status = "partial" if deadline_hit else "ok"
        result.summary = _summary_line(result.features_written, work, cfg, env, known)
        return result
    except Exception as exc:  # the hook must never fail loudly
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"
        if log:
            log.error("capture failed:\n%s", traceback.format_exc())
        return result
    finally:
        if lock:
            lock.release()
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        if log:
            for warning in tu_compat.drain_warnings():
                log.warning("token-usage: %s", warning)
            if result.status != "noop":
                log.info("capture %s: status=%s sessions parsed=%d cached=%d written=%s in %d ms", result.mode,
                         result.status, parsed, cached, result.features_written, result.duration_ms)
        if runtime is not None and result.status != "noop":
            try:
                _write_status(runtime, now, result, parsed, cached, dropped)
            except Exception:  # noqa: BLE001 - status reporting must not break capture
                if log:
                    log.error("cannot write %s:\n%s", STATUS_FILE, traceback.format_exc())


def _os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - getpass raises various errors without a login name
        return ""


def _remove(path: Path, log: logging.Logger | None) -> bool:
    try:
        path.unlink()
        return True
    except OSError as exc:
        if log:
            log.warning("cannot remove %s: %s", path, exc)
        return False


def _summary_line(written: list[str], work: Path, cfg: Config, env: Mapping[str, str], known: list[str]) -> str:
    if not written:
        return "Usage Bridge: no changes"
    active, _ = active_feature(work, env)
    focus = active if active in written else written[0]
    sources = feature_sources(work, cfg, focus)
    count = f"{len(written)} feature{'s' if len(written) != 1 else ''} updated"
    if not sources:
        return f"Usage Bridge: {count}"
    totals = merge_feature(sources)["totals"]
    return (f"Usage Bridge: {count} — {PurePosixPath(focus).name} {fmt_tokens(totals['tokens'])} tokens "
            f"(est. {fmt_cost(totals['cost_usd'])})")
