"""Handlers behind the ``capture`` and ``report`` scripts (spec §2.1, §4.3-4.4, §6.2).

The ``*_main`` functions take their streams, environment and cwd as arguments so tests can drive
them; the ``*_entry`` functions wire the real process state for the tiny entrypoint scripts.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, TextIO

from .attribution import existing_feature_dirs
from .config import load_config
from .paths import project_root, runtime_dir, same_path
from .pipeline import CaptureResult, feature_sources, run_capture
from .render import dump_json, merge_all, merge_feature, render_all_md, render_feature_md
from .runtime import MANUAL
from .timeline import TimelineEntry, active_feature, read, relative_dir

MAX_STDIN_BYTES = 1 << 20
REPORT_USAGE = "usage: report [feature] [--all] [--json]"


def read_stdin(stream: BinaryIO | None) -> str:
    """The hook payload as text; "" when there is none (no stream, a terminal, EOF).

    At most ``MAX_STDIN_BYTES + 1`` bytes are read. Longer input comes back truncated, never as ""
    (which means a manual run): truncated JSON is garbage that capture ignores silently (spec §8).
    """
    if stream is None:
        return ""
    try:
        if stream.isatty():  # an interactive run must not wait for input
            return ""
        data = stream.read(MAX_STDIN_BYTES + 1) or b""
    except (OSError, ValueError):
        return ""
    text = data.decode("utf-8", errors="replace")
    return text[1:] if text.startswith("﻿") else text


def _manual_line(result: CaptureResult) -> str:
    """Manual mode prints exactly one line (spec §2 step 7), also when nothing was captured."""
    if result.summary:
        return result.summary
    if result.status == "error":
        error = " ".join(str(result.error).split())
        return f"Usage Bridge: capture failed ({error}) — run /speckit-usage-bridge-check for details"
    if result.status == "skipped":
        return "Usage Bridge: another capture is running; try again in a moment"
    return "Usage Bridge: disabled (enabled: false in the configuration)"  # the only manual noop


def capture_main(argv: Sequence[str], stdin: BinaryIO | None, stdout: TextIO, env: Mapping[str, str],
                 cwd: Path) -> int:
    """Silent in hook mode, one summary line in manual mode; always 0 (a failing Stop hook is noise)."""
    try:
        result = run_capture(read_stdin(stdin), Path(cwd), env)
        if result.mode == MANUAL:
            stdout.write(_manual_line(result) + "\n")
    except Exception:  # noqa: BLE001 - run_capture never raises; this guards the stream handling
        pass
    return 0


def _parse_report_args(argv: Sequence[str]) -> tuple[str | None, bool, bool] | None:
    feature: str | None = None
    want_all = as_json = False
    for arg in argv:
        if arg == "--all":
            want_all = True
        elif arg == "--json":
            as_json = True
        elif arg.startswith("-") or feature is not None:
            return None
        else:
            feature = arg
    if want_all and feature is not None:
        return None
    return feature, want_all, as_json


def _match(arg: str, work: Path, known: Sequence[str]) -> str | None:
    """A feature argument: a known directory's path or name, or another directory relative to W."""
    text = relative_dir(arg, work)
    if text is None:
        return None
    if text in known:
        return text
    named = [d for d in known if PurePosixPath(d).name == text]
    if len(named) == 1:
        return named[0]
    return text if (work / text).is_dir() else None


def _last_activity(sources: Sequence[dict[str, Any]]) -> str:
    return max((run.get("end_ts") or "" for src in sources for sess in src.get("sessions", [])
                for run in sess.get("runs", [])), default="")


def _default_feature(work: Path, env: Mapping[str, str], timeline: Sequence[TimelineEntry],
                     sources: Mapping[str, list[dict[str, Any]]]) -> str | None:
    """The active feature, else this checkout's latest timeline feature, else the most recently active one."""
    active, _ = active_feature(work, env)
    if active and (work / active).is_dir():
        return active
    latest: TimelineEntry | None = None
    for entry in timeline:
        if entry.feature_dir and same_path(entry.work_root, work) and (work / entry.feature_dir).is_dir():
            if latest is None or entry.ts >= latest.ts:
                latest = entry
    if latest is not None:
        return latest.feature_dir
    if sources:
        return max(sources, key=lambda d: (_last_activity(sources[d]), d))
    return None


def report_main(argv: Sequence[str], stdout: TextIO, env: Mapping[str, str], cwd: Path) -> int:
    """Refresh (a manual capture), then print one feature's report or the ``--all`` rollup."""
    parsed = _parse_report_args(argv)
    if parsed is None:
        stdout.write(REPORT_USAGE + "\n")
        return 1
    feature, want_all, as_json = parsed
    result = run_capture("", Path(cwd), env)
    work = project_root(Path(cwd)) or Path(cwd)  # a manual run has no payload cwd, so W = P (spec §2.2)
    cfg = load_config(work, env)
    timeline = read(runtime_dir(work, work))
    known = existing_feature_dirs(work, timeline)
    sources = {d: found for d in known if (found := feature_sources(work, cfg, d))}
    names = ", ".join(PurePosixPath(d).name for d in sources) or "none"

    if want_all:
        report = merge_all([merge_feature(s) for s in sources.values()], result.local.get("project", {}),
                           result.local.get("unattributed", {}))
        stdout.write(dump_json(report) if as_json else render_all_md(report))
        return 0
    if feature is not None:
        chosen = _match(feature, work, known)
        if chosen is None:
            stdout.write(f"No feature found for '{feature}'. Features: {names}\n")
            return 1
    else:
        chosen = _default_feature(work, env, timeline, sources)
        if chosen is None:
            stdout.write("No token usage recorded yet.\n")
            return 1
    chosen_sources = sources.get(chosen) or feature_sources(work, cfg, chosen)
    if not chosen_sources:
        stdout.write(f"No token usage recorded for '{PurePosixPath(chosen).name}' yet. Features: {names}\n")
        return 1
    stdout.write(dump_json(merge_feature(chosen_sources)) if as_json else render_feature_md(chosen_sources))
    return 0


def _utf8(stream: TextIO) -> TextIO:
    """Write UTF-8 whatever the locale: a Windows pipe defaults to the ANSI code page, which has no → or ≈."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
    return stream


def capture_entry() -> int:
    try:
        stdin = getattr(sys.stdin, "buffer", None)
        return capture_main(sys.argv[1:], stdin, _utf8(sys.stdout), os.environ, Path.cwd())
    except Exception:  # noqa: BLE001 - the Stop hook must exit 0
        return 0


def report_entry() -> int:
    return report_main(sys.argv[1:], _utf8(sys.stdout), os.environ, Path.cwd())
