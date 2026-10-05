# Ponytail Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply verified, behavior-preserving complexity reductions to the existing release-automation branch.

**Architecture:** Reuse existing JSON and attestation helpers. Remove unused code and aggregation superseded by coverage-aware summaries.

**Tech Stack:** Python standard library, existing pytest/Ruff tooling, actionlint, and Zizmor.

**Spec:** User-requested repository audit; preserve the requirements in ../specs/2026-10-02-release-automation-design.md and ../specs/2026-10-01-usage-bridge-v0.2-design.md.

## Global Constraints

- Preserve Python 3.9+ and Spec Kit 1.0.12+ support, output schemas and ordering, provenance, archive limits, and mandatory runtime checks.
- Do not modify the pinned vendor, add dependencies, remove regression coverage, change live settings, or publish releases.
- Apply fixes on `feat/release-automation`; leave changes available for review before any further commit or push.

## Review Focus

- Partial archive-limit overrides must retain defaults: existing malicious-archive tests.
- Failed or absent installation jobs must still block: existing orchestration and publication tests.
- Missing maintainer attestations must still produce pending CLI output: existing CLI and submission tests.
- Nested subagent requests must serialize identically: existing digest/cache and oracle tests.
- Unknown or partial runtime measurements and deterministic report ordering must remain intact: existing render, coverage, and pipeline tests.

### Task 1: Simplify verified audit findings

**Files:** `tools/release_cli.py`, `tools/release/{artifacts,orchestration,publication,submission}.py`, `tools/{repository_policy,update-vendor}.py`, and `scripts/python/usage_bridge/{digest,pipeline,render}.py`.

**Interfaces:** Reuse `write_json(path, payload)`; expose the existing attestation validator as `missing_attestations(evidence)`. Keep all supported CLI commands and report schemas unchanged. Remove the unused `require_install` option; all current callers require installation success.

- [x] Audit callers across source, tests, workflow configuration, and dynamic/string references; reject speculative cuts.
- [x] Run existing behavioral tests before refactoring; no new behavior or structural change-detector tests are required.
- [x] Apply the verified deletions, helper reuse, recursive `asdict`, and duplicate-aggregation removal.
- [x] Run affected tests, then full integration validation with `.venv/Scripts/python.exe`, an external temporary directory, and process-scoped Git safe-directory configuration.
- [x] Run Ruff, actionlint, configured high-severity Zizmor, and `git diff --check`; obtain an independent read-only review.
- [x] Record results and report the measured production-code reduction.

## Execution Record

- Both audit passes were read-only. Repository-wide symbol searches included tests and dynamic/string references.
- Behavioral baselines passed before edits: 92 maintenance tests and 210 release/runtime tests.
- All 302 affected tests passed after refactoring. Ruff and diff checks passed.
- Production diff: 19 lines added, 84 removed; net reduction of 65 lines across ten files, zero dependency changes.
- Full integration validation passed: 802 passed, three expected skips, and the existing duplicate-ZIP-member warning. Skips cover two authenticated native-agent smoke tests and POSIX ownership behavior on Windows.
- Ruff, actionlint, configured high-severity Zizmor, and diff checks passed. Independent review found no actionable issues; differential checks preserved exact report bytes, nested subagent serialization, and all tested attestation combinations.
- No commit, push, live settings change, or publication performed for these audit fixes. Live GitHub behavior remains unverified.
