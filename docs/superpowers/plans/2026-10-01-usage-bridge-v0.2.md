# Usage Bridge v0.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local Codex and Cursor capture to the existing Spec Kit usage audit, with measured subtotals and explicit unavailable coverage.

**Architecture:** Runtime adapters normalize sources into the existing digest/phase pipeline. A local Codex reader and privacy-aware Cursor ledger writer sit outside the unchanged vendor; runtime-qualified identities and schema v2 support mixed reports and v1 readers. Capability flags prevent unsupported metrics from being presented as measured facts.

**Tech Stack:** Python 3.9+ runtime standard library, pinned token-usage, pytest/ruff development tooling, Spec Kit 1.0.12+.

**Spec:** [Approved v0.2 design](../specs/2026-10-01-usage-bridge-v0.2-design.md). Read it before execution.

## Global Constraints

- Python 3.9+ and Spec Kit 1.0.12+ remain the baseline.
- The extension is distributed as files, not as a Python package.
- Capture retains its 15-second overall deadline, silent hook behavior and zero hook exit status.
- Preserve the pinned token-usage commit and hashes. All vendor calls pass through `tu_compat.py`.
- Do not estimate missing token counts.
- Previews remain opt-in for every adapter, including intermediate bridge-created ledgers.
- Write schema version 2; readers accept versions 1 and 2.
- Release preparation is in scope; publishing or an upstream PR requires a separate request.
- All paths below are repository-relative to `D:/spec-kit-usage-bridge`. Keep edits on the reviewed development branch; use the worktree skill if execution requires isolation.
- Execute tasks in order. No task may publish automatic-support claims before Task 9 verifies native delivery. No product changes begin before the user reviews this plan and chooses execution.

## Review Focus

1. Windows path case, spaces, file URIs and sibling prefix collisions must not import an unrelated checkout (Tasks 3 and 5).
2. A malformed JSONL tail during a live write must retain valid preceding usage and signal incomplete coverage (Tasks 3 and 4).
3. Disabling previews after an earlier capture must remove bridge-created previews from caches, ledgers and newly rendered reports without editing agent files (Tasks 5 and 8).
4. A shared Cursor database can change unrelated rows while a session stays unchanged; cache invalidation must not duplicate or lose its contribution (Tasks 5 and 8).
5. Failed or timed-out discovery is not evidence of deletion: historical and other-runtime snapshots must survive (Task 8).

## File and interface map

Create focused modules under `scripts/python/usage_bridge/`:

| File | Responsibility |
|---|---|
| `adapters/base.py` | Source descriptor, parse context, adapter protocol and capabilities |
| `adapters/__init__.py` | Lazy adapter registry |
| `adapters/claude.py` | Existing discovery/digest delegation |
| `adapters/codex.py` | Rollout discovery, indexing and event parsing |
| `adapters/codex_usage.py` | Counter reconciliation and inherited-history filtering |
| `adapters/cursor.py` | Vendor discovery/segment translation and source precedence |
| `adapters/cursor_ledger.py` | Privacy-aware append and preview removal |
| `measurement.py` | Quality, known subtotals and missing coverage |
| `schema.py` | v1/v2 source normalization and validation |
| `pricing.py`, `data/openai-pricing.json` | Runtime-aware pricing and provenance |

Modify existing `runtime.py`, `config.py`, `digest.py`, `phases.py`, `attribution.py`,
`timeline.py`, `metrics.py`, `render.py`, `pipeline.py`, `cli.py`, `checks.py` and
`tu_compat.py` only where their responsibilities require it. Keep existing public
entrypoints and Claude oracle tests working. Add sanitized fixtures under
`tests/fixtures/{codex,cursor}/` with provenance in each directory's `README.md`.

Shared types are defined by Task 1 and reused without renaming:

