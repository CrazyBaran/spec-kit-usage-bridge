# Gated Release Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release a minimal Usage Bridge archive through tested prereleases and approved stable promotion, then merge fixes back and submit truthful metadata through official Spec Kit issues.

**Architecture:** Small Python development-tool modules own packaging, release decisions, publication reconciliation, and submission state; GitHub Actions orchestrates them with isolated testing and protected publishing jobs. Stable promotion reuses the verified candidate ZIP, and independent follow-through makes submission/merge-back retryable without republishing.

**Tech Stack:** Python 3.9-compatible tooling and runtime, pytest/Ruff/PyYAML, GitHub Actions, GitHub CLI/API, GitHub App installation tokens, protected environments, immutable releases, actionlint and zizmor.

**Spec:** [Release automation design](../specs/2026-10-02-release-automation-design.md). Research: [pipeline development references](../../references/pipeline-development-practices.md). Prerequisite: [repository protection plan](2026-10-02-repository-protection.md).

**Status:** Planning requested on 2026-10-02; plan review and execution-method selection pending. No workflow/settings implementation occurs during planning.

## Global Constraints

- Python 3.9+ and Spec Kit 1.0.12+ remain the baseline.
- The extension is distributed as files, not as a Python package.
- Stable releases must never skip prerelease.
- Final fixes go onto release/X.Y.Z; any new commit after the last candidate makes that candidate ineligible for promotion.
- Maintain one usage-bridge/ top-level folder; exclude README.md, CHANGELOG.md, docs, tests, tools, CI workflows, development configuration, repository instructions, Git metadata, caches, and unrelated files.
- Preserve the pinned token-usage commit and hashes; retain all required legal files and runtime data.
- Missing, skipped, cancelled, pending, or unavailable results are not successful checks.
- Never waive candidate existence, source-to-candidate equality, version/tag consistency, runtime allowlist, legal files, archive digests, or successful isolated installation/runtime verification.
- Override applies only to that run and SHA; it does not bypass main's merge requirements or spec-kit's submission checklists.
- Workflows containing publishing authority run from protected main and check out release code separately for unprivileged testing.
- Tags are immutable and existing published assets are never replaced. No direct catalog PRs or mutations of the user's Spec Kit fork.
- Allow one active release train; never use force push to recover a release branch.
- Preserve human author/committer identity for Codex-created commits; use exactly one required Codex trailer and inspect before pushing.
- No personal transcripts, raw account data, secrets, or personal paths in tests or committed reports.

## Review Focus

1. Process stops between draft/tag/upload operations: reconcile exact source/digests without duplicating, publishing partial content, or replacing assets (Task 6).
2. GitHub reports a successful run containing skipped/missing jobs or an old head: require every expected job and the exact SHA (Tasks 2, 7).
3. ZIP members escape extraction, exhaust resources, or conceal omitted data: bound sizes/members and verify the exact runtime surface before running it (Tasks 1, 3).
4. Upstream workflow/form or issue triage changes between reads: stop on policy drift and re-read issue state immediately before an update (Task 9).
5. Approval is replayed after branch movement or a rerun: bind approval and waived checks to the exact run attempt/SHA/digest (Tasks 2, 5, 7).

---

## Planning decisions from the research

Implement deterministic ZIP metadata, draft-first immutable publication, workflow
lint/security checks, and bounded failure evidence as safeguards for the specified
flow. Add candidate build provenance only with verification of the real build
identity; automatic OIDC workflow metadata alone must not misidentify protected
main as the release source. Bind the checked-out source SHA explicitly in the
provenance predicate/verified release record.

These strengthen the existing design without adding a new distribution platform.
Dependabot, scheduled host monitoring, Scorecard, and a new aggregate main check
remain separate follow-up PRs. Initial main protection keeps its seven known checks.

## Files and boundaries

