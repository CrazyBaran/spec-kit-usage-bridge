# Native Tooling Alignment 2.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Verify Usage Bridge release archives through native Spec Kit installation and real updates, using newest stable as the current host and accurately reporting compatibility evidence.

**Architecture:** Keep the existing extension archive builder and release verifier. Reuse the public Spec Kit CLI, local HTTP fixture server, and current integration suite. Coordinate explicit host refs across workflows, evidence collection and test defaults; preserve the four required platform/host lanes.

**Tech Stack:** Python standard library, existing PyYAML/pytest/Ruff, uvx, GitHub Actions, actionlint and Zizmor. No new product dependency.

**Spec:** [Draft 2.2](../../references/2.2-native-tooling-alignment-draft.md), with context in [extraction research](../../references/community-extension-tooling-extraction-draft.md). The user approved native execution; all tasks are completed below. Commit and push remain separately authorized actions.

## Global Constraints

- Preserve uncommitted changes on `feat/release-automation`; baseline `238bed63366064ae1ce1e88e4d8ab6529ef12237`.
- “2.2” is a cycle label; do not bump release versions.
- Primary/current host: newest stable, verified as `v1.1.0` / `f1d3a4f8337ebbd3ae22760a9c12e3352b93a175` on 2026-10-04. Recheck once at execution start and record any newer selection consistently.
- Minimum compatibility host: `v1.0.12`. Keep Linux/Windows × minimum/current and existing publication gates.
- Developer host environment supports Python 3.11+; retain Usage Bridge runtime support for Python 3.9.
- Unreleased source can inform design using an exact SHA; `ae5ade7234be5cb1d975f736c4e06dd46d1326d6` was inspected. Do not describe a source build as an official nightly. No mandatory development lane in this plan.
- Preserve source/digest binding, archive limits, allowlists, vendor checks, immutable retries, historical-candidate verification, protected authority and explicit submission gates.
- No toolkit extraction, private host API imports, replacement installer/updater, generic adapter framework or `bundle.yml` support.
- No publication, live settings, upstream submission, commits or pushes without authorization. Skill examples of frequent commits do not override this restriction.
- If commits are later authorized, preserve human Git identity and add exactly once `Co-authored-by: Codex <codex@openai.com>`; inspect attribution before pushing.

## Review Focus

1. An existing `UB_RELEASE_ARCHIVE` must remain the exact update destination; Task 3 asserts its digest is unchanged.
2. Unsupported manifest schema must fail without registration or installed payload; Task 2 checks both outcomes.
3. Native update may exit successfully without applying anything; Task 3 asserts installed version and archive content, not exit code alone.
4. Windows fixture server and subprocess environment must preserve cleanup and UTF-8; Tasks 2–3 run on Windows and Linux with process-scoped catalog overrides.
5. Current workflow refs could drift from evidence refs; Task 1 tests both release and verification workflows against the authoritative mapping.

## Files and responsibilities

| File | Change |
|---|---|
| `tools/release/policy.py` | Define `HOST_REFS` for the two supported lanes; retain evidence validation contracts. |
| `tools/release/orchestration.py` | Use `HOST_REFS` when collecting job evidence. |
| `.github/workflows/release-pipeline.yml`, `.github/workflows/verify-release.yml` | Resolve each lane to its explicit host ref without changing job names/counts. |
| `.github/workflows/ci.yml` | Give ordinary integration jobs the explicit current stable ref. |
| `tests/release_fixtures.py` | Default to current stable; let subprocess helper accept isolated environment overrides. |
| `tests/test_release_workflow_paths.py`, `tests/test_release_orchestration.py` | Test workflow/ref/evidence agreement and retained gates. |
| `tests/integration/test_release_install.py` | Accurate reinstall name, native malformed-manifest rejection and versioned update tests. |
| `docs/release.md`, `docs/references/2.2-native-tooling-alignment-draft.md`, `pyproject.toml` | Ownership, host coverage, integration-marker description, limitations and completed-cycle evidence. |

No additional product modules are planned. Keep archive mutation as a small test-local helper only if the two integration tests need it.

## Execution environment

From `D:\spec-kit-usage-bridge`, use these process-scoped settings. If Git config entries already exist, append the safe-directory entry rather than overwriting them.

