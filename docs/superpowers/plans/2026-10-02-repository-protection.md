# Repository Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent direct pushes to main and permit automated PR merging only after the existing required CI passes.

**Architecture:** Keep desired settings in a small tested policy builder, apply only owned settings through authenticated GitHub APIs, and verify the effective rules by reading them back. A shared API adapter supports this standalone configuration task and the release plan without duplicating authentication or pagination logic.

**Tech Stack:** Python 3.9-compatible development tools, pytest, GitHub CLI authentication, GitHub REST API, repository rulesets.

**Spec:** [Release automation design, sections 6–7](../specs/2026-10-02-release-automation-design.md). Companion: [release implementation plan](2026-10-02-release-automation.md).

**Status:** Planning requested on 2026-10-02; implementation-plan review and execution-method selection pending.

## Global Constraints

- Require a pull request for all updates; no direct human or automation pushes.
- Block force pushes and branch deletion.
- Require resolution of review conversations, but zero mandatory approving reviewers so the sole maintainer can merge their own passing PRs.
- Apply an active main ruleset with no bypass actors.
- Require the branch to be current with main and all seven existing GitHub Actions contexts listed below.
- Preserve unrelated existing settings. Workflow changes themselves arrive through a PR after protection is enabled.
- Keep the human's configured Git author and committer; every Codex-created commit includes exactly one blank-line-separated `Co-authored-by: Codex <codex@openai.com>` trailer.
- Never stage the existing untracked `docs/references/architecture-and-python-practices.md` as part of this work.
- Perform no remote setting mutation while writing this plan. Implement only after plan approval.

## Review Focus

1. A stricter existing main rule appears before execution: preserve it and stop on incompatible requirements instead of weakening protection (Task 2).
2. CI names match but come from another integration: bind required contexts to the observed GitHub Actions App (Task 2).
3. A paginated rules/checks response hides an existing setting: enumerate all pages before deciding to create or replace anything (Task 1).
4. Partial configuration writes succeed before a later API failure: report exactly what changed and retry idempotently; never claim success from a successful HTTP write alone (Task 3).
5. Solo-maintainer merging or release ancestry is accidentally blocked: zero reviewer requirement, strict checks, and merge commits remain usable (Tasks 2–3).

---

## Files and boundaries

| File | Responsibility |
|---|---|
| `tools/github_api.py` (new) | Bounded structured GitHub CLI API transport and pagination |
| `tools/repository_policy.py` (new) | Desired main rules, conflict detection, semantic read-back comparisons |
| `tools/configure_repository.py` (new) | Inspect/dry-run/apply/report orchestration |
| `tests/test_github_api.py`, `tests/test_repository_policy.py`, `tests/test_configure_repository.py` (new) | Transport faults, protective policy, idempotent configuration |
| `docs/repository-maintenance.md` (new) | Applied settings, maintainer usage, known owner-authority limit |

## Verification and commits

Use the repository virtual environment: `.venv/Scripts/python.exe -m pytest` on
Windows, `.venv/bin/python -m pytest` on Linux. Below, `python` means that interpreter.
Use isolated pytest homes from `tests/conftest.py`; no tests access real credentials.
Each task performs red/green verification and commits only its named files.

Commit form: `git commit -m '<task message>' -m 'Co-authored-by: Codex <codex@openai.com>'`.
Inspect author, committer, and trailer before pushing. Do not change global Git
identity or safe-directory settings; use a command-scoped safe-directory exception
if this Windows sandbox needs it.

### Task 1: Reusable API transport

**Files:** Create `tools/github_api.py`, `tests/test_github_api.py`.

**Interfaces:** Produce `GitHubAPI.request(method: str, path: str, payload: dict | None = None) -> dict | list | None` and `GitHubAPI.pages(path: str) -> list[dict]`; constructor accepts an injected subprocess runner for tests. Produce `GitHubAPIError` with HTTP status and redacted diagnostics. Authenticate through the caller's `GH_TOKEN` or existing gh sign-in; never read/export the token in application code.

- [ ] **Step 1: Write failing transport tests.** Assert `test_request_uses_structured_body` sends a JSON file through `gh api --input`, preserves literal backticks/newlines, and never constructs a shell command; `test_pages_collects_every_page` returns all 101 fixture records; `test_403_and_429_are_not_empty_success` raises `GitHubAPIError`; `test_diagnostics_redact_token` excludes the injected credential.
```python
def test_403_is_not_empty_success(denied_runner):
    api = GitHubAPI(runner=denied_runner)
    with pytest.raises(GitHubAPIError):
        api.request('GET', 'repos/CrazyBaran/spec-kit-usage-bridge/rulesets')
```

Create `denied_runner` in this test file as an injected subprocess callable that
returns gh's nonzero exit and a fixture HTTP 403 response; it never invokes gh.

- [ ] **Step 2: Run `python -m pytest tests/test_github_api.py -q`.** Expect failure because the module/API does not exist.

- [ ] **Step 3: Implement the interfaces.** Use argv lists, `shell=False`, temporary UTF-8 JSON files, 60-second subprocess deadlines, bounded output, and GitHub's documented REST API version. Retry bounded transient/rate-limit reads; do not blindly retry non-idempotent writes after an unknown result. Return `None` for successful empty responses.
- [ ] **Step 4: Run the same tests.** Expect all pass; offline tests assert no outbound command escapes their injected runner.
- [ ] **Step 5: Commit.** Message: `feat: add bounded GitHub API transport`.

### Task 2: Exact main policy and safe reconciliation

**Files:** Create `tools/repository_policy.py`, `tests/test_repository_policy.py`.