| File | Responsibility |
|---|---|
| `tools/build_release.py` | Existing public build interface and new CLI tag input |
| `tools/release/__init__.py` (new) | Development-only package marker |
| `tools/release/artifacts.py` (new) | Allowlist, deterministic ZIP, catalog/digests, bounded validation |
| `tools/release/models.py`, `policy.py` (new) | Typed release evidence and pure state/gate decisions |
| `tools/release/prepare.py` (new) | Idempotent branch/version/changelog/draft-PR preparation |
| `tools/release/publication.py` (new) | Tags, drafts, uploads, immutable publication reconciliation |
| `tools/release/verification.py` (new) | Remote asset/evidence/provenance validation |
| `tools/release/submission.py` (new) | Policy fingerprints, issue rendering, issue-state reconciliation |
| `tools/release/mergeback.py` (new) | Mark ready, enable normal merge-commit auto-merge, report conflicts |
| `tools/release_cli.py` (new) | Thin CLI entrypoints; structured output/exit codes |
| `tools/repository_policy.py`, `tools/configure_repository.py` | Extend prerequisite tooling for tags/environments/immutability |
| `.github/workflows/ci.yml` | Accept exact source ref for reusable runs; keep current matrix/job names |
| `.github/workflows/release.yml` | Replace tag-push publisher with candidate dispatch flow |
| `.github/workflows/prepare-release.yml`, `promote-release.yml` (new) | Preparation and stable promotion dispatches |
| `.github/workflows/verify-release.yml`, `release-follow-through.yml` (new) | Explicit reuse and manual-publication detection/retries |
| `.github/release-policy.json` (new) | Owned check names, environments, source trust, bounded artifact limits |
| `.github/upstream-submission-policy.json` (new) | Reviewed upstream commit, form mapping, content fingerprints |
| `requirements-dev.txt`, `requirements-dev.lock` (new lock), `.github/workflows/workflow-checks.yml` (new) | Compatible hashed CI tooling; pinned workflow linters |
| `tests/test_release_*.py` (new), existing build/workflow tests | Pure policy and mocked API/process behavior |
| `tests/integration/test_speckit.py` | Actual clean archive install/runtime/upgrade coverage |
| `docs/release.md`, `docs/repository-maintenance.md`, `README.md` | Operator setup, dispatch, failure recovery, accurate install status |

## Test/commit conventions and execution order

Run repository virtual-environment `python -m pytest`, using the existing hermetic
fixture. Tool tests import `tools.release` with repository-root pytest path support;
include that path in `pyproject.toml` when Task 1 introduces the package. Keep all
tool dependencies out of the release ZIP. Tool code uses future annotations and
avoids Python 3.10-only execution APIs so the existing matrix can test it.

Every task: failing test -> observed failure -> minimal implementation -> passing
focused tests -> explicit-file commit. Commit with
`git commit -m '<message>' -m 'Co-authored-by: Codex <codex@openai.com>'`.
Read spec and prerequisite plan before execution. Use isolation at execution time
if needed; preserve the existing untracked architecture reference.

### Task 1: Minimal deterministic archives and separate tag identity

**Files:** Modify `tools/build_release.py`, `pyproject.toml`, `tests/test_build_release.py`; create `tools/release/__init__.py`, `artifacts.py`, `tests/test_release_artifacts.py`.

**Interfaces:** Preserve `build(repo: Path, version: str, out_dir: Path, base_url: str) -> tuple[Path, Path]`, extending with keyword-only `release_tag: str | None = None`. Produce `runtime_members(repo: Path) -> tuple[str, ...]`, `validate_archive(path: Path, expected_members: tuple[str, ...], limits: dict | None = None) -> dict`, `write_catalog(repo: Path, archive: Path, version: str, release_tag: str, base_url: str, output: Path) -> Path`. Returned validation includes SHA-256, member list, and uncompressed bytes. Default limits are 25 MiB compressed, 100 MiB expanded, and 1,000 members; Task 2's policy config overrides them explicitly rather than adding another validator.

- [ ] **Step 1: Add failing packaging tests**, including:

```python
def test_candidate_catalog_is_tag_pinned(tmp_path):
    archive, catalog = build(ROOT, '0.2.1', tmp_path, BASE, release_tag='v0.2.1-rc.1')
    data = json.loads(catalog.read_text())
    assert data['extensions']['usage-bridge']['version'] == '0.2.1'
    assert '/download/v0.2.1-rc.1/' in data['extensions']['usage-bridge']['download_url']
    assert '/download/v0.2.1-rc.1/' in data['catalog_url']
    assert data['extensions']['usage-bridge']['sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
```

Also assert `test_runtime_members_exact_and_legal` equals manifest commands,
four entrypoints, package `.py` modules, OpenAI pricing JSON, four vendored files,
manifest/config/legal files; `test_rebuild_ignores_mtime_and_mode` produces identical
ZIP bytes after checkout metadata changes; `test_symlink_traversal_and_zip_bomb`
rejects malicious members and excessive sizes before extraction; `test_untracked_runtime_module_rejected`
does not accidentally package local files. Retain existing build compatibility tests.

