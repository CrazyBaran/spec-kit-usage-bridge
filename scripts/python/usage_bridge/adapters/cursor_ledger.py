"""Vendor-compatible Cursor records with opt-in prompt previews."""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import current_branch, is_inside
from .base import ParseContext
from .codex import invocation

HOOKS = {"beforeSubmitPrompt", "stop", "afterAgentResponse", "subagentStart", "subagentStop"}


def append_event(payload: Mapping[str, Any], context: ParseContext) -> None:
    hook, conversation = payload.get("hook_event_name"), payload.get("conversation_id")
    if hook not in HOOKS or not isinstance(conversation, str) or not conversation:
        return
    record = {"hook": hook, "conversation_id": conversation,
              "generation_id": str(payload.get("generation_id") or "unknown"),
              "ts": payload.get("timestamp") or datetime.now(timezone.utc).isoformat()}
    evidence = [payload.get("cwd"), *(payload.get("workspace_roots") or [])]
    owners = [checkout for checkout in context.checkouts
              if any(isinstance(root, str) and is_inside(root, [checkout]) for root in evidence)]
    owner = max(owners, key=lambda checkout: len(str(checkout)), default=None)
    branch = current_branch(owner) if owner else None
    if branch:
        record["branch"] = branch
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        record["workspace_roots"] = [root for root in roots if isinstance(root, str)]
    text = str(payload.get("prompt") or "")
    name = invocation(text)
    if hook == "beforeSubmitPrompt":
        if name:
            record.update(prompt=name, label=name)
        elif context.keep_previews:
            record["prompt"] = text.strip()[:120]
    for key in ("model", "subagent_id", "subagent_type", "subagent_model"):
        value = payload.get(key)
        if isinstance(value, str):
            record[key] = value
    tokens = {key: payload[key] for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
              if isinstance(payload.get(key), int) and not isinstance(payload[key], bool) and payload[key] >= 0}
    if tokens:
        record["tokens"] = tokens
    directory = context.runtime_dir / "cursor-ledgers" / "cursor"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(conversation.encode()).hexdigest() + ".jsonl")
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, separators=(",", ":")) + "\n")


def remove_previews(ledger_root: Path) -> None:
    for path in ledger_root.rglob("*.jsonl"):
        clean = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            for key in ("prompt", "label", "task"):
                value = record.pop(key, None)
                if key in ("prompt", "label") and isinstance(value, str) and invocation(value):
                    record[key] = invocation(value)
            clean.append(json.dumps(record, separators=(",", ":")))
        temp = path.with_suffix(".tmp")
        temp.write_text("\n".join(clean) + "\n", encoding="utf-8")
        os.replace(temp, path)
