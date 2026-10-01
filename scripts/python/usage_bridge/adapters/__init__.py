"""Lazy runtime adapter registry, independent of the vendor registry."""
from .base import RuntimeAdapter


def get_adapter(runtime: str) -> RuntimeAdapter:
    if runtime == "claude":
        from .claude import ClaudeAdapter

        return ClaudeAdapter()
    if runtime == "codex":
        from .codex import CodexAdapter

        return CodexAdapter()
    raise ValueError(f"unsupported runtime: {runtime}")