- [ ] **Step 2: Run `python -m pytest tests/test_build_release.py tests/test_release_artifacts.py -q`.** Expect candidate-tag/allowlist/determinism failures.
- [ ] **Step 3: Implement.** Select tracked manifest commands and explicit runtime patterns; vendor allowlist is `VENDOR.json`, `LICENSE`, `scripts/token_usage.py`, `data/pricing.json`. Reject links, duplicates, encrypted members, path escapes, and unexpected entries. Normalize sorted paths, source-commit UTC ZIP timestamps with a 1980 floor and two-second resolution, permissions, and extra fields. Bound archive to 25 MiB compressed, 100 MiB expanded, and 1,000 members in `.github/release-policy.json` when introduced in Task 2. Stable catalog keeps its latest URL; candidate catalog is tag-pinned. Do not require timestamped catalog bytes to reproduce.
- [ ] **Step 4: Run focused tests and existing package-file/vendor-hash tests.** Expect pass, with runtime ZIP identity asserted on the publishing environment.
- [ ] **Step 5: Commit:** `feat: build minimal deterministic release archives`.

### Task 2: Release evidence and gate policy

**Files:** Create `models.py`, `policy.py`, `.github/release-policy.json`, `tests/test_release_policy.py` under the paths above.

**Interfaces:** Define frozen dataclasses `CheckResult(name: str, source_sha: str, run_id: int, attempt: int, app_id: int, status: str, conclusion: str | None, url: str)`, `OverrideRequest(requested: bool, reason: str, waived_checks: tuple[str, ...], run_id: int, attempt: int, source_sha: str, approved: bool, approver: str | None)`, and `GateDecision(allowed: bool, blockers: tuple[str, ...], waived: tuple[str, ...])`. Produce `parse_version(value: str) -> tuple[int, int, int]`, `next_candidate_tag(version: str, existing_tags: tuple[str, ...]) -> str`, `evaluate_checks(checks: tuple[CheckResult, ...], required: tuple[str, ...], source_sha: str, override: OverrideRequest) -> GateDecision`, and `require_candidate(version: str, tip_sha: str, candidate: dict | None) -> None` (raises `ReleasePolicyError`). Metadata dictionaries use `schema_version=1`, repository, version, tag, source_sha, run_id, attempt, zip_sha256, candidate_tag, checks, override, and verification result fields; unknown schema is rejected.

- [ ] **Step 1: Add tests.** Assert rc.9 -> rc.10 numerically; reject invalid versions/leading-zero semver and shell-like input. Parametrize `test_incomplete_check_never_waived` for pending/missing/skipped/cancelled. Assert approved exact-run lint failure can be waived, stale attempt/head/App results cannot, all seven expected contexts are necessary, candidate must be published prerelease with same version/SHA, and `candidate=None` is blocked regardless of override.
```python
def test_no_candidate_cannot_be_overridden():
    with pytest.raises(ReleasePolicyError):
        require_candidate('0.2.2', 'a' * 40, None)

def test_candidate_numbers_are_numeric():
    assert next_candidate_tag('0.2.2', ('v0.2.2-rc.9',)) == 'v0.2.2-rc.10'
```

- [ ] **Step 2: Run `python -m pytest tests/test_release_policy.py -q`.** Expect missing interfaces.

- [ ] **Step 3: Implement pure decisions.** `.github/release-policy.json` holds the seven known check names, artifact bounds from Task 1, canonical repository/main, and environments `release-publish`, `release-override`, `catalog-submit`. Waivable failures are the seven completed CI quality jobs; mandatory packaging/install/digest/source/prerelease checks are outside that list. Exact-source/required-job evidence must be present before waiving anything.
- [ ] **Step 4: Run policy/artifact tests.** Expect pass; exercise all Review Focus 2 and 5 conditions.
- [ ] **Step 5: Commit:** `feat: enforce candidate and release check policy`.

### Task 3: Isolated archive installation and runtime verification

**Files:** Modify `tests/integration/test_speckit.py`; create `tests/integration/test_release_install.py`, `tests/release_fixtures.py`.

**Interfaces:** Produce test helper `install_archive_project(tmp_path: Path, archive: Path, host_ref: str) -> Path`. Host refs are explicit resolved tag/SHA inputs supplied through `UB_SPEC_KIT_REF`, defaulting to existing `v1.0.12`; tests never silently use a moving main host. No production runtime imports from the repository checkout in consumer subprocesses.