- `SourceDescriptor(runtime: str, session_id: str, source_kind: str, native: object, stamps: tuple)`; `identity -> tuple[str, str]`. `native` is runtime-local and never serialized into committed reports.
- `ParseContext(checkouts: tuple[Path, ...], env: Mapping[str, str], runtime_dir: Path, keep_previews: bool, deadline: float, clock: Callable[[], float])`; `expired() -> bool`.
- `Capabilities(request_counts: bool = False, subagents: bool = False, compaction: bool = False, splitting: bool = False)`.
- `RuntimeAdapter.discover(context: ParseContext, config: Config) -> Iterator[SourceDescriptor]`, `.parse(source: SourceDescriptor, context: ParseContext) -> SessionDigest`, `.record(payload: Mapping[str, Any], context: ParseContext) -> None`.
- Preserve `SessionDigest`, `Request` and `Event` names. Add defaulted metadata to their ends so existing callers survive. A `Request` is the legacy internal name for a normalized usage observation: add `kind` (`request`, `counter_delta`, `segment`), measurement/reasons and nullable token buckets. `flat()` returns nullable buckets; callers must use the new measurement helpers before pricing or arithmetic.
- `SessionDigest` adds runtime (`claude` default), measurement, reasons, capabilities, attribution confidence and optional parent identity. Events preserve stable source ordinals and native turn/generation identity when available.
- `measurement.summarize(observations: Sequence[Request]) -> dict[str, Any]`: `usage` has null for any incompletely measured bucket, `measured_usage` sums known buckets, `measurement` and `reasons` disclose coverage. Measured zero stays zero.
- `pricing.estimate(runtime: str, model: str, usage: Mapping[str, int | None], rates: Rates, measurement: str = "exact") -> dict[str, Any]` returns `cost_usd`, `known_cost_usd`, `reasons`. Partial/activity-only coverage keeps complete cost null even if known buckets can be priced.

## Task 1: Shared measurement contract and Claude adapter

**Files:** Create `adapters/base.py`, `adapters/__init__.py`, `adapters/claude.py`, `measurement.py`; modify `digest.py`; test `tests/test_adapters.py`, `tests/test_measurement.py`, existing oracle/digest tests.

**Interfaces:** Produce the shared types above and `get_adapter(runtime: str) -> RuntimeAdapter`. Claude delegates to `projects_roots`, `discover` and `digest_session`; no vendor behavior change.

- [ ] Write tests for adapter identity and serialization round trips. Pin nullable arithmetic with `test_mixed_measurement_preserves_known_subtotal`:
  ```python
  result = summarize([measured(input=100, output=20), activity_only()])
  assert result["usage"]["input"] is None
  assert result["measured_usage"]["input"] == 100
  assert result["measurement"] == "activity_only"
  assert summarize([measured(input=0, output=0)])["usage"]["input"] == 0
  ```
  Helpers construct the defined `Request` type. Assert `("claude", "same") != ("codex", "same")` and legacy digest defaults remain Claude.
- [ ] Run `python -m pytest tests/test_adapters.py tests/test_measurement.py -q`; require failures for missing interfaces before implementation.
- [ ] Implement the shared dataclasses, registry and helpers. Define coverage order `exact < partial < activity_only`; sum known values independently of completeness. Adapt digest serialization while preserving positional constructors.
- [ ] Run those tests plus `python -m pytest tests/test_digest.py tests/test_oracle.py tests/test_tu_compat.py -q`; require all pass and identical Claude totals.
- [ ] Commit only this deliverable with `refactor: introduce runtime adapter and measurement contracts`.

## Task 2: Runtime configuration and unambiguous payload detection

**Files:** Modify `config.py`, `runtime.py`, `config-template.yml`; test `tests/test_config.py`, `tests/test_runtime.py`.

**Interfaces:** Extend `Config` with `runtime_names: list[str]` defaulting to all three, `codex_extra_dirs: list[str]`, `cursor_extra_dirs: list[str]`, `cursor_data_dir: str`. Extend `detect(raw: str, integration_hint: str | None = None) -> Detected` without breaking its existing one-argument calls.