```powershell
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$env:UV_CACHE_DIR = "$PWD\build\review-uv-cache"
$env:UB_REQUIRE_INTEGRATION = '1'
$env:GIT_CONFIG_COUNT = '1'
$env:GIT_CONFIG_KEY_0 = 'safe.directory'
$env:GIT_CONFIG_VALUE_0 = 'D:/spec-kit-usage-bridge'
$cycleTemp = Join-Path $env:TEMP ('usage-bridge-2.2-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $cycleTemp | Out-Null
```

Use a fresh child directory under `$cycleTemp` for each pytest `--basetemp` run. This prevents pytest cleanup from touching repository files. Do not change global Git settings. Network failures or missing uvx are environment failures, not successful test evidence.

### Task 1: Align stable host selection and release evidence

**Files:** Modify the policy, orchestration, three workflows, fixture default, and two contract-test files listed above.

**Interfaces:** Produce `HOST_REFS: dict[str, str] = {'minimum': 'v1.0.12', 'current': 'v1.1.0'}` in `release.policy`. Preserve `collect_run_evidence(..., host_refs=None, *, install_prefix='install') -> dict`; its default consumes `HOST_REFS`, while explicit overrides retain existing behavior. Preserve `host_ref() -> str`, respecting `UB_SPEC_KIT_REF` and defaulting to current stable.

- [x] **Step 1:** Recheck GitHub's newest non-prerelease release and resolve its SHA. Inspect its public extension update/catalog interface and Python floor. If a newer stable exists, replace `v1.1.0` consistently in this task and record the change; do not use a moving ref at execution time.
- [x] **Step 2:** Add failing `test_release_host_refs_match_collected_evidence` in `tests/test_release_workflow_paths.py`. Assert both workflow matrices keep `host == ['minimum', 'current']` and both OS entries. Assert the install step's `UB_SPEC_KIT_REF` selects the exact `HOST_REFS` values for its lane. Add `test_collected_runtime_records_use_supported_host_refs` in `tests/test_release_orchestration.py`, reusing its existing API fixture, asserting `{r['host']: r['host_ref'] for r in result['runtime']} == HOST_REFS`. Preserve tests for explicit overrides.
- [x] **Step 3:** Run `.venv\Scripts\python.exe -m pytest tests/test_release_workflow_paths.py tests/test_release_orchestration.py -q --basetemp "$cycleTemp\task1-red"`. Expect failure because current workflow/evidence refs are both `v1.0.12` or `HOST_REFS` is absent.
- [x] **Step 4:** Add `HOST_REFS` and consume it in the collector and fixture default. Use a simple GitHub expression selecting minimum/current literal refs in both workflow install steps. The contract test must compare these literal refs with `HOST_REFS`; no new configuration generator. Set CI integration `UB_SPEC_KIT_REF` to current stable. Preserve job names, permissions, dependencies, overrides and archive paths.
- [x] **Step 5:** Replace integration test fallback literals with `host_ref()` except the intentionally explicit minimum install case. Run Step 3 with `task1-green`; expect all tests pass. Inspect other `v1.0.12` literals and retain historical fixtures/required minimum cases; do not replace indiscriminately.
- [x] **Step 6:** Review the diff for unchanged four-job gates and correct archive/source bindings. Leave changes uncommitted.

### Task 2: Prove native rejection and name reinstall coverage accurately

**Files:** Modify `tests/release_fixtures.py` and `tests/integration/test_release_install.py`.

**Interfaces:** Extend `_run(cmd: list[str], cwd: Path | None = None, *, env: dict[str, str] | None = None, **kwargs) -> subprocess.CompletedProcess[str]` to merge overrides into the existing UTF-8 subprocess environment. Keep success assertion behavior. Failed-install tests invoke `subprocess.run` directly with captured output so failure is testable. Reuse `_serve(directory: Path)` and `specify_command(ref: str)`.