- [ ] **Step 1: Add failing tests.** `test_installed_runtime_without_repo_pythonpath` runs the four installed entrypoints with sanitized synthetic runtime history, asserts checkpoint binding/capture/report/check behavior and generated report data; `test_archive_contains_exact_installed_surface` compares payload; `test_upgrade_preserves_config_and_reports` preserves edited config/history; parametrized Claude/Codex/Cursor installs verify command rendering/event registration. Do not simulate authenticated native events as proven real delivery.
```python
def test_archive_contains_exact_installed_surface(tmp_path, release_archive):
    project = install_archive_project(tmp_path, release_archive, 'v1.0.12')
    installed = project / '.specify/extensions/usage-bridge'
    assert (installed / 'scripts/python/checkpoint.py').is_file()
    assert (installed / 'scripts/python/usage_bridge/data/openai-pricing.json').is_file()
    assert not (installed / 'tests').exists()
    assert not (installed / 'docs').exists()
```

`release_archive` is a Task 3 fixture that calls Task 1's builder on the test source
checkout; `install_archive_project` is the only consumer installation helper.

- [ ] **Step 2: Run `python -m pytest tests/integration/test_release_install.py -m integration -q`.** Expect missing helper or insufficient packaging/runtime setup; skip only when integration is intentionally unavailable locally.

- [ ] **Step 3: Implement fixtures/tests and isolated subprocess setup.** Serve the ZIP on an OS-assigned local port; keep synthetic sources outside the repository. Use `UB_REQUIRE_INTEGRATION=1` in release CI to make absent tools a failure. Resolve minimum host from manifest requirements and current stable once per run; store exact refs in verification evidence.
- [ ] **Step 4: Execute minimum/current stable tests on Linux and Windows Actions.** Expect all commands and archive assertions pass; existing authenticated-delivery limitations remain documented.
- [ ] **Step 5: Commit:** `test: verify isolated release install and upgrades`.

### Task 4: Idempotent release preparation

**Files:** Create `prepare.py`, `tools/release_cli.py`, `tests/test_release_prepare.py`.

**Interfaces:** Consume `GitHubAPI`, `parse_version`. Produce `prepare_release(api: GitHubAPI, repo: str, version: str, main_sha: str) -> dict` with branch, draft PR URL, source SHA, and reused flag; CLI `prepare --version X.Y.Z --output <json> [--dry-run]`.

- [ ] **Step 1: Write tests.** Assert `release/0.2.2`, one draft PR targeting main, manifest/changelog changed together, no tags/releases created, same-train retries reuse existing branch/PR, another open release train blocks, older version blocks, and existing maintainer fixes are never overwritten. Use a temporary Git repository plus mocked API state; add injected failure after branch creation and verify retry recovery.
```python
def test_prepare_never_publishes_release(fake_api):
    result = prepare_release(fake_api, 'CrazyBaran/spec-kit-usage-bridge', '0.2.2', 'a' * 40)
    assert result['branch'] == 'release/0.2.2'
    assert fake_api.created_pull_requests[0]['draft'] is True
    assert fake_api.created_releases == []
    assert fake_api.created_tags == []
```

Create the local `fake_api` fixture in this test file implementing the
prerequisite plan's `GitHubAPI.request`/`pages` interface (`tools/github_api.py`)
with these recorded collections; do not depend on a live GitHub fixture.

- [ ] **Step 2: Run `python -m pytest tests/test_release_prepare.py -q`.** Expect missing interface failures.

- [ ] **Step 3: Implement preparation.** Require fresh main SHA and semver greater than newest published stable. Use a prepared tree/commit based on captured main and update only manifest/changelog; establish branch by atomic ref creation. Use explicit bot identity for operational Actions commits, distinct from human-attributed Codex implementation commits. Never force-push or rewrite an existing release branch. Check the PR list before creating another draft.
- [ ] **Step 4: Run preparation/API tests.** Expect no unapproved release side effect on dry-run and stable retry behavior.
- [ ] **Step 5: Commit:** `feat: prepare release branches through draft PRs`.

### Task 5: Release authority, environments, and immutable settings

**Files:** Extend `tools/repository_policy.py`, `tools/configure_repository.py`, their tests; update `docs/repository-maintenance.md`.

**Interfaces:** Produce `release_settings_plan(existing: dict, release_app_id: int, reviewer_id: int) -> list[dict]`, `verify_release_settings(observed: dict, expected: dict) -> list[str]`. Extend configuration CLI with `release --release-app-id <id> --reviewer CrazyBaran [--apply]`.