- [ ] Add tests for base/local/environment precedence, empty list, unknown runtime warnings and unchanged Claude `extra_dirs`. Pin scalar/list environment names: `SPECKIT_USAGE_BRIDGE_RUNTIMES_ENABLED`, `SPECKIT_USAGE_BRIDGE_RUNTIMES_CODEX_EXTRA_DIRS`, `SPECKIT_USAGE_BRIDGE_RUNTIMES_CURSOR_EXTRA_DIRS`, `SPECKIT_USAGE_BRIDGE_RUNTIMES_CURSOR_DATA_DIR`, using the existing list encoding.
- [ ] Add detection tests for native discriminators, empty manual input, malformed input and overlapping `session_id`/`transcript_path`. Assert an ambiguous payload is `unknown` until a verified format or integration hint resolves it.
- [ ] Run `python -m pytest tests/test_config.py tests/test_runtime.py -q`; require the new tests to fail before implementation.
- [ ] Implement settings and detection. Recognize only verified payload shapes; do not guess Codex from a UUID. Keep empty stdin manual, other unrecognized data a silent no-op. Expose payload hints through the existing dispatcher envelope when available; format verification belongs to adapters.
- [ ] Rerun that command; require pass, then commit `feat: configure supported runtimes and classify native events`.

## Task 3: Project-owned Codex discovery and indexed reads

**Files:** Create `adapters/codex.py`, `tests/fixtures/codex/README.md`, sanitized rollout fixtures; test `tests/test_codex_discovery.py`.

**Interfaces:** Implement `CodexAdapter.discover`; produce descriptors for session/archived rollouts and configured extra roots. `CODEX_HOME` defaults to `Path.home() / ".codex"`. Persist the metadata index in `<runtime_dir>/codex-index.json`.

- [ ] Write `test_discovers_only_owned_sessions`, `test_archive_copy_is_one_identity`, `test_windows_sibling_prefix_is_rejected`, `test_live_tail_retains_valid_metadata`, `test_deadline_stops_discovery` and `test_index_avoids_reparsing_unchanged_metadata`. Assert unrelated/missing-ownership sessions are excluded and a worktree session is included.
- [ ] Run `python -m pytest tests/test_codex_discovery.py -q`; require failure before implementation.
- [ ] Implement bounded metadata reads, normalized checkout containment and source fingerprint indexing. Keep same-session candidate copies available for accounting reconciliation; discovery must not choose the largest file as proof of an authoritative history. Malformed final lines produce partial-source reasons; unknown ownership never falls back to filename/branch guessing.
- [ ] Rerun discovery tests, require pass, then commit `feat: discover project-owned Codex rollout history`.

## Task 4: Codex accounting, phases and inherited history

**Files:** Create `adapters/codex_usage.py`; extend `adapters/codex.py`, fixtures; test `tests/test_codex_accounting.py`, `tests/test_codex_events.py`.

**Interfaces:** `parse_rollout(source: SourceDescriptor, context: ParseContext) -> SessionDigest`; `reconcile_snapshots(entries: Sequence[Mapping[str, Any]]) -> tuple[list[Request], list[str]]`; `exclude_inherited_prefix(child: SessionDigest, parent: SessionDigest) -> SessionDigest` in `codex_usage.py`.

- [ ] Write fixture tests pinning two inclusive-input snapshots `(100, cached=40, output=20)` then `(180, cached=70, output=35)`: normalized measured totals are input `110`, cache read `70`, output `35`. Repeating the second snapshot changes nothing. Reasoning `10` within output `35` does not yield output `45`.
- [ ] Add tests for first-snapshot phase uncertainty, model switches, null usage, unsupported cache-write duration, counter decrease, synthetic context total, malformed live tail, resumed history and inherited fork prefix. Assert uncertain increments go to an unassigned phase; unknown model stays unpriced later. Child prefix evidence is required before exclusion.
- [ ] Run `python -m pytest tests/test_codex_accounting.py tests/test_codex_events.py -q`; require failures before implementation.
- [ ] Implement cumulative reconciliation with stable epoch/ordinal observation IDs. Apply the spec's conservative reset policy. Extract commands/skills only from user-event evidence; retain source identity for child/fork reconciliation. Validate cached/reasoning subset semantics against fixture provenance.
- [ ] Rerun tests; require no duplicate cumulative spend and partial reasons for unsupported history. Commit `feat: normalize Codex usage and inherited session history`.

## Task 5: Cursor parsing and privacy-aware ledgers

**Files:** Create `adapters/cursor.py`, `adapters/cursor_ledger.py`, Cursor fixtures/provenance; modify `tu_compat.py`; test `tests/test_cursor_adapter.py`, `tests/test_cursor_ledger.py`.

