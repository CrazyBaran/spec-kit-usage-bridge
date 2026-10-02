"""Explicit feature evidence for one observed invocation; private runtime state only."""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import same_path
from .phases import Run
from .timefmt import norm_ts
from .timeline import relative_dir

FILE = 'feature-bindings.json'


@dataclass(frozen=True)
class FeatureBinding:
    runtime: str
    session_id: str
    work_root: str
    feature_dir: str
    phase: str
    invocation_ts: str

    def __post_init__(self):
        if not all(isinstance(v, str) and v.strip() for v in asdict(self).values()):
            raise ValueError('invalid binding fields')
        if self.runtime not in ('claude', 'codex', 'cursor') or self.phase == 'constitution':
            raise ValueError('invalid binding runtime or phase')
        work = str(Path(self.work_root).resolve())
        feature = relative_dir(self.feature_dir, Path(work))
        stamp = norm_ts(self.invocation_ts)
        if not feature or not stamp:
            raise ValueError('invalid binding feature or invocation timestamp')
        object.__setattr__(self, 'work_root', work)
        object.__setattr__(self, 'feature_dir', feature)
        object.__setattr__(self, 'invocation_ts', stamp)

    @property
    def key(self):
        return (self.runtime, self.session_id, os.path.normcase(self.work_root), self.phase, self.invocation_ts)


def select_run(runs: Sequence[Run], runtime: str, session_id: str, phase: str,
               invocation_ts: str | None = None, latest: bool = False) -> Run:
    if latest and invocation_ts is not None:
        raise ValueError('choose one invocation selector')
    stamp = norm_ts(invocation_ts) if invocation_ts is not None else None
    if invocation_ts is not None and stamp is None:
        raise ValueError('invalid invocation timestamp')
    matches = [run for run in runs if (run.runtime, run.session_id, run.phase) == (runtime, session_id, phase)]
    if stamp:
        matches = [run for run in matches if run.start_ts == stamp]
    if latest and matches and all(run.start_ts for run in matches):
        newest = max(run.start_ts for run in matches)
        matches = [run for run in matches if run.start_ts == newest]
    if len(matches) != 1 or not matches[0].start_ts:
        raise ValueError('invocation missing or ambiguous; select --invocation-ts (or explicit --latest)')
    if phase == 'constitution':
        raise ValueError('constitution is project-level')
    return matches[0]


def _state(runtime: Path) -> tuple[list[FeatureBinding], set[tuple[str, str]]]:
    path = runtime / FILE
    if not path.exists():
        return [], set()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('bindings'), list):
            raise ValueError('unsupported schema')
        rows = [FeatureBinding(**row) for row in data['bindings']]
        if len({row.key for row in rows}) != len(rows):
            raise ValueError('duplicate keys')
        destinations = {(row.work_root, row.feature_dir) for row in rows}
        history = data.get('destinations', [])
        if not isinstance(history, list):
            raise ValueError('invalid destination history')
        for item in history:
            if not isinstance(item, dict) or set(item) != {'work_root', 'feature_dir'}:
                raise ValueError('invalid destination history')
            if not all(isinstance(value, str) and value.strip() for value in item.values()):
                raise ValueError('invalid destination fields')
            root = str(Path(item['work_root']).resolve())
            feature = relative_dir(item['feature_dir'], Path(root))
            if not feature:
                raise ValueError('invalid destination feature')
            destinations.add((root, feature))
        return rows, destinations
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        raise ValueError(f'invalid feature binding file: {exc}') from exc


def load_bindings(runtime_dir: Path, work_root: Path) -> list[FeatureBinding]:
    rows, _ = _state(Path(runtime_dir))
    return [row for row in rows if same_path(row.work_root, work_root.resolve())]


def binding_feature_dirs(runtime_dir: Path, work_root: Path) -> list[str]:
    """Include prior destinations so rebinding/retrying can clean obsolete local reports."""
    _, destinations = _state(Path(runtime_dir))
    return sorted({feature for root, feature in destinations if same_path(root, work_root.resolve())
                   and (work_root / feature).is_dir()})


def save_binding(runtime_dir: Path, binding: FeatureBinding) -> bool:
    """Caller holds the capture lock. Never replace corrupt state or swallow write errors."""
    runtime = Path(runtime_dir)
    rows, destinations = _state(runtime)
    previous = next((row for row in rows if row.key == binding.key), None)
    if previous == binding:
        return False
    rows = [row for row in rows if row.key != binding.key] + [binding]
    destinations.add((binding.work_root, binding.feature_dir))
    data = {'version': 1, 'bindings': [asdict(row) for row in sorted(rows, key=lambda row: row.key)],
            'destinations': [{'work_root': root, 'feature_dir': feature}
                             for root, feature in sorted(destinations)]}
    runtime.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='bindings-', suffix='.tmp', dir=runtime)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(data, indent=2) + '\n')
        os.replace(name, runtime / FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return True