- [ ] **Step 1: Add tests.** Assert v* creation only bypassed by the named App, no main bypass, release environments constrained to protected main, `release-override`/`catalog-submit` require CrazyBaran approval with self-review permitted and admin bypass disabled. Assert no secret values in reports and unrelated settings retained; missing App installation blocks setup.
```python
def test_release_app_cannot_bypass_main():
    assert main_ruleset(actions_app_id=15368)['bypass_actors'] == []
    operations = release_settings_plan(existing={}, release_app_id=4242, reviewer_id=777)
    override = next(op['payload'] for op in operations if op['path'].endswith('/environments/release-override'))
    assert override['prevent_self_review'] is False
    assert override['can_admins_bypass'] is False
    assert override['reviewers'] == [{'type': 'User', 'id': 777}]
```

For this pure-policy fixture `existing={}` means no owned release settings yet;
installed App validation belongs to CLI preflight, before applying operations.

- [ ] **Step 2: Run repository policy/configuration tests.** Expect missing release configuration behavior.

- [ ] **Step 3: Implement settings plan and setup guide.** Enable immutable releases through the supported repository setting/API and verify read-back; if API support is absent, provide exact UI step and verify afterward rather than pretend an unsupported PATCH succeeded. Use separate tag-creation authority and tag-update/deletion restrictions; no actor receives main bypass. App permissions: contents and pull requests write; checks/actions/deployments read as needed; no administration write. Install only in this repository.
- [ ] **Step 4: Document prerequisites concretely.** Variables: `RELEASE_APP_ID`, reviewer/app IDs resolved via API; environment secret `RELEASE_APP_PRIVATE_KEY` only in trusted authority jobs using release-publish/release-override. Preparation uses the same App through release-publish to create the branch/PR and trigger normal CI; its tested entrypoint performs no tag/release operation. No App key/token is present in build/test jobs. Upstream user credential `SPEC_KIT_SUBMISSION_TOKEN` only in catalog-submit. The maintainer registers/installs the App and sets private-key/user credentials through GitHub; never commit or print them. No personal-token fallback for publication.
- [ ] **Step 5: Test and dry-run the exact settings.** Apply only after prerequisite configuration exists; verify effective tags, environments, immutability, and unchanged main protection. Missing prerequisites leave publishing visibly disabled without blocking unrelated packaging work.
- [ ] **Step 6: Commit:** `feat: configure constrained release authority`.

### Task 6: Idempotent publication and provenance verification

**Files:** Create `publication.py`, `verification.py`, `tests/test_release_publication.py`, `tests/test_release_verification.py`; extend CLI.

**Interfaces:** Produce `publish_release(api: GitHubAPI, evidence: dict, assets: dict[str, Path], prerelease: bool) -> dict`, `verify_release(api: GitHubAPI, tag: str, expected: dict, download_dir: Path) -> dict`. Verification receives an injected downloader/provenance verifier in tests. CLI `publish --evidence <json> --assets <dir> [--dry-run]` and `verify --tag <tag> --expected <json> --output <json>`. Trusted workflow passes credentials only at publication; subprocess runners cannot execute downloaded metadata as code.

- [ ] **Step 1: Write tests.** Draft creation -> all expected assets upload -> digest/set verification -> publication; rc is prerelease and not latest. `test_latest_only_for_newest_stable` publishes 0.2.2 after 0.3.0 exists and asserts `make_latest == 'false'`; `test_stable_notes_match_changelog` asserts the release body equals the `## [X.Y.Z]` CHANGELOG.md section from the source SHA and refuses publication when that section is absent. A retry reuses matching draft/tag/assets, mismatches refuse publication, asset replacement is never requested, unrelated API error is not interpreted as absent release. Test interrupted uploads and publish-response timeout reconciliation. Verification rejects tampered digest, wrong source/version, unknown metadata schema, missing provenance, wrong build identity, duplicate assets, or unexpected payload before extraction.
```python
def test_publish_retry_never_replaces_asset(fake_api, candidate_evidence, candidate_assets):
    first = publish_release(fake_api, candidate_evidence, candidate_assets, prerelease=True)
    second = publish_release(fake_api, candidate_evidence, candidate_assets, prerelease=True)
    assert first['release_id'] == second['release_id']
    assert fake_api.replaced_assets == []
    assert len(fake_api.created_releases) == 1
```

Local test fixtures model the recorded API operations, complete schema-1 evidence,
and Task 1 artifacts. A fixture is not an approval source in production.

- [ ] **Step 2: Run both new files.** Expect missing implementation.