**Interfaces:** Compatibility wrappers `cursor_sessions(project: Path, ledger_root: Path, data_root: Path | None) -> list[object]` and `cursor_parse(source: object) -> dict[str, Any]`. `append_event(payload: Mapping[str, Any], context: ParseContext) -> None`, `remove_previews(ledger_root: Path) -> None` in `cursor_ledger.py`. Adapter implements the shared contract.

- [ ] Write tests proving one contribution per conversation with precedence ledger > configured export > SQLite; duplicate completion/generation delivery adds no usage. Assert upstream quality is preserved and parsed segments have `kind == "segment"`, with unavailable request counts.
- [ ] Write privacy tests: ordinary prompt/task strings are absent by default, recognized Spec Kit invocation survives, opt-in previews cap at `120`, disabling previews cleans bridge ledgers. Assert vendor scoped environment is restored after a raised exception.
- [ ] Add ownership tests for file URIs/spaces, unrelated workspace rows and prefix collisions, plus SQLite busy/unreadable and unrelated-row update cases. Assert read-only access and stable totals after reparsing a changed shared database.
- [ ] Run `python -m pytest tests/test_cursor_adapter.py tests/test_cursor_ledger.py -q`; require failure before implementation.
- [ ] Implement wrappers without editing vendor/private registry. Store vendor-compatible bridge ledgers at `<runtime_dir>/cursor-ledgers/`; writes require the pipeline lock. Translate vendor segment labels to phase evidence only if an actual command/skill invocation is established. Apply query timeout/interruption where available; retain diagnostics otherwise.
- [ ] Rerun tests and `python -m pytest tests/test_tu_compat.py -q`; require pass and unchanged vendor hashes. Commit `feat: capture Cursor activity with private bridge ledgers`.

## Task 6: Runtime-qualified phases, attribution and safe metrics

**Files:** Modify `phases.py`, `attribution.py`, `timeline.py`, `metrics.py`; test existing corresponding tests plus `tests/test_multiruntime_metrics.py`.

**Interfaces:** Add defaulted runtime/measurement/capability metadata to `Run` and `TimelineEntry`. Keep `build_runs`, `attribute_runs`, `session_entry` signatures; internally key timelines and dedup by runtime-qualified identities. Session entries expose the spec's measurement, confidence and capability fields.

- [ ] Write tests for identical IDs across runtimes, timeline isolation, no later-feature assignment after missed Stop, activity-only phase runs without requests, and uncertain Codex interval assignment. Assert a child with established parent/start evidence contributes once to the parent's active phase.
- [ ] Add tests that an unresolved child keeps separate partial attribution, segment counts are not API calls, and Codex/Cursor re-priming/splitting stay null when unsupported. Preserve existing Claude metrics; prohibit cross-runtime splitting comparisons.
- [ ] Run `python -m pytest tests/test_phases.py tests/test_attribution.py tests/test_timeline.py tests/test_metrics.py tests/test_multiruntime_metrics.py -q`; require new failures before implementation.
- [ ] Generalize shared phases to retain activity without tokens; use `summarize` before arithmetic. Scope observation dedup to runtime and preserve actual request-ID behavior for Claude. Apply capability checks before any metric formula.
- [ ] Rerun tests; require pass, then commit `feat: attribute multi-runtime activity without inventing metrics`.

## Task 7: Schema v2, runtime pricing and mixed reports

**Files:** Create `schema.py`, `pricing.py`, `data/openai-pricing.json`; modify `tu_compat.py`, `metrics.py`, `render.py`; test `tests/test_schema.py`, `tests/test_pricing.py`, existing render tests and new mixed golden outputs.

**Interfaces:** `schema.normalize_source(data: Mapping[str, Any]) -> dict[str, Any]` accepts v1/v2, otherwise raises `ValueError`; produce the pricing interface from the map. Keep `author_file`, `merge_feature`, `merge_all`, `render_feature_md` and `render_all_md` entrypoints.