- [x] **Step 1:** Rename `test_upgrade_preserves_config_and_reports` to `test_forced_reinstall_preserves_config_and_reports`; keep its same-archive `add --force` assertions. This is a truthful rename and does not require an artificial failing test.
- [x] **Step 2:** Add `test_native_install_rejects_unsupported_manifest_schema`. Copy the release ZIP into `tmp_path`, changing only `usage-bridge/extension.yml` to `schema_version: 'unsupported-test-schema'`; preserve every other member and avoid duplicate names. Initialize a fresh disposable project through native `init`. Serve the invalid archive locally and run native `extension add usage-bridge --from URL`, capturing result.

  Required assertions: `result.returncode != 0`; the host reports a manifest/schema failure rather than only a network error; no installed `usage-bridge/extension.yml`; native `extension list` or the documented registry representation confirms no successful Usage Bridge registration. Inspect the latest stable host's registry format before selecting the assertion. Do not depend on a private Python class.
- [x] **Step 3:** Run `.venv\Scripts\python.exe -m pytest tests/integration/test_release_install.py -k 'unsupported_manifest or forced_reinstall' -q --basetemp "$cycleTemp\task2"` with `UB_SPEC_KIT_REF` set to current stable. A new characterization test may pass immediately because the host already rejects the schema; record that honestly. Do not modify the host or disable validation to manufacture red.
- [x] **Step 4:** Make only the helper/environment changes needed for the test, then rerun it on minimum stable as well. Expect rejection and reinstall preservation on both supported refs. Investigate any mismatch before declaring shared semantics.
- [x] **Step 5:** Review fixture cleanup and ensure no production archive or manifest changed. Leave changes uncommitted.

### Task 3: Verify a real native update to the exact release archive

**Files:** Modify `tests/integration/test_release_install.py`; reuse Task 2's subprocess interface.

**Interfaces:** Use `host_ref()`, `specify_command(ref)`, `_run(..., env={'SPECKIT_CATALOG_URL': url})`, `_serve(...)`, and `install_archive_project(...)`. The target is the existing `release_archive` fixture, including an externally supplied `UB_RELEASE_ARCHIVE`. The older archive is a test-only derivative with manifest version `0.0.0`; assert the target version is greater before testing. No updater helper/product interface is introduced.

- [x] **Step 1:** Add `test_native_update_preserves_config_and_reports`. Compute the target ZIP digest, derive its real manifest version, create the older fixture ZIP, and install that older version. Assert the initial installed version is `0.0.0`. Write local author configuration and a report containing `kept history\n`.
- [x] **Step 2:** Serve a minimal valid catalog and the untouched target ZIP from the same local server. Build its entry from the real target manifest with matching identity, version, requirements, command metadata and target SHA-256. Set the catalog override only for the update subprocess, run `specify extension update usage-bridge`, and confirm with `y\n`.
- [x] **Step 3:** Assert installed version equals the target version and differs from `0.0.0`; installed manifest bytes match the target archive manifest; local author and report contents survive; target archive digest is unchanged. A zero exit code with no version change fails. Ensure the catalog points to the exact supplied target rather than rebuilding it.
- [x] **Step 4:** Run `.venv\Scripts\python.exe -m pytest tests/integration/test_release_install.py -k native_update -q --basetemp "$cycleTemp\task3-red"` against current stable. Record the actual failure or immediate characterization pass. If fixture setup fails, fix that failure before interpreting update behavior.
- [x] **Step 5:** Apply the smallest fixture/environment correction demonstrated by Step 4. Run the same test with `task3-current` on current stable and `task3-minimum` on `v1.0.12`; both must pass for existing evidence to claim upgrade success in all four lanes. Keep the `upgrade` evidence key and existing gate unchanged.
- [x] **Step 6:** Run the full integration file on each supported host. If native update cannot satisfy the minimum contract, stop with the exact failure and a proposed support-policy decision; do not silently skip the mandatory check or substitute forced reinstall.
- [x] **Step 7:** Review the target-byte invariant, process-scoped catalog override, server cleanup and absence of publication credentials. Leave changes uncommitted.

### Task 4: Record ownership and proven overlap

**Files:** Modify `docs/release.md` and the 2.2 draft. Update extraction research only if its conclusions would otherwise contradict completed results.

**Interfaces:** Documentation consumes actual host refs, test names and results from Tasks 1–3; no new evidence schema or runtime API.