- [ ] **Step 3: Implement with bounded API/network operations.** Assets are ZIP, catalog.json, checksums, release-metadata.json, and build provenance bundle as applicable. Attest candidate build where it occurs, explicitly bind release source/digest, verify original build provenance on promotion, and retain GitHub immutable release attestation. Do not assert a later promotion runner built the original ZIP. Preserve candidate bytes in stable publication; generate stable URL metadata independently. Release notes come from the matching CHANGELOG.md section at the source SHA; set `make_latest` explicitly (`true` only when the version exceeds every published stable, otherwise `false`; always `false` for candidates). Tag creation names the captured SHA; remote source is rechecked immediately beforehand.
- [ ] **Step 4: Run publication/verification/policy/artifact tests.** Expect failure recovery without duplicate release or asset mutation; published bytes must be verified before follow-through.
- [ ] **Step 5: Commit:** `feat: publish and verify immutable release artifacts`.

### Task 7: Trusted preparation, candidate, and promotion workflows

**Files:** Modify `ci.yml`, `release.yml`, `tests/test_workflows.py`; create `prepare-release.yml`, `promote-release.yml`, `verify-release.yml`, `tests/test_release_workflow_paths.py`; extend CLI.

**Interfaces:** `ci.yml` accepts optional `source_sha` string for `workflow_call`; existing push/PR behavior is unchanged. Add CLI `candidate-context --version ... --output ...`, `promotion-context --version ... --candidate-tag ... --output ...`, and `gate --checks ... --override ... --output ...`. These assemble remote evidence using prior interfaces, with no publication side effect. Map reusable-job qualified names to policy identities using the inspected workflow/run/job IDs; never infer identity by an arbitrary suffix match.

- [ ] **Step 1: Add failing workflow contract/path tests.** Assert the tag-push publisher is absent; dispatches require main as workflow source; validation checks out captured release SHA without publishing secrets; CI and mandatory artifact/install checks precede publication. Mock candidate->fix->stale-promotion (blocked)->new-candidate->stable path. Approved lint failure can proceed but missing install evidence cannot. Override skipped on normal green path, approval required only on requested completed failures, approval replay rejected.
```python
def test_tag_push_cannot_publish():
    release = wf('release.yml')
    triggers = release.get('on', release.get(True))
    assert 'workflow_dispatch' in triggers
    assert 'push' not in triggers
```

Reuse the existing workflow reader in `tests/test_workflows.py`. Gate behavior is
tested through Task 2 interfaces and mocked Task 7 context commands, not YAML alone.

- [ ] **Step 2: Run workflow/path tests.** Expect existing tag trigger and missing dispatch workflows to fail.

- [ ] **Step 3: Implement thin Actions wiring.** Prepare runs as a trusted authority job using release-publish, opens a branch/PR with App authentication, and triggers normal CI; candidate and promotion call reusable CI from protected main with explicit SHA. Promotion downloads/verifies candidate bytes and reruns exact-source CI. Add a separate mandatory install matrix of Linux/Windows x minimum/current stable host, Python 3.12, using resolved host tags/SHAs. Capture all expected job/run/attempt results before a gate; no blanket `continue-on-error`. Use an `always()` evaluation job to distinguish quality failures from mandatory failures and allow only requested approved quality waivers. Separate publishing runners from build/test runners and fetch pinned trusted scripts there.
- [ ] **Step 4: Add protection and evidence.** Job budgets: 10 minutes prepare, 20 lint/policy/publication, 30 unit matrix, 45 install matrix; network calls 60 seconds. Serial mutation group `usage-bridge-release`, `cancel-in-progress: false`; validate `queue: max` with current Actions/actionlint support and remote-state checks remain mandatory. Override job uses `release-override`; normal publisher uses `release-publish`. Query environment approval history to bind requester/approver to run attempt/source/digest; an input JSON `approved=true` cannot establish approval. Use a scoped App token after approval. Canonical repository guard prevents fork publication. Write bounded JSON/run summaries and upload failure evidence with explicit retention.
- [ ] **Step 5: Verify workflows locally and with Actions dry-runs after normal PR merge.** Existing seven main check names remain unchanged; reusable checkout SHA is covered by tests. No disposable stable release or upstream issue is created for verification.
- [ ] **Step 6: Commit:** `feat: orchestrate checked candidate and stable promotion`.

### Task 8: Merge-back and publication detection

**Files:** Create `mergeback.py`, `tests/test_release_mergeback.py`; extend `verify-release.yml`/CLI; create `release-follow-through.yml` with `workflow_call` and `workflow_dispatch`.

**Interfaces:** Produce `enable_mergeback(api: GitHubAPI, version: str, release_sha: str) -> dict`. CLI `mergeback --version ... --source-sha ... --verification ... --output ...`. Follow-through receives verified tag/source/digest, not a free-form instruction.

