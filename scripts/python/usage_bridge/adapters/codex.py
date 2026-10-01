"""Project-owned local Codex rollout discovery and parsing."""
from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from ..config import Config
from ..paths import is_inside
from .base import ParseContext, SourceDescriptor


class CodexAdapter:
    @staticmethod
    def _metadata(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for index, line in enumerate(stream):
                if index >= 50:
                    break
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and entry.get("type") == "session_meta":
                    payload = entry.get("payload")
                    if isinstance(payload, dict):
                        return payload
        return {}

    def discover(self, context: ParseContext, config: Config) -> Iterator[SourceDescriptor]:
        home = Path(context.env.get("CODEX_HOME") or str(Path.home() / ".codex"))
        roots = [home / "sessions", home / "archived_sessions", *map(Path, config.codex_extra_dirs)]
        index_path = context.runtime_dir / "codex-index.json"
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(index, dict):
                index = {}
        except (OSError, ValueError):
            index = {}
        found: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for root in roots:
            if not root.is_dir():
                continue
            for directory, _, filenames in os.walk(root):
                if context.expired():
                    break
                for name in filenames:
                    if context.expired():
                        break
                    if not name.endswith(".jsonl"):
                        continue
                    path = Path(directory) / name
                    marker = os.path.normcase(str(path.absolute()))
                    if marker in seen:
                        continue
                    seen.add(marker)
                    try:
                        stat = path.stat()
                        stamp = [str(path), stat.st_size, stat.st_mtime_ns]
                        saved = index.get(marker, {})
                        meta = saved.get("meta") if saved.get("stamp") == stamp else self._metadata(path)
                    except OSError:
                        continue
                    index[marker] = {"stamp": stamp, "meta": meta}
                    if not isinstance(meta, dict):
                        continue
                    cwd = meta.get("cwd")
                    if not isinstance(cwd, str) or not is_inside(cwd, context.checkouts):
                        continue
                    session = meta.get("id") or meta.get("session_id")
                    if not isinstance(session, str) or not session:
                        continue
                    record = found.setdefault(session, {"paths": [], "meta": meta, "stamps": []})
                    record["paths"].append(path)
                    record["stamps"].append(tuple(stamp))
        try:
            context.runtime_dir.mkdir(parents=True, exist_ok=True)
            temp = index_path.with_suffix(".tmp")
            temp.write_text(json.dumps(index), encoding="utf-8")
            os.replace(temp, index_path)
        except OSError:
            pass
        for session, native in sorted(found.items()):
            yield SourceDescriptor("codex", session, "rollout", native, tuple(native["stamps"]))

    def parse(self, source: SourceDescriptor, context: ParseContext):
        return parse_rollout(source, context)

    def record(self, payload: Mapping[str, Any], context: ParseContext) -> None:
        pass  # Codex owns its local rollout.


def parse_rollout(source: SourceDescriptor, context: ParseContext):
    from ..digest import SessionDigest

    return SessionDigest(source.session_id, str(source.native["paths"][0]), None, None, None, runtime="codex")
