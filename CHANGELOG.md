# Changelog

## [0.2.0] - 2026-10-01

Adds local Codex rollout support and best-available Cursor usage/activity through
runtime adapters. Reports distinguish exact, partial and activity-only coverage,
retain measured subtotals, and leave unavailable counts and complete costs null.
Codex API-equivalent pricing is bridge-owned; the vendored token-usage files remain
unchanged at `0.6.1+unreleased-0.7`, commit
`f4078277e79c007993e0cb595bb95f924a2a8777`.

Adds private Cursor event ledgers, runtime configuration, qualified identities,
schema v2 output with v1 read compatibility, historical snapshot retention, and
runtime-specific checks. Spec Kit dispatch is tested for all three integrations;
authenticated Codex/Cursor automatic delivery remains manual/unverified.

Upgrade all contributors before committing schema v2 reports. Downgrading writers
to v0.1 is unsupported. See the release and native smoke guides.

## [0.1.0] - 2026-09-30

Initial implementation of Usage Bridge for Spec Kit. Adds automatic Claude Code Stop-hook capture, per-feature and per-phase
reports, attribution across sessions and authors, and integration checks.

Vendored token-usage version: `0.6.1+unreleased-0.7`, commit
`f4078277e79c007993e0cb595bb95f924a2a8777`.