- [ ] **Step 1: Write failing tests.** Assert verified stable release marks the matching draft PR ready and enables merge-commit auto-merge without direct main push; conflict reports pending/manual action; failed required checks cannot trigger immediate merge; missing verification blocks. Already-merged PR yields a successful no-op, unrelated PR is untouched, branch deletion occurs only after merge. Manual stable release without candidate is flagged and does not submit/merge.
```python
def test_conflict_leaves_release_pr_open(fake_api):
    fake_api.pull_request['mergeable'] = False
    result = enable_mergeback(fake_api, '0.2.2', 'a' * 40)
    assert result['status'] == 'manual_action_required'
    assert fake_api.direct_main_updates == []
    assert fake_api.deleted_branches == []
```

Define `fake_api` locally with a matching release draft PR and the recorded API
collections; missing verification is exercised at the CLI boundary before this call.

- [ ] **Step 2: Run merge-back/workflow tests.** Expect missing behavior.

- [ ] **Step 3: Implement independent follow-through.** Enable auto-merge against current PR identity/head and rely on main rules; do not call force/admin merge APIs. Post-publication verification runs explicitly from candidate/promotion and from `release: published` for manual detection. Manual event path checks policy evidence and reports violations; it cannot retroactively block publication. No elevated job executes downloaded release code; installation verification stays isolated.
- [ ] **Step 4: Run focused tests.** Expect retries independent of upstream submission failure and no credential exposure to manual asset verification.
- [ ] **Step 5: Commit:** `feat: merge release fixes through protected PRs`.

### Task 9: Truthful issue-driven catalog submission

**Files:** Create `submission.py`, `.github/upstream-submission-policy.json`, `tests/test_release_submission.py`, `tests/fixtures/release/upstream-policy/`; extend follow-through/CLI.

**Interfaces:** Produce `render_submission(manifest: dict, release: dict, evidence: dict, form: dict) -> str`, `choose_submission_action(issues: tuple[dict, ...], release: dict) -> dict`, `submit_release(api: GitHubAPI, release: dict, evidence: dict) -> dict`. CLI `submit --tag ... --verification ... --evidence ... --output ... [--prepare-only]`. Actions: `create`, `update_untriaged`, `reuse`, `block`; output contains issue URL/state and blockers.

- [ ] **Step 1: Write tests.** All required official headings appear; download URL is tag-pinned stable ZIP with digest. Missing real-project/doc/security attestation leaves prepare-only data and blocks issue creation. Untriaged owned issue updates to newer semver, older rerun no-ops, same-version retry reuses one issue; labeled issue or linked PR freezes old version and a newer release creates one superseding issue. Ambiguous ownership, form changes, 403, closed rejected submission, and triage between reads all block unsafe edits. Assert no upstream labels applied, no fork/catalog writes, no automatic checklist lies, and shell-like metadata remains literal.
```python
def test_triaged_issue_is_not_rewritten(owned_issue, verified_release):
    owned_issue['labels'] = [{'name': 'extension-submission'}]
    action = choose_submission_action((owned_issue,), verified_release)
    assert action['action'] == 'create'
    assert action['supersedes'] == owned_issue['number']
```

Define local `owned_issue` as this repository's marked, CrazyBaran-authored older
submission and `verified_release` as a newer verified stable version. Same-version
triaged retries must return `reuse`, not create another issue.

- [ ] **Step 2: Run submission tests.** Expect missing module/state logic.

- [ ] **Step 3: Implement with reviewed policy baseline.** Fingerprint live CONTRIBUTING.md, publishing guide, issue form, and validation workflow from a resolved upstream commit; baseline is reviewed content, never executable policy. Generate official headings and Proposed Catalog Entry from verified stable assets. Hidden marker identifies this repository/id; require issue author CrazyBaran. Fetch labels/linked PR/current body again immediately before update and stop if triage moved. Preserve comments and avoid closing reviewed issues. New superseding submissions link prior issue/PR. Remote APIs cannot guarantee atomic issue-state compare-and-swap; report any detected race and require maintainer rerun rather than claiming isolation.
- [ ] **Step 4: Wire evidence approval.** Separate `catalog-submit` environment; publish prepared fields first. Follow-through dispatch inputs supply a real-project test description, documentation-review confirmation, and security-review evidence; verify them and bind the approval to version/digest/run before creating/updating with `SPEC_KIT_SUBMISSION_TOKEN`. Environment approval alone must not silently tick unprovided attestations. Automatic evidence covers only exercised checks. Missing credential/attestation/policy compatibility yields local prepared body and clear pending state; never blocks already verified merge-back.
- [ ] **Step 5: Run submission/API/workflow tests.** Expect mocked issue requests match form and all refused paths make no unsafe external writes.
- [ ] **Step 6: Commit:** `feat: submit verified releases through official catalog issues`.

