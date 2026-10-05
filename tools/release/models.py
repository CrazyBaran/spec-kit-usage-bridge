"""Typed release evidence. Development tooling only."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    name: str
    source_sha: str
    run_id: int
    attempt: int
    app_id: int
    status: str
    conclusion: str | None
    url: str


@dataclass(frozen=True)
class OverrideRequest:
    requested: bool
    reason: str
    waived_checks: tuple[str, ...]
    run_id: int
    attempt: int
    source_sha: str
    approved: bool
    approver: str | None


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    blockers: tuple[str, ...]
    waived: tuple[str, ...]
