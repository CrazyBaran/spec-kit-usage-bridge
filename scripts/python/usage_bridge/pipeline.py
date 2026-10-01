"""The capture pipeline (spec §2): one run per Claude ``Stop`` and per manual refresh.

Silent by contract: nothing is printed, every failure is logged under the runtime dir and reported
in ``last-capture.json``, and the work is bounded by a deadline well inside the hook timeout (the
dispatcher exits 2 on timeout, which would keep Claude from stopping — spec F9/F18).
"""

from __future__ import annotations

import getpass
import hashlib
import json
import logging
import os
import socket
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from string import Formatter
from typing import Any

from . import __version__, tu_compat
from .adapters import get_adapter
from .adapters.base import ParseContext
from .adapters.codex_usage import exclude_inherited_prefix
from .adapters.cursor_ledger import remove_previews
from .attribution import AttributedRun, attribute_runs, dedup_across_sessions, existing_feature_dirs
from .bindings import binding_feature_dirs, load_bindings
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
from .pricing import estimate, provenance
from .render import (
    SCHEMA_FEATURE,
    author_file,
    dump_json,
    fmt_cost,
    fmt_tokens,
    merge_feature,
    render_feature_md,
    snapshot_revision,
    write_if_changed,
)
from .report_coverage import summarize_runs
from .runtime import CLAUDE, CODEX, CURSOR, MANUAL, detect
from .schema import normalize_source
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
                    pass  # lock I/O failure must still reach the timeout and sleep
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
        fields = list(Formatter().parse(cfg.output_dir))
        if not any(field in ("feature_dir", "feature_id") and not spec and conversion is None
                   for _, field, spec, conversion in fields):
            raise ValueError("a plain {feature_dir} or {feature_id} placeholder is required")
        relative = cfg.output_dir.format(feature_dir=feature_dir, feature_id=PurePosixPath(feature_dir).name)
        if ".." in relative.replace("\\", "/").split("/"):
            raise ValueError("parent traversal can erase the feature-specific path")
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


def _source_dir(work: Path, out_dir: Path) -> Path:
    """Resolve the final source directory before reading, writing or removing reports."""
    try:
        directory = (out_dir / "token-usage").resolve()
        directory.relative_to(Path(work).resolve())
    except (OSError, ValueError, RuntimeError) as exc:
        raise ValueError("token-usage source directory resolves outside the checkout") from exc
    return directory


def feature_sources(work: Path, cfg: Config, feature_dir: str) -> list[dict[str, Any]]:
    """Every readable per-author source file of a feature (other authors' files included)."""
    sources: list[dict[str, Any]] = []
    directory = _source_dir(work, _output_dir(work, cfg, feature_dir))
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("schema") == SCHEMA_FEATURE and isinstance(data.get("sessions"), list):
            try:
                sources.append(normalize_source(data))
            except ValueError:
                continue
    return sources


def _set_snapshot_revisions(entries: list[dict[str, Any]], sources: list[dict[str, Any]],
                            author: str, machine: str) -> None:
    """Advance changed captures across aliases; keep identical captures byte-stable."""
    previous: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for source in sources:
        identity = source.get("author", {})
        if identity.get("machine") == machine:
            for session in source.get("sessions", []):
                previous.setdefault((session.get("runtime", "claude"), session["session_id"]), []).append(
                    (identity.get("name"), session))
    for entry in entries:
        copies = previous.get((entry.get("runtime", "claude"), entry["session_id"]), [])
        revision = max((snapshot_revision(s) for _, s in copies), default=0)
        unchanged = any(name == author and snapshot_revision(s) == revision
                        and dump_json({k: v for k, v in s.items() if k != "snapshot_revision"}) == dump_json(entry)
                        for name, s in copies)
        entry["snapshot_revision"] = revision if unchanged else revision + 1


def _generator(rates: tu_compat.Rates) -> dict[str, str]:
    info = tu_compat.vendored_info()
    return {"usage_bridge": __version__, "token_usage": f"{info.get('ref', '?')}@{str(info.get('commit', ''))[:7]}",
            "pricing": rates.label, "pricing_sha256": rates.sha256, **provenance()}


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
                bucket[key] += value or 0
    return buckets