### Task 10: Workflow/toolchain checks and end-to-end acceptance

**Files:** Create `requirements-dev.lock`, `workflow-checks.yml`, `tests/test_release_cli.py`; modify `requirements-dev.txt`, CI installs, `docs/release.md`, `README.md`, `docs/repository-maintenance.md`.

**Interfaces:** CLI exit codes: 0 successful/reused, 2 invalid input/policy block, 3 API/transient failure, 4 configuration prerequisite missing. Outputs include stage status, next action, run/source/digests, and links; no secrets. Pin compatible dependency versions/hashes and reviewed action SHAs; retain version comments. Linter invocations are pinned and documented, not moving curl scripts.

- [ ] **Step 1: Write CLI acceptance tests.** Exercise prepare, candidate, new fix, blocked stale promotion, new candidate, approved quality override, stable verification, merge-back conflict, submission pending, and independent successful retry against temporary Git/mock APIs. Assert a process interrupted after publishing does not republish on retry. Assert every CLI entrypoint emits usable redacted failures and never submits a prerelease. Test all Review Focus conditions.
```python
def test_submit_prerelease_is_policy_error(cli_fixture):
    result = cli_fixture.run('submit', '--tag', 'v0.2.2-rc.1')
    assert result.returncode == 2
    assert cli_fixture.api.created_issues == []
```

`cli_fixture` is defined in this test file: a temporary Git checkout, injected fake
API and subprocess runner, complete evidence fixtures, and captured exit/output.
It invokes the actual CLI parser/dispatcher; it never starts real gh writes.

- [ ] **Step 2: Run `python -m pytest tests/test_release_cli.py -q`.** Expect incomplete command/evidence wiring.

- [ ] **Step 3: Finish CLI/toolchain/docs.** Add actionlint and zizmor; lock Python tooling with hashes compatible with Python 3.9 and current CI Python. Do not add runtime dependencies. Preserve existing CI contexts while adding workflow checks. Document App/environment setup, Prepare -> Candidate -> Promote, exact override scope, issue lifecycle, immutable retry recovery, admin limit, and configuration/credential blockers. Keep README source-install warning until a real public release is verified; do not advertise nonexistent assets.
- [ ] **Step 4: Run focused policy/CLI tests, full `python -m pytest -m 'not integration' -q`, `python -m ruff check .`, vendor hash contracts, actionlint, and zizmor.** Expect pass. Run Linux/Windows integration with `UB_REQUIRE_INTEGRATION=1` against explicit minimum/current stable refs; expect pass. No broader repeats unless new changes/failures justify them.
- [ ] **Step 5: Verify live settings and Actions dry-runs.** Read main/tag/environment/immutability settings back. Exercise disposable candidate state in mocked/temporary fixtures and actual Actions dry-run. A real test prerelease requires a maintainer-nominated version or an explicitly provided sandbox repository; never create an external repository or publish stable merely for testing.
- [ ] **Step 6: Commit:** `feat: validate and document the release lifecycle`.
- [ ] **Step 7: Push normal implementation PRs and inspect all new trailers.** Attach every created PR to the chat, include checks and configuration evidence, merge only through required protection, and report any unconfigured App/credential prerequisites precisely. The first production candidate/stable publication remains a separate deliberate maintainer dispatch after checks.

## Self-review and requirement coverage

| Spec requirement | Tasks |
|---|---|
| Prepare branch, last fixes, always candidate before stable | 2, 4, 7 |
| Exact SHA/full green CI and separately approved override | 2, 5, 7 |
| Runtime-only archive, vendor/legal files, isolated install/upgrade | 1, 3 |
| Immutable assets, checksums, candidate ZIP promotion | 1, 5, 6 |
| Protected main and automatic merge-back | Prerequisite plan, 8 |
| Dedicated App, trusted workflow origin, no credential fallback | 5, 7 |
| Official issue form, policy drift, truthful evidence, pending issue reuse | 9 |
| Partial failure/retry, versions/races, manual violation detection | 2, 6–10 |
| Complete Linux/Windows verification and maintainer documentation | 3, 10 |

Review and choose an execution method before implementation. Recommended:
subagent-driven, because the policy, publication, credential boundaries, and upstream
issue transitions deserve independent per-task review before they gain write access.
Native execution with one independent final review is the faster alternative.