- [x] **Step 1:** Add a short ownership table: native host owns manifest/install/update semantics; local builder owns tracked runtime packaging; product tests own command behavior; local release verifier owns published-byte/source/provenance checks; upstream owns catalog acceptance.
- [x] **Step 2:** State distinct minimum/current versions, tested Python/platform coverage, real update versus forced reinstall, and stable versus unreleased source findings. Clarify that `release-verification.json` in the fixture is diagnostic, while existing pipeline evidence binds jobs/source/digests.
- [x] **Step 3:** Document that no local release checks were deleted because equivalent native coverage at their offline/privileged trust boundary was not demonstrated. If implementation discovers a deletion candidate, trace every caller and add a regression proving preserved behavior before removing it; this plan does not authorize speculative deletion.
- [x] **Step 4:** Check Markdown links, examples and terminology. Record fresh verification only after Task 5; keep historical `802 passed, 3 expected skips` labeled historical. Leave changes uncommitted.

### Task 5: Integrated validation, review and pause

**Files:** Review the combined diff; update completion evidence in the 2.2 draft.

**Interfaces:** No new interfaces. This task accepts only successful fresh checks and explicit limitations.

- [x] **Step 1:** Run `.venv\Scripts\python.exe -m pytest tests/test_release_policy.py tests/test_release_orchestration.py tests/test_release_workflow_paths.py tests/test_release_publication.py tests/test_release_verification.py tests/test_release_cli.py tests/test_release_regressions.py -q --basetemp "$cycleTemp\release"`. Expect all pass, including candidate-to-stable and immutable retry regressions.
- [x] **Step 2:** Clear unintended catalog overrides and set the explicit current stable host. Run `.venv\Scripts\python.exe -m pytest -q --basetemp "$cycleTemp\full"`. Expect no unexpected failures/skips; explain the existing platform/authenticated-event skips. Task 3's separate minimum run remains required.
- [x] **Step 3:** Run `.venv\Scripts\ruff.exe check .`, `build\review-tools\actionlint.exe`, and `.venv\Scripts\uvx.exe --from zizmor==1.30.1 zizmor --offline --min-severity high .github/workflows` with repository configuration, matching `.github/workflows/workflow-checks.yml`. Verify the existing actionlint binary is v1.7.12 before use. Reuse the dependency cache; install nothing into the product. Record commands/results; inability to run a checker is a limitation, not a pass. Run `git -c safe.directory=D:/spec-kit-usage-bridge diff --check` and separately inspect untracked Markdown files.
- [x] **Step 4:** Use `superpowers:requesting-code-review` for an independent read-only combined-change review. Review host-map/evidence agreement, real update success, malformed-install cleanup and preserved release security. Handle feedback with `superpowers:receiving-code-review`; rerun only checks justified by changes.
- [x] **Step 5:** Use `superpowers:verification-before-completion`, record exact fresh outcomes and remaining live-workflow uncertainty. Check final status to confirm unrelated work survived and no commit/push/publication occurred.
- [x] **Step 6:** Pause. Report changed behavior, tests, review findings and limitations. Provide a restart prompt covering only remaining work and requiring separate authorization for any commit/push/live action.

## Plan self-review

- Draft requirements map to Tasks 1–4; acceptance and release preservation map to Task 5.
- Native reuse is through public subprocess commands. No whole-module replacement is claimed.
- Task 3 makes existing `upgrade` evidence truthful without renaming metadata keys or weakening gates.
- Four named release lanes remain; latest stable advances current coverage while minimum stays compatibility-only.
- Characterization tests may pass immediately; no fake TDD failures are required for existing native behavior.
- File/signature dependencies and five review-focus conditions are assigned explicitly. Implementation is complete; commits remain pending authorization.

## Execution result (2026-10-04)

Native execution completed; changes remain uncommitted. Full suite: 808 passed, 3 expected skips with existing CI `UB_PERF_MARGIN=3`. Installed-archive checks: 8 passed on each host locally on Windows; supplied archive checks: 2 passed. Release regressions: 113 passed. Ruff, actionlint, configured Zizmor and independent review passed. Default margin 1 narrowly missed the unchanged warm-path budget; see the spec execution record for limitations and restart prompt. No live operations were performed.