def load_sources(context: ParseContext, config: Config, active: tuple[str, str] | None):
    """Load extra runtimes independently; failures never erase a saved source."""
    digests = []
    diagnostics = {"parsed": 0, "cached": 0, "partial": False, "warnings": []}
    directory = context.runtime_dir / "adapter-cache"
    directory.mkdir(parents=True, exist_ok=True)
    if not context.keep_previews:
        for path in [*directory.glob("*.json"), *(context.runtime_dir / "cache").glob("*.json")]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("keep_previews"):
                    path.unlink()
            except (OSError, ValueError):
                continue
    names = [name for name in config.runtime_names if name != "claude"]
    names.sort(key=lambda name: active is None or active[0] != name)
    for name in names:
        try:
            adapter = get_adapter(name)
            sources = list(adapter.discover(context, config))
            sources.sort(key=lambda source: source.identity != active)
            for source in sources:
                key = {"v": 5, "runtime": name, "stamps": [list(s) for s in source.stamps],
                       "checkouts": sorted(os.path.normcase(str(root.resolve())) for root in context.checkouts),
                       "keep_previews": context.keep_previews, "vendor": tu_compat.vendored_sha()}
                path = directory / (hashlib.sha256(repr(source.identity).encode()).hexdigest() + ".json")
                try:
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    digest = SessionDigest.from_json(saved["digest"]) if saved.get("key") == key else None
                except (OSError, ValueError, KeyError, TypeError):
                    digest = None
                if digest is not None:
                    diagnostics["cached"] += 1
                elif context.expired():
                    diagnostics["partial"] = True
                    continue
                else:
                    digest = adapter.parse(source, context)
                    diagnostics["parsed"] += 1
                    if "deadline" in digest.reasons:
                        diagnostics["partial"] = True
                        continue  # Retain prior complete snapshot rather than replacing with a truncated prefix.
                    write_if_changed(path, dump_json({"key": key, "keep_previews": context.keep_previews,
                                                     "digest": digest.to_json()}))
                digests.append(digest)
            if context.expired():
                diagnostics["partial"] = True
        except Exception as exc:  # noqa: BLE001 - each optional runtime fails independently.
            diagnostics["partial"] = True
            diagnostics["warnings"].append(f"{name}: {type(exc).__name__}")
    return digests, diagnostics


