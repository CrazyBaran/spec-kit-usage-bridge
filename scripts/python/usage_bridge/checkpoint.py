"""Explicit, invocation-scoped checkpoints. Source selection runs in a bounded worker."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import TextIO

from .adapters import get_adapter
from .adapters.base import ParseContext
from .attribution import attribute_runs, existing_feature_dirs
from .bindings import FeatureBinding, load_bindings, save_binding, select_run
from .config import MAX_DEADLINE_SECONDS, load_config
from .paths import project_root, runtime_dir
from .phases import build_runs, installed_extension_ids
from .pipeline import _Lock, run_capture
from .timeline import by_session, read, relative_dir


def _parser():
    parser = argparse.ArgumentParser(description='Preview or bind one observed phase invocation to a feature.')
    parser.add_argument('--runtime', choices=['claude', 'codex', 'cursor'])
    parser.add_argument('--session-id')
    parser.add_argument('--feature', required=True)
    parser.add_argument('--phase', required=True)
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument('--invocation-ts')
    selector.add_argument('--latest', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--workflow', action='store_true')
    parser.add_argument('--_select', action='store_true', help=argparse.SUPPRESS)
    return parser


def _select(options, env, work, runtime, cfg):
    deadline = time.monotonic() + min(cfg.deadline_seconds, MAX_DEADLINE_SECONDS)
    context = ParseContext((work,), env, runtime, False, deadline, time.monotonic)
    adapter = get_adapter(options.runtime)
    sources = [s for s in adapter.discover(context, cfg) if s.session_id == options.session_id]
    if context.expired():
        raise ValueError('source discovery timed out; retry checkpoint')
    if len(sources) != 1:
        raise ValueError('session identity has no unique owned source in this checkout')
    digest = adapter.parse(sources[0], context)
    if context.expired():
        raise ValueError('source parsing timed out; retry checkpoint')
    run = select_run(build_runs(digest, installed_extension_ids(work), include_empty=True),
                     options.runtime, options.session_id,
                     options.phase, options.invocation_ts, options.latest)
    binding = FeatureBinding(options.runtime, options.session_id, str(work), options.feature,
                             options.phase, run.start_ts)
    bindings = load_bindings(runtime, work)
    timeline = read(runtime)
    known = sorted(set(existing_feature_dirs(work, timeline)) | {b.feature_dir for b in bindings
                                                               if (work / b.feature_dir).is_dir()})
    previous = attribute_runs([run], by_session(timeline), known, bindings)[0]
    return {'binding': asdict(binding), 'previous': previous.bucket.feature_dir or previous.bucket.kind}


def checkpoint_main(argv: Sequence[str], stdout: TextIO, env: Mapping[str, str], cwd: Path) -> int:
    options = _parser().parse_args(argv)
    try:
        work = (project_root(Path(cwd)) or Path(cwd)).resolve()
        feature = relative_dir(options.feature, work)
        if not feature or not (work / feature).is_dir():
            raise ValueError('feature must be an existing directory inside this checkout')
        options.feature = feature
        if not options.runtime and env.get('CODEX_THREAD_ID'):
            options.runtime = 'codex'
        if not options.session_id and options.runtime == 'codex':
            options.session_id = env.get('CODEX_THREAD_ID')
        if not options.runtime or not options.session_id or not options.session_id.strip():
            raise ValueError('missing verified runtime/session identity; supply --runtime and --session-id '
                             '(Codex may use CODEX_THREAD_ID)')
        cfg = load_config(work, env)
        if not cfg.enabled or options.runtime not in cfg.runtime_names:
            raise ValueError('selected runtime is disabled in Usage Bridge configuration')
        runtime = runtime_dir(work, work)
        if options._select:
            stdout.write(json.dumps(_select(options, env, work, runtime, cfg)) + '\n')
            return 0
        # Supervision bounds even adapters whose parser cannot interrupt a large file.
        entry = Path(__file__).resolve().parents[1] / 'checkpoint.py'
        args = [sys.executable, str(entry), '--_select', '--runtime', options.runtime,
                '--session-id', options.session_id, '--feature', feature, '--phase', options.phase]
        if options.invocation_ts:
            args += ['--invocation-ts', options.invocation_ts]
        if options.latest:
            args += ['--latest']
        selected = subprocess.run(args, cwd=work, env=dict(env), capture_output=True, text=True,
                                  encoding='utf-8', errors='replace',
                                  timeout=min(cfg.deadline_seconds, MAX_DEADLINE_SECONDS))
        if selected.returncode:
            raise ValueError(selected.stdout.strip() or 'source selection failed; run usage-bridge.check')
        evidence = json.loads(selected.stdout)
        binding = FeatureBinding(**evidence['binding'])
        stdout.write(f'Usage Bridge: {binding.runtime} session {binding.session_id}, phase {binding.phase}, '
                     f'invocation {binding.invocation_ts}: {evidence["previous"]} -> {binding.feature_dir}\n')
        if not options.apply:
            stdout.write('Usage Bridge: preview only; add --apply to save this binding and refresh reports.\n')
            return 0
        lock = _Lock(runtime / 'lock')
        if not lock.acquire(5.0):
            raise ValueError('another capture holds the lock; retry checkpoint')
        try:
            # Containment is checked again under the lock in case the destination changed.
            safe = relative_dir(binding.feature_dir, work)
            if safe != binding.feature_dir or not (work / safe).is_dir():
                raise ValueError('feature destination changed; retry with an existing contained directory')
            changed = save_binding(runtime, binding)
        finally:
            lock.release()
        stdout.write('Usage Bridge: binding saved.\n' if changed else 'Usage Bridge: binding already saved.\n')
        result = run_capture('', work, env)
        if result.status not in ('ok', 'partial'):
            raise ValueError(f'binding saved but refresh {result.status}; '
                             f'retry capture: {result.error or "check logs"}')
        stdout.write(result.summary + '\n')
        return 0
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        stdout.write(f'Usage Bridge: checkpoint warning: {exc}\n')
        return 0 if options.workflow and not options._select else 1


def checkpoint_entry():
    return checkpoint_main(sys.argv[1:], sys.stdout, dict(os.environ), Path.cwd())
