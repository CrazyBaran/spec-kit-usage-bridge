"""Sanitized public Codex event shapes; no personal history."""
import json
import time

from usage_bridge.adapters.base import ParseContext


def context(repo, home, clock=time.monotonic):
    return ParseContext((repo,), {"CODEX_HOME": str(home)}, home / "runtime", False, clock() + 15, clock)


def write_rollout(home, repo, session="s", events=(), archived=False, parent=None):
    directory = home / ("archived_sessions" if archived else "sessions/2026/10/01")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-{session}.jsonl"
    meta = {"type": "session_meta", "timestamp": "2026-10-01T08:00:00Z",
            "payload": {"id": session, "cwd": str(repo), "git": {"branch": "001-login"}}}
    if parent:
        meta["payload"]["parent_thread_id"] = parent
    entries = [meta, *events]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


def turn(model="gpt-5.2-codex"):
    return {"type": "turn_context", "timestamp": "2026-10-01T08:00:01Z",
            "payload": {"turn_id": "t1", "model": model}}


def prompt(text="/speckit.plan"):
    return {"type": "event_msg", "timestamp": "2026-10-01T08:00:02Z",
            "payload": {"type": "user_message", "message": text}}


def tokens(inp, cached, out, reasoning=0, stamp="2026-10-01T08:00:03Z", **extra):
    usage = {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out,
             "reasoning_output_tokens": reasoning, "total_tokens": inp + out, **extra}
    return {"type": "event_msg", "timestamp": stamp,
            "payload": {"type": "token_count", "info": {"total_token_usage": usage,
                                                             "last_token_usage": usage}}}
