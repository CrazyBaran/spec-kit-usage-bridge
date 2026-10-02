"""Runtime-neutral source and capability contracts."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..config import Config
    from ..digest import SessionDigest


@dataclass(frozen=True)
class Capabilities:
    request_counts: bool = False
    subagents: bool = False
    compaction: bool = False
    splitting: bool = False


@dataclass(frozen=True)
class SourceDescriptor:
    runtime: str
    session_id: str
    source_kind: str
    native: object
    stamps: tuple

    @property
    def identity(self) -> tuple[str, str]:
        return self.runtime, self.session_id


@dataclass
class ParseContext:
    checkouts: tuple[Path, ...]
    env: Mapping[str, str]
    runtime_dir: Path
    keep_previews: bool
    deadline: float
    clock: Callable[[], float]

    def expired(self) -> bool:
        return self.clock() >= self.deadline


class RuntimeAdapter(Protocol):
    def discover(self, context: ParseContext, config: Config) -> Iterator[SourceDescriptor]: ...
    def parse(self, source: SourceDescriptor, context: ParseContext) -> SessionDigest: ...
    def record(self, payload: Mapping[str, Any], context: ParseContext) -> None: ...