def _local_summary(runs: Sequence[AttributedRun], rates: tu_compat.Rates) -> dict[str, Any]:
    if any(a.run.runtime != "claude" for a in runs):
        return {"sessions": len({(a.run.runtime, a.run.session_id) for a in runs}),
                **summarize_runs([run_summary(a.run, rates) for a in runs])}
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
        work = work_root(payload.get("cwd") if detected.kind in (CLAUDE, CODEX, CURSOR) else None, project)
        runtime = runtime_dir(work, project)
        log = get_logger(runtime, cfg.log_level)
        for warning in cfg.warnings:
            log.warning("config: %s", warning)
        if detected.kind not in (CLAUDE, CODEX, CURSOR, MANUAL):
            log.info("unrecognised stdin payload ignored")
            return result
        if detected.kind == CURSOR and payload.get("hook_event_name") not in (
                "beforeSubmitPrompt", "stop", "afterAgentResponse", "subagentStart", "subagentStop"):
            log.info("unrecognised Cursor event ignored")
            return result
        deadline = clock() + min(cfg.deadline_seconds, MAX_DEADLINE_SECONDS)
        active_id = payload.get("session_id") or payload.get("thread-id") or payload.get("conversation_id")
        active_runtime = detected.kind if detected.kind != MANUAL else None
        snapshot = None
        if active_runtime and isinstance(active_id, str):
            snapshot = replace(make_entry(active_id, work, env, current_branch(work), now), runtime=active_runtime)
            append(runtime, snapshot)
        lock = _Lock(runtime / "lock")
        if not lock.acquire(lock_wait):
            result.status = "skipped"
            log.info("another capture holds the lock; skipped")
            return result

        checkouts = worktrees(project) or [project]
        context = ParseContext(tuple(checkouts), env, runtime, cfg.prompt_previews, deadline, clock)
        if not cfg.prompt_previews:
            remove_previews(runtime / "cursor-ledgers")
        if active_runtime in cfg.runtime_names:
            get_adapter(active_runtime).record(payload, context)
        extra = [Path(os.path.expanduser(d)) for d in cfg.extra_dirs]
        sessions = discover(checkouts, projects_roots(payload, env), extra) if CLAUDE in cfg.runtime_names else []
        cache = DigestCache(runtime, tu_compat.vendored_sha())
        digests, parsed, cached, deadline_hit = _load_digests(sessions, active_id, cache, cfg.prompt_previews,
                                                              clock, deadline, log)
        extras, diagnostics = load_sources(context, cfg, (active_runtime, active_id) if active_runtime else None)
        digests.extend(extras)
        parsed += diagnostics["parsed"]
        cached += diagnostics["cached"]
        deadline_hit |= diagnostics["partial"]
        for warning in diagnostics["warnings"]:
            log.warning("runtime capture: %s", warning)
        parents = {(d.runtime, d.session_id): d for d in digests}
        digests = [exclude_inherited_prefix(d, parents[d.parent_identity]) if d.parent_identity in parents
                   else replace(d, requests=[], measurement="activity_only",
                                reasons=sorted(set(d.reasons + ["inherited-usage-ambiguous"])))
                   if d.runtime == "codex" and d.parent_identity else d for d in digests]
        # Bind the Stop snapshot to its closing main request, before fork deduplication.
        # The initial snapshot remains useful when capture is skipped, but cannot claim usage.
        if snapshot is not None:
            active = next((d for d in digests if d.session_id == active_id and d.runtime == active_runtime), None)
            if active and active.requests:
                closing = active.requests[-1]
                append(runtime, replace(snapshot, ts=max(snapshot.ts, closing.ts or snapshot.ts),
                                        last_request_id=closing.request_id,
                                        last_request_ts=closing.ts))
            elif active and active.events and active.events[-1].ts:
                event_ts = active.events[-1].ts
                append(runtime, replace(snapshot, ts=max(snapshot.ts, event_ts), last_event_ts=event_ts))
        digests, dropped = dedup_across_sessions(digests)
        extension_ids = installed_extension_ids(project)
        by_id = {(d.runtime, d.session_id): d for d in digests}
        runs = [run for d in digests for run in build_runs(d, extension_ids)]
        timeline_entries = read(runtime)
        known = existing_feature_dirs(work, timeline_entries)
        bindings = load_bindings(runtime, work)
        known = sorted(set(known) | set(binding_feature_dirs(runtime, work)))
        attributed = attribute_runs(runs, by_session(timeline_entries), known, bindings)
        rates = tu_compat.load_rates(cfg.pricing_overrides, runtime)
        for warning in rates.warnings:
            log.warning("pricing: %s", warning)
        author = author_slug(cfg.author_alias, git_user_name(work), _os_user())
        machine = machine_id(socket.gethostname())
        generator = _generator(rates)

        written: list[str] = []
        for feature_dir in known:
            out_dir = _output_dir(work, cfg, feature_dir, log)
            source_dir = _source_dir(work, out_dir)
            feature_runs = [a for a in attributed if a.bucket.kind == "feature" and a.bucket.feature_dir == feature_dir]
            session_ids = {(a.run.runtime, a.run.session_id) for a in feature_runs}
            feature_digests = sorted((by_id[s] for s in session_ids), key=lambda d: (d.first_ts or "", d.session_id))
            entries = []
            for digest in feature_digests:
                own_runs = [a for a in feature_runs if a.run.session_id == digest.session_id
                            and a.run.runtime == digest.runtime]
                eligible = [d for d in feature_digests if d.last_ts and digest.first_ts
                            and d.last_ts < digest.first_ts and d.runtime == digest.runtime]
                previous = max(eligible, key=lambda d: (d.last_ts, d.session_id), default=None)
                entries.append(session_entry(digest, own_runs, rates, previous, cfg.prompt_previews))
            renumber_runs(entries)
            entries = normalize_source({"schema": SCHEMA_FEATURE, "schema_version": 2,
                                        "sessions": entries}, require_metadata=False)["sessions"]
            _set_snapshot_revisions(entries, feature_sources(work, cfg, feature_dir), author, machine)
            changed = False
            own_path = source_dir / f"{author}.{machine}.json"
            historical = [s for src in feature_sources(work, cfg, feature_dir)
                          if src.get("author", {}).get("name") == author
                          and src.get("author", {}).get("machine") == machine for s in src.get("sessions", [])]
            if not cfg.prompt_previews:
                for session in historical:
                    removed = False
                    for row in session.get("runs", []):
                        removed |= "prompt_preview" in row
                        row.pop("prompt_preview", None)
                    if removed:
                        session["snapshot_revision"] = snapshot_revision(session) + 1
            refreshed = {(d.runtime, d.session_id) for d in digests}
            entries.extend(s for s in historical if (s.get("runtime", "claude"), s["session_id"]) not in refreshed)
            if entries:
                state, reasons = completeness(feature_digests, deadline_hit)
                unpriced = sorted({row.model for a in feature_runs
                                   for row in [*a.run.requests, *(r for sub in a.run.subagents for r in sub.requests)]
                                   if "unpriced-model" in estimate(a.run.runtime, row.model, row.flat(), rates,
                                                                  row.measurement)["reasons"]})
                document = author_file(PurePosixPath(feature_dir).name, feature_dir, author, machine, generator,
                                       entries, state, reasons, unpriced)
                changed |= write_if_changed(own_path, dump_json(document), log)
            elif own_path.exists():
                changed |= _remove(own_path, log)  # All local history was refreshed and reassigned, or empty.
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