- [ ] Write tests for v1 default Claude semantics, preserved partial reasons, v2 round trip and rejected future versions. Assert merge identity includes machine/runtime/session and historical alias revisions still resolve correctly.
- [ ] Write mixed report tests with one exact, one partial and one activity-only session. Assert null complete usage/cost, visible measured/known-cost subtotals, measurement counts and runtime rows. Unknown model has no fallback cost; incomplete buckets never become zero in Markdown. A zero exact measurement remains `0`.
- [ ] Run `python -m pytest tests/test_schema.py tests/test_pricing.py tests/test_render_json.py tests/test_render_md.py -q`; require new failures before implementation.
- [ ] Research official OpenAI pricing for models actually covered by sanitized fixtures. Record rates, source URLs, retrieval date, schema and deterministic hash in the bridge table. Leave undocumented model aliases unpriced. Make overrides resolve deterministically by the existing prefix rules; dispatch Claude costs through existing vendor semantics.
- [ ] Implement v1 normalization, schema v2 validation, runtime-specific totals and nullable formatting. Complete cost is null if coverage/rates are incomplete; `known_cost_usd` carries only priced measured usage. Write output metadata identifying bridge and vendor pricing provenance separately.
- [ ] Rerun tests plus `python -m pytest tests/test_metrics.py tests/test_oracle.py -q`; require pass. Inspect new golden Markdown and JSON manually, then commit `feat: render schema v2 mixed-runtime usage and cost coverage`.

## Task 8: Capture orchestration, retention and cache migration

**Files:** Modify `pipeline.py`, `digest.py`, `cli.py`, config/adapter helpers as needed; test `tests/test_pipeline.py`, `tests/test_cli.py`, `tests/test_perf.py`, `tests/test_multiruntime_pipeline.py`.

**Interfaces:** Preserve `run_capture`, `capture_main`, `report_main` signatures. New `load_sources(context: ParseContext, config: Config, active: tuple[str, str] | None) -> tuple[list[SessionDigest], dict[str, Any]]` in `pipeline.py` orchestrates adapters and returns per-runtime scan diagnostics.

- [ ] Write end-to-end synthetic-project tests for all three runtimes, active-session priority, silent native events, one-line manual summaries, locks and idempotent refresh. Assert unrelated runtime/session records survive a scoped refresh and alias changes.
- [ ] Add failures/deadline tests preserving prior snapshots when adapters throw, sources disappear, enabled runtimes are empty or discovery times out. Assert no stale cache loads after adapter/schema/privacy version changes.
- [ ] Add `test_disable_previews_rebuilds_bridge_state_only`: capture with previews, disable them, refresh, then assert no preview text in bridge caches/ledgers/new reports and byte-identical original agent files.
- [ ] Run `python -m pytest tests/test_pipeline.py tests/test_cli.py tests/test_multiruntime_pipeline.py tests/test_perf.py -q`; require new failures before implementation.
- [ ] Wire the shared pipeline to lazy adapters under one lock/deadline; preserve capture's zero-exit contract. Merge newly parsed sessions into prior same-author records rather than replacing the file wholesale. Distinguish successful complete scans from unavailability; no historical deletion based on a failed scan. Bump digest format/cache keys and read legacy timeline entries as Claude.
- [ ] Rerun tests, including many unrelated rollouts and a large Cursor corpus with the existing performance margins. Require deadline compliance and prior-data retention, then commit `feat: orchestrate bounded multi-runtime capture and migration`.

## Task 9: Integration health and real dispatch validation

**Files:** Modify `checks.py`, `extension.yml`, `tests/test_checks.py`, `tests/test_package_files.py`, `tests/integration/test_speckit.py`; add `tests/integration/test_native_events.py` and runtime smoke-test documentation.

**Interfaces:** Preserve check CLI/JSON entrypoints; add runtime-qualified check IDs and explicit `automatic`/`manual` capture mode. Use Spec Kit native event registration for stop and prompt-submit; do not write unmanaged user hooks.

