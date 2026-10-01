"""Preserve the reconciled Claude transcript implementation."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from ..config import Config
from ..digest import SessionDigest, digest_session
from ..discovery import discover, projects_roots
from .base import ParseContext, SourceDescriptor


class ClaudeAdapter:
    def discover(self, context: ParseContext, config: Config) -> Iterator[SourceDescriptor]:
        roots = projects_roots({}, context.env)
        for files in discover(context.checkouts, roots, [Path(d).expanduser() for d in config.extra_dirs]):
            if context.expired():
                return
            yield SourceDescriptor("claude", files.session_id, "jsonl", files, files.stamps)

    def parse(self, source: SourceDescriptor, context: ParseContext) -> SessionDigest:
        return digest_session(source.native, context.keep_previews)

    def record(self, payload: Mapping[str, Any], context: ParseContext) -> None:
        pass  # Claude writes its own transcript.