**Interfaces:** Consume `GitHubAPI`. Produce `main_ruleset(actions_app_id: int) -> dict`, `plan_main_updates(existing: dict, actions_app_id: int) -> list[dict]`, and `verify_main_policy(observed: dict, expected: dict) -> list[str]`. Each planned operation has `method`, `path`, and `payload`; comparison ignores server IDs/timestamps but not rule parameters. `existing` contains repository settings, all applicable rulesets, effective main rules, and recent main check runs.

- [ ] **Step 1: Write policy tests**, including:

```python
def test_main_requires_pr_and_has_no_bypass():
    policy = main_ruleset(actions_app_id=15368)
    assert policy['enforcement'] == 'active'
    assert policy['bypass_actors'] == []
    assert policy['conditions']['ref_name']['include'] == ['refs/heads/main']
    rules = {r['type']: r for r in policy['rules']}
    assert rules['pull_request']['parameters']['required_approving_review_count'] == 0
    assert rules['required_status_checks']['parameters']['strict_required_status_checks_policy'] is True
    assert 'deletion' in rules and 'non_fast_forward' in rules
```

Also assert `test_required_contexts_bound_to_actions` contains exactly `lint`,
`test (ubuntu-latest, 3.9)`, `test (ubuntu-latest, 3.x)`,
`test (windows-latest, 3.9)`, `test (windows-latest, 3.x)`,
`integration (ubuntu-latest)`, `integration (windows-latest)` with the supplied
integration ID; `test_stricter_existing_policy_is_preserved` creates no weakening
operation; `test_missing_or_ambiguous_actions_checks_blocks_apply` refuses guessed
IDs; `test_merge_commit_compatible_policy` does not require linear history.

- [ ] **Step 2: Run `python -m pytest tests/test_repository_policy.py -q`.** Expect missing-module failure.
- [ ] **Step 3: Implement the interfaces.** Own only ruleset `usage-bridge-main`; require review-thread resolution and strict checks. Enable `allow_auto_merge` and `allow_merge_commit` through a narrow repository PATCH. Do not set unrelated repository fields or delete other rulesets. Detect stricter/incompatible inherited rules rather than overriding them.
- [ ] **Step 4: Run the same tests.** Expect pass; include serialization against documented ruleset parameter names.
- [ ] **Step 5: Commit.** Message: `feat: define protected main policy`.

### Task 3: Apply authorized main configuration and verify

**Files:** Create `tools/configure_repository.py`, `tests/test_configure_repository.py`, `docs/repository-maintenance.md`.

**Interfaces:** Consume Tasks 1–2. Produce `configure_main(api: GitHubAPI, repository: str, apply: bool) -> dict`; result contains `planned`, `applied`, `verified`, `errors`, with no credentials. CLI: `python tools/configure_repository.py main --repo CrazyBaran/spec-kit-usage-bridge [--apply]`; inspection is the default. Permit mutation only of this explicitly named repository.

- [ ] **Step 1: Write failing tests.** `test_dry_run_has_no_writes` asserts zero POST/PUT/PATCH; `test_apply_verifies_effective_rules` asserts rules are read back; `test_retry_updates_owned_rule_without_duplicate` asserts one owned ruleset; `test_partial_failure_reports_prior_writes` retains applied operations and reports `verified=False`; `test_wrong_repository_is_refused` makes no writes for `github/spec-kit`.
```python
def test_dry_run_has_no_writes(fake_api):
    report = configure_main(fake_api, 'CrazyBaran/spec-kit-usage-bridge', apply=False)
    assert report['applied'] == []
    assert all(call.method == 'GET' for call in fake_api.calls)
```

Define `fake_api` in this test file with paginated settings/check fixtures and a
`calls` collection; each recorded call carries method/path/payload.

- [ ] **Step 2: Run `python -m pytest tests/test_configure_repository.py -q`.** Expect missing entrypoint/interface failures.

- [ ] **Step 3: Implement inspect/apply/report and document usage.** Record a redacted before/after report under ignored local build output. Require explicit `--apply`, admin authority, matching main/default branch, and discovered check source. Treat a 403 or unsupported rule as a blocker, not success. Do not remove protections automatically to recover an error.
- [ ] **Step 4: Run `python -m pytest tests/test_github_api.py tests/test_repository_policy.py tests/test_configure_repository.py -q` and `python -m ruff check tools tests`.** Expect pass.
- [ ] **Step 5: Run the CLI without `--apply` and inspect its exact proposed changes.** Expect seven discovered contexts and no bypass. Recheck live settings; the research snapshot is not a current-state guarantee.
- [ ] **Step 6: Apply the user's already requested main protection with `--apply`.** Read repository settings, owned ruleset, and `/repos/CrazyBaran/spec-kit-usage-bridge/rules/branches/main` back; expect PR requirement, strict seven checks, no bypass, force-push/deletion blocks, and auto-merge enabled. If effective inherited rules conflict, report them before any weakening.
- [ ] **Step 7: Verify the effective PR/merge behavior using normal implementation PRs.** Do not push a sacrificial commit directly to main. Link configuration evidence and document the administrator's ability to change settings.
- [ ] **Step 8: Commit.** Message: `feat: configure and verify main protection`; include documentation, not ignored machine reports. Push/open this tooling PR with attribution checked and attach the PR to the chat. Normal main requirements govern merging; no bypass.

## Completion boundary

This plan is complete when main protection is effective and its management tooling
has passed tests and normal PR review. It does not configure release secrets,
publish releases, modify the Spec Kit fork, or submit upstream issues. Proceed to
the companion release plan after this policy is in place.