- [ ] Write checks tests for Claude-only, Codex-only, Cursor-only and mixed installs. Assert missing optional histories warn, no supported enabled integration fails, and broken advertised automatic registration fails only its integration. Verify config parsing for native JSON/TOML without a new runtime dependency on Python 3.9.
- [ ] Run `python -m pytest tests/test_checks.py tests/test_package_files.py -q`; require new failures before implementation.
- [ ] Implement runtime-specific check/remediation output. Add canonical prompt-submit capture registration alongside stop. Confirm actual baseline dispatcher discriminator/envelope in the pinned Spec Kit source before finalizing payload fixture shape; adapt Task 2 fixtures if the verified contract differs.
- [ ] Extend baseline install/update/remove tests across integrations, checking skills paths, retained config and both event registrations. Run `python -m pytest tests/integration/test_speckit.py -q`; require successful dispatch with synthetic native payloads, not just file existence.
- [ ] Run opt-in real-agent smoke tests on installed supported agents in disposable Spec Kit projects. Record agent version, OS, native events delivered and resulting report. `test_native_events.py` must skip clearly when a native agent/account is unavailable and never promote a skip to an automatic-support claim. Document that runtime as manual/unverified until delivery is demonstrated.
- [ ] Rerun checks/package tests; require pass. Commit `feat: validate Codex and Cursor integration capture modes`.

## Task 10: v0.2 release preparation and branch verification

**Files:** Modify `scripts/python/usage_bridge/__init__.py`, `extension.yml`, README, commands, changelog, `docs/limitations.md`, `docs/release.md`, packaging/doc tests, workflows only if packaging coverage requires it. Add release migration notes and verified platform matrix.

**Interfaces:** Version `0.2.0` in Python/manifest/generated catalog; existing archive builder CLI remains unchanged. Include all adapter modules and bridge pricing data; keep vendor hashes unchanged.

- [ ] Add package tests for new files, matching version metadata, vendor invariance and installability of the built archive. Add doc assertions only for exact contractual text/version facts, not prose formatting. Run `python -m pytest tests/test_package_files.py tests/test_build_release.py tests/test_docs.py -q`; require failures for outdated release metadata before changes.
- [ ] Update metadata and documentation: all-runtime manual commands, verified automatic modes, opt-in privacy, nullable counts, known-cost subtotals, API-equivalent estimates, local Codex limits, Cursor source precedence, all-contributor upgrade requirement and unsupported downgrade. Preserve historical v0.1 changelog entries.
- [ ] Run `ruff check .`, `python -m pytest -m "not integration" -q` and `python -m pytest -m contract -q`; require exit 0 for each. Run baseline integration suite with its required dependencies/network and record any unavailable real-agent smoke coverage separately.
- [ ] Commit `chore: prepare v0.2 multi-runtime release`. After tracking files, run `python tools/build_release.py --version 0.2.0 --out dist --base-url https://github.com/CrazyBaran/spec-kit-usage-bridge`, inspect ZIP members and install the archive into a disposable project. Verify version/catalog agreement and unchanged `VENDOR.json` hashes. Do not publish.
- [ ] Run `git diff --check`, inspect branch diff for private transcript data, and perform the execution method's whole-branch review. Fix actionable findings and rerun only affected checks plus required completion checks. Report tests run and support limitations truthfully.

## Coverage and handoff

| Spec sections | Owning tasks |
|---|---|
| 1–3 intent, constraints, adapter contract | 1, 2, 8, 10 |
| 4 Codex discovery/accounting/children | 3, 4, 6 |
| 5 Cursor sources and privacy | 5, 8 |
| 6 configuration, capture, commands, checks | 2, 8, 9 |
| 7 measurement, pricing, metrics | 1, 6, 7 |
| 8 schema and migration | 6, 7, 8, 10 |
| 9 errors, performance, privacy | 3, 5, 8 |
| 10 validation and release | Each task's tests; 9, 10 |
| 11 evolving formats and evidence | Fixture provenance in 3–5; native checks in 9 |

Plan self-review: requirements are mapped above; shared names/signatures are defined
before use; all five review-focus conditions have owning tests. Fixtures must validate
real source semantics before claims of exact coverage. No implementation has started.

Recommended execution: **Native** (the executing-plans skill) because these tasks share
digest, identity and report interfaces that benefit from one implementer carrying the
whole migration through. An independent whole-branch review follows implementation.
Alternatively choose **Subagent-driven** for separate implementer/reviewer gates per task.
Wait for written-plan approval and the user's execution-method choice before starting.
