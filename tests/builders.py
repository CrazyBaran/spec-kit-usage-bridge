"""Synthetic Claude Code transcripts and repositories for tests.

Entry shapes mirror real transcripts (spec findings F1-F8): every entry carries sessionId, cwd,
gitBranch and timestamp; assistant usage has the cache_creation 5m/1h split; subagents live in
<session>/subagents/**/agent-*.jsonl with a sibling .meta.json.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path


def projects_root() -> Path:
    return Path(os.environ["TOKEN_USAGE_PROJECTS_DIR"])


def slug(path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_repo(tmp: Path, name: str = "repo", features: Sequence[str] = ("001-login",), branch: str = "main") -> Path:
    """A git repository with `.specify/` and one `specs/<feature>/spec.md` per feature, committed once."""
    repo = tmp / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True, capture_output=True)
    (repo / ".specify").mkdir()
    for feature in features:
        d = repo / "specs" / feature
        d.mkdir(parents=True)
        (d / "spec.md").write_text(f"# {feature}\n", encoding="utf-8")
    (repo / "README.md").write_text("test repository\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


class SessionBuilder:
    """Builds one Claude Code session transcript (and its subagents) entry by entry."""

    def __init__(
        self,
        session_id: str,
        cwd: Path,
        branch: str | None = "main",
        start: str = "2026-09-29T09:00:00.000Z",
        sidechain: bool = False,
    ) -> None:
        self.session_id = session_id
        self.cwd = Path(cwd)
        self.branch = branch
        self.sidechain = sidechain
        self.entries: list[dict] = []
        self._lines: list[str] = []
        self._clock = _parse(start)
        self._pending_raw_ts: str | None = None
        self._counter = 0
        self._parent_uuid: str | None = None
        self._children: list[tuple[str, SessionBuilder, dict]] = []

    # -- clock -------------------------------------------------------------------------------
    def tick(self, seconds: int = 30) -> str:
        self._clock += timedelta(seconds=seconds)
        return _fmt(self._clock)

    def at(self, iso: str) -> None:
        """The next entry gets exactly this timestamp string (the clock continues from it)."""
        self._clock = _parse(iso)
        self._pending_raw_ts = iso

    def _stamp(self) -> str:
        if self._pending_raw_ts is not None:
            raw, self._pending_raw_ts = self._pending_raw_ts, None
            return raw
        self._clock += timedelta(seconds=1)
        return _fmt(self._clock)

    def set_branch(self, name: str | None) -> None:
        self.branch = name

    # -- entries -----------------------------------------------------------------------------
    def _base(self, entry_type: str) -> dict:
        self._counter += 1
        uid = f"{self.session_id}-{'s' if self.sidechain else 'm'}{id(self) % 10_000}-{self._counter}"
        entry = {
            "parentUuid": self._parent_uuid,
            "isSidechain": self.sidechain,
            "userType": "external",
            "cwd": str(self.cwd),
            "sessionId": self.session_id,
            "version": "2.1.284",
            "entrypoint": "cli",
            "type": entry_type,
            "uuid": uid,
            "timestamp": self._stamp(),
        }
        if self.branch is not None:
            entry["gitBranch"] = self.branch
        self._parent_uuid = uid
        return entry

    def _add(self, entry: dict) -> None:
        self.entries.append(entry)
        self._lines.append(json.dumps(entry, ensure_ascii=False))

    def command(self, name: str, args: str = "") -> None:
        entry = self._base("user")
        label = name.lstrip("/$")
        entry["message"] = {
            "role": "user",
            "content": f"<command-message>{label} is running…</command-message>\n"
            f"<command-name>{name}</command-name>\n<command-args>{args}</command-args>",
        }
        self._add(entry)

    def prompt(self, text: str) -> None:
        entry = self._base("user")
        entry["message"] = {"role": "user", "content": text}
        self._add(entry)

    def reply(
        self,
        request_id: str | None,
        *,
        model: str = "claude-opus-5-5",
        input: int = 0,
        output: int = 0,
        cache_read: int = 0,
        cache_5m: int = 0,
        cache_1h: int = 0,
        skill: str | None = None,
        stop_reason: str = "end_turn",
        chunks: int = 1,
    ) -> None:
        """One API response; `chunks > 1` streams it as several entries sharing the requestId."""
        for i in range(chunks):
            entry = self._base("assistant")
            if request_id is not None:
                entry["requestId"] = request_id
            content: list[dict] = [{"type": "text", "text": "ok"}]
            if skill and i == 0:
                tool_use = {"type": "tool_use", "id": f"toolu_{request_id}", "name": "Skill", "input": {"skill": skill}}
                content.append(tool_use)
            entry["message"] = {
                "id": f"msg_{request_id if request_id is not None else self._counter}",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": content,
                "stop_reason": stop_reason if i == chunks - 1 else None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": input,
                    "output_tokens": output * (i + 1) // chunks,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_5m + cache_1h,
                    "cache_creation": {"ephemeral_5m_input_tokens": cache_5m, "ephemeral_1h_input_tokens": cache_1h},
                    "service_tier": "standard",
                    "speed": "standard",
                },
            }
            self._add(entry)

    def compact(self, trigger: str = "auto", pre: int = 967128, post: int = 24252) -> None:
        boundary = self._base("system")
        boundary.update({
            "subtype": "compact_boundary",
            "content": "Conversation compacted",
            "level": "info",
            "compactMetadata": {"trigger": trigger, "preTokens": pre, "postTokens": post},
        })
        self._add(boundary)
        summary = self._base("user")
        summary["isCompactSummary"] = True
        text = "This session is being continued from a previous conversation."
        summary["message"] = {"role": "user", "content": text}
        self._add(summary)

    def raw(self, line: str) -> None:
        """Append a raw (possibly malformed) line."""
        self._lines.append(line)

    def subagent(self, rel: str, *, agent_type: str = "general-purpose", spawn_depth: int = 1) -> SessionBuilder:
        """A subagent transcript at <session>/subagents/<rel>.jsonl; its clock starts at ours."""
        child = SessionBuilder(self.session_id, self.cwd, self.branch, start=_fmt(self._clock), sidechain=True)
        meta = {
            "agentType": agent_type,
            "description": f"{agent_type} task",
            "model": "claude-sonnet-5-5",
            "parentAgentId": None,
            "spawnDepth": spawn_depth,
            "toolUseId": f"toolu_{rel}",
        }
        self._children.append((rel, child, meta))
        return child

    def write(self, root: Path | None = None) -> Path:
        """Write the transcript (and subagents) under <root>/<slug(cwd)>/; return the main path."""
        project_dir = (root or projects_root()) / slug(self.cwd)
        project_dir.mkdir(parents=True, exist_ok=True)
        main = project_dir / f"{self.session_id}.jsonl"
        _write_lines(main, self._lines)
        for rel, child, meta in self._children:
            path = project_dir / self.session_id / "subagents" / f"{rel}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_lines(path, child._lines)
            path.with_suffix(".meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return main


def _write_lines(path: Path, lines: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for line in lines:
            fh.write(line + "\n")
