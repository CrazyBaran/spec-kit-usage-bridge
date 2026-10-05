# Draft: shared tooling for Spec Kit community extension developers

**Status:** First-pass research and discussion draft; not an approved extraction design or implementation plan.

**Date:** 2026-10-04.

**Code baseline:** `238bed63366064ae1ce1e88e4d8ab6529ef12237` on `feat/release-automation`, submitted in [PR #8](https://github.com/CrazyBaran/spec-kit-usage-bridge/pull/8).

**Proposed audience:** Developers of community extensions, including extensions with different languages, file layouts, release practices, and maintainers.

**Near-term follow-up:** [Draft 2.2: native-tooling alignment](2.2-native-tooling-alignment-draft.md) separates existing overlap from safe changes to this repository before any extraction.

## Initial conclusion

There is a credible separate project here: a developer CLI for validating, packaging, testing, publishing, and verifying Spec Kit extensions, with optional GitHub Actions workflows. Usage Bridge could become its first consumer instead of carrying its complete release toolchain.

The implementation already separates much of the release lifecycle from the installed extension. It does **not** yet separate that lifecycle from Usage Bridge's identity, file layout, security policy, and tests. Extracting it requires more than moving `tools/` into another repository or replacing repository names.

The best first experiment is **release-readiness evidence around native Spec Kit validation, packaging where needed, and isolated installation checks**. Spec Kit already implements substantial validation and a deterministic builder for its distinct `bundle.yml` format; a new project should reuse those capabilities, not create competing implementations. Add optional publication after the experiment works for a genuinely different extension. Keep repository administration, automatic merge-back, and upstream submission out of the minimum adoption path.

## Problem and intended value

Maintainers repeatedly need to answer similar questions:

- Does the manifest agree with the version, commands, configuration files, and packaged files?
- Can someone install the actual distributed archive into a clean Spec Kit project?
- Does the archive omit development files and preserve required runtime data and licenses?
- Do installation and upgrades work on the supported platforms and host versions?
- Are the verified bytes the same bytes that were published or promoted?
- Can a release retry recover safely without changing an existing release?

Shared tooling could make these checks available without copying this repository's Python modules, test fixtures, and workflows. Extension authors would retain their own product tests, publication authority, and release decisions.

The existing [community pipeline survey](pipeline-development-practices.md) is useful demand evidence: its 2026-10-02 snapshot found GitHub Actions workflows in 64 of 171 distinct catalog repositories. This is historical inventory, not proof that the other repositories lack testing or that all maintainers want this tool. The [survey ledger](pipeline-extension-survey.json) can help select pilot consumers; it was not rerun for this draft.

## How large is the existing foundation?

Counts below are physical lines, including comments and blank lines, at the baseline commit. They measure scope, not complexity or extraction effort.

| Surface | Files | Lines | What is included |
|---|---:|---:|---|
| Release and repository tooling | 16 Python files | 3,082 | `tools/release/*.py`, `build_release.py`, `release_cli.py`, `github_api.py`, `repository_policy.py`, `configure_repository.py` |
| GitHub Actions | 8 YAML files | 741 | All current workflows, including ordinary CI and workflow checks |
| Closely related tests and fixtures | 18 Python files | 4,040 | `test_release_*.py`, build/API/repository-policy/configuration tests, `release_fixtures.py`, and release-install integration tests |
| All first-party Python | 54 files | 8,267 | `tools/` and `scripts/python/`, excluding vendored code and caches |

The extraction area is about **37% of first-party Python by physical lines**. It has a substantial regression-test investment. The latest full local run passed 802 tests with three expected skips, but that count covers the entire project, not just the proposed toolkit. Live release workflows and cross-repository reuse have not been demonstrated.

### Reuse assessment by component

| Component | Python lines | Reusable substance | Current extraction barrier |
|---|---:|---|---|
| [GitHub transport](../../tools/github_api.py) and [evidence models](../../tools/release/models.py) | 259 | Bounded API requests, pagination, redaction, binary transfers, evidence records | Attestation predicate and signer workflow are project-specific; transport targets GitHub.com and requires `gh` |
| [Policy](../../tools/release/policy.py), [context](../../tools/release/context.py), [prepare](../../tools/release/prepare.py), [publication](../../tools/release/publication.py), [verification](../../tools/release/verification.py), [merge-back](../../tools/release/mergeback.py) | 811 | Candidate/version decisions, source binding, draft reconciliation, immutable retries, tag resolution, protected PR operations | Import-time policy loading, `main`, branch/tag conventions, asset names, bot identity, required jobs, and release-train assumptions |
| [Archive tooling](../../tools/release/artifacts.py) and [build entrypoint](../../tools/build_release.py) | 352 | Deterministic ZIPs, safe paths, bounds, hashes, catalog construction | Fixed `usage-bridge/` layout, Python entrypoints, pricing data, token-usage vendor pin, legal files, and catalog key |
| [Orchestration](../../tools/release/orchestration.py) and [CLI](../../tools/release_cli.py) | 508 | Command boundaries, evidence collection, JSON outputs, build/verify sequencing | Fixed workflow paths/job names, command evidence, host defaults, artifact names, repository defaults, and local imports |
| [Repository policy](../../tools/repository_policy.py) and [configuration tool](../../tools/configure_repository.py) | 767 | Read/plan/apply/read-back reconciliation | Single-repository safety boundary; solo-maintainer review rules, merge methods, check contexts, environments, and App setup |
| [Catalog submission](../../tools/release/submission.py) | 384 | Evidence-bound issue preparation, policy fingerprints, retry/triage handling | Usage Bridge author/ID/marker/examples; one upstream form and reviewed policy snapshot |
| Package marker | 1 | None of consequence | None |

The first two rows total **1,070 lines, about 35%** of the tooling area. These are the strongest candidates for retaining their algorithms while changing inputs and policy boundaries. Packaging and orchestration add another **860 lines, about 28%**, with more visible product coupling. Administration and submission account for **1,151 lines, about 37%**, and should be optional capabilities.

These percentages describe an architectural grouping, **not a measured percentage of code that can be copied unchanged**. No complete current workflow is a supported drop-in solution for another extension. The genuinely portable pieces are smaller functions and patterns inside these groups.

## What is already decoupled well?

1. **Development tooling is outside the installed runtime.** The archive allowlist excludes `tools/`, tests, workflows, and development documentation. A shared toolkit need not become a dependency of users installing Usage Bridge.
2. **Much of the lifecycle is testable without GitHub.** Modules accept an API client and explicit evidence dictionaries. Tests already cover interrupted publication, stale sources, immutable retries, and candidate-to-stable behavior with real archive bytes and simulated remote responses.
3. **Packaging and verification operate on concrete artifacts.** Paths, file lists, hashes, manifests, metadata, and catalogs provide useful future interfaces.
4. **Workflows already share orchestration.** Candidate and stable releases call the same pipeline; verification and follow-through are separate workflows. This is a useful starting structure, even though current calls and checkout assumptions are local to this repository.
5. **Explicit evidence and policy failures are established.** Failed mandatory checks do not silently turn into release approval. Preserve this property through extraction.

## What must become generic, and what should remain local?

### Manifest and package contract

Read extension identity, version, command files, and host requirements from `extension.yml`. Keep the shared packager language-neutral: another extension may contain Markdown only, JavaScript, shell scripts, Python, or a combination.

The manifest does not necessarily enumerate every runtime resource. Add a small, declarative package contract for additional included files, required files, and excluded development paths. Resolve it against tracked files and keep the current path/link/size protections. Do not infer that every extension needs Usage Bridge's four Python entrypoints, pricing data, or token-usage vendor directory.

For Usage Bridge, vendor-pin checks and report-specific resources remain local requirements expressed through that contract or an isolated product test. Trusted expectations must not be obtained only from the archive being checked.

### Policy loading and repository identity

[`policy.py`](../../tools/release/policy.py) currently reads a repository-relative policy file at import time. [`artifacts.py`](../../tools/release/artifacts.py) also reads the reviewed vendor manifest relative to the tool's own location. These paths would point into the toolkit installation after extraction.

Load and validate consumer policy once at the CLI boundary, from an explicitly selected repository and trusted policy revision. Pass it into the existing functions. Derive asset naming consistently from the validated extension ID. Do not replace the current canonical-repository guard with unrestricted writes: publication still needs an explicit expected repository, and remote evidence must match it.

Keep default branch, release branch/tag conventions, required checks, and supported host/platform matrix as consumer policy where variation is demonstrated. Avoid making every existing constant configurable merely because extraction makes that possible.

### Generic smoke checks versus product behavior

The current [release installation tests](../../tests/integration/test_release_install.py) exercise Usage Bridge's checkpoint, capture, report, and check commands with its transcript fixtures. Those commands are not a Spec Kit-wide testing contract.

A generic harness can create a disposable host project, install the actual archive, inspect declared installed files and command registration, exercise upgrade mechanics, and record results. Product assertions remain in the consumer repository. Running generated agent commands or arbitrary extension scripts requires consumer-specific tests; a generic harness cannot honestly claim every extension's functionality works because installation succeeded.

Consumer tests execute without release or submission credentials. Evidence should bind the archive digest, consumer source SHA, host revision, toolkit version, and actual completed job/run. The current `require_runtime` command list and job-name collector need redesign around this boundary, not cosmetic renaming.

### Optional governance and catalog policy

Do not apply Usage Bridge's solo-maintainer rules to another team. Required reviewers, App ownership, environment approvals, merge-back strategy, and protected branches belong to each repository. A future configuration command should default to inspection and require deliberate application of a chosen policy.

Catalog submission should initially generate a reviewable issue body. Upstream submission is a separate opt-in action, never a side effect of installing the toolkit, validating a bundle, or publishing a candidate. The current upstream guide uses an issue template rather than direct catalog PRs; the toolkit should track that external contract separately from packaging. [Spec Kit publishing guide](https://raw.githubusercontent.com/github/spec-kit/main/extensions/EXTENSION-PUBLISHING-GUIDE.md)

## Upstream overlap and built-in extensions

This section inspects upstream `main` as resolved on 2026-10-04 to **`ae5ade7234be5cb1d975f736c4e06dd46d1326d6`** (commit dated 2026-10-03). Links below pin that revision. These are source findings, not a successful run of upstream CI or a guarantee about older published Spec Kit versions.

### Three different distribution cases

An **extension archive** contains `extension.yml` and one extension's files. A **bundled extension** is an extension shipped inside Spec Kit itself. A **Spec Kit bundle** uses `bundle.yml` to compose extensions, presets, workflows, and steps. These concepts must not share an ambiguous packaging contract. Spec Kit also maintains a separate first-party bundle catalog. [Bundle reference](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/docs/reference/bundles.md)

The inspected [built-in extension catalog](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/extensions/catalog.json) contains five entries, all marked `bundled: true`, owned by `spec-kit-core`, pointing to `github/spec-kit`, and without a standalone `download_url`:

| Extension | Manifest/catalog version |
|---|---|
| `agent-context` | `1.0.2` |
| `assess` | `1.0.1` |
| `bug` | `1.0.0` |
| `git` | `1.0.1` |
| `github` | `1.0.1` |

Hatch's wheel configuration explicitly includes these directories under `specify_cli/core_pack/extensions/`. The host locates that installed copy first and falls back to `extensions/<id>` in a source checkout. They therefore have individual extension versions but ship through the host's package, rather than five independent ZIP releases. `selftest` and `template` directories are fixtures/scaffolding, not additional entries in this catalog. [Package configuration](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/pyproject.toml), [asset lookup](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/src/specify_cli/_assets.py), [version-guard scope](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/.github/scripts/check_extension_version_bump.py)

### What upstream workflows already do

| Workflow or check | Trigger and behavior in inspected source | Implication for extraction |
|---|---|---|
| [Extension Version Guard](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/.github/workflows/extension-version-guard.yml) | Every PR; compares the synthetic merge commit with its first parent. The script requires increased extension versions for changed cataloged extension content and checks catalog/manifest version equality and parseability. | Keep this existing safeguard. Do not introduce a second independent version-bump algorithm. |
| [Tests](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/.github/workflows/test.yml) | PRs and pushes to `main`; Ruff plus pytest on Linux, Windows, and macOS with Python 3.13 and 3.14. | Shared tooling would supplement existing host and extension tests, not supply a missing test system. |
| [Release trigger](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/.github/workflows/release-trigger.yml) | Manual dispatch; prepares the host version/changelog, creates and pushes a tag and release branch, then prepares the next development version and opens a PR. | This is host release orchestration, with a different order and policy from Usage Bridge's candidate-first flow. |
| [GitHub release](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/.github/workflows/release.yml) | `v*` tag pushes; checks for an existing release, generates notes, and creates a GitHub release. | The inspected workflow does not build separate ZIP releases for each bundled extension. |
| [PyPI publication](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/.github/workflows/publish-pypi.yml) | Manual dispatch for a tag; checks tag/package version consistency, builds distributions, then publishes using a separate environment-backed job and OIDC. | Built-in extension payload verification belongs around these host distributions. |
| [Community submission automation](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/.github/workflows/add-community-extension.md) | Source definition reacts to the `extension-submission` issue label, validates submission/archive evidence, and requests a draft PR changing `catalog.community.json` and community documentation. | An upstream catalog-maintenance flow already exists. A toolkit should prepare compatible evidence, not replace it. This is separate from the built-in catalog. |

These event declarations do not prove that one workflow successfully triggers another in production: token event-suppression rules, deployed workflow state, permissions, and environment approvals still need live verification. No release or submission was triggered for this research.

The version guard addresses a real delivery concern: `specify extension update` compares catalog versions with installed versions, so unchanged versions hide changed content. Upstream has contract tests using real bundled extension sources and the real catalog to exercise stale-install upgrades through the local packaged-copy route. Those tests cover more than metadata equality, but do not by themselves prove a freshly built wheel contains the expected payload. [Version guard implementation](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/.github/scripts/check_extension_version_bump.py), [update-delivery tests](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/tests/contract/test_bundled_extension_update_delivery.py)

### Capabilities that should be reused

| Existing native capability | Scope and limitation | Proposed toolkit response |
|---|---|---|
| Extension manifest validation and installation management | Checks schema, metadata, versions, declarations, compatibility, and command conflicts in the host's extension machinery. | Exercise a pinned host's public installation/update commands. Avoid copying its schema validator into a separately evolving implementation. [Extension implementation](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/src/specify_cli/extensions/__init__.py) |
| Archive/update preflight | Safe extraction, manifest identity/version matching, compatibility and conflict checks precede the update transaction. | Preserve host checks; add release-source/digest evidence around the actual tested bytes. Internal helper imports would create a host-version coupling and need explicit compatibility tests. [Update preflight](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/src/specify_cli/extensions/_command_update_artifacts.py) |
| `specify bundle validate` | Validates `bundle.yml` structure and component references; offers offline validation against available bundled/installed components. | Call this for actual Spec Kit bundles. It is not an `extension.yml` validator. [Command](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/src/specify_cli/bundles/command_validate.py) |
| `specify bundle build` | Builds a versioned ZIP with fixed timestamps, normalized permissions, sorted files and source-path confinement; rejects structurally invalid manifests. Build alone does not invoke the validator's optional reference resolver. | Reuse the builder for `bundle.yml`; run reference validation and installation separately. Do not rewrite deterministic bundle packaging. [Packager](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/src/specify_cli/bundles/packager.py), [validator](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/src/specify_cli/bundles/validator.py) |
| Community catalog intake | Downloads submitted artifacts, checks submitted hashes when provided, records the computed hash, validates catalog data and prepares a draft PR. | Generate submission evidence only when requested; leave acceptance and catalog changes upstream. [Submission workflow definition](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/.github/workflows/add-community-extension.md) |

No public `specify extension build` or `specify extension validate` command is registered in the inspected [extension command module](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/src/specify_cli/extensions/_commands.py). This is a narrower gap than “Spec Kit has no developer tooling.” A small native upstream command could be preferable to extracting a duplicate validator. Internal Python classes are not automatically a supported public library API.

The remaining potential value is **artifact-to-source binding, reproducible extension-specific packaging, clean installed-artifact tests, evidence collection, and optional candidate/promotion/retry assurance**. The inspected commands and release workflows do not expose Usage Bridge's complete evidence-bound candidate-to-stable lifecycle. This is not a claim that every upstream security or release facility was exhaustively audited.

The inspected upstream package requires Python **3.11 or newer**. A wrapper must select a compatible host environment and pin the host revision; it must not assume Usage Bridge's Python 3.9 runtime floor applies to the developer tool or that upstream `main` features exist in the project's currently pinned host release. [Python requirement](https://github.com/github/spec-kit/blob/ae5ade7234be5cb1d975f736c4e06dd46d1326d6/pyproject.toml)

### Could built-in extensions use the tooling?

**Yes, for shared checks and evidence; not by adopting the standalone extension release workflow unchanged.** The built-in case is a monorepo consumer with several extension roots and a host-owned publication boundary.

| Concern | Community extension repository | Built-in extension in `github/spec-kit` |
|---|---|---|
| Source and identity | Usually one root `extension.yml` | Repository root plus `extensions/<id>/extension.yml`; enumerate actual catalog entries |
| Version coordination | Extension version, archive and external catalog | Per-extension version, built-in catalog, and independently versioned host distribution |
| Artifact under test | The extension's release ZIP | Built host wheel and source distribution, with the wheel's actual `core_pack/extensions/<id>` contents checked |
| Installation evidence | Clean install and upgrade from the distributed ZIP | Install the built host wheel outside its source checkout, then add/update each bundled extension; source fallback must not hide missing packaged files |
| Publication | Optional independent candidate/stable releases | Existing Spec Kit host release and PyPI workflow; no new per-extension tags or releases by default |
| Catalog delivery | Explicit community submission when needed | Built-in catalog change reviewed in the same upstream PR; no community submission issue |

A useful built-in pilot would inspect one Markdown-oriented extension and one extension with script assets, then expand to all five catalog entries. Build the host distributions in an unprivileged job, verify catalog/manifest/payload agreement, and exercise fresh and stale installs from the built wheel in a disposable environment. Include a missing packaged-command negative case to prove that source-checkout fallback cannot produce a false pass. Reuse the existing version guard and update-delivery tests; investigate current wheel tests before adding overlapping coverage.

Keep extension version, host package version, and toolkit revision separate in evidence. Bind any eventual release evidence to the host distribution digest and source SHA, with individual extension payload details where useful. Do not apply ZIP-specific promotion assumptions or Usage Bridge's repository policy to host wheels. Publication and approvals remain upstream-owned.

Start with explicit repository/artifact paths and the native commands. Only introduce a separate built-in release profile after a pilot demonstrates a need; no plugin framework is justified yet. Incorporation could be a small upstream CI check or native CLI improvement rather than adoption of an external release framework. It requires upstream maintainer agreement, which this draft does not presume.

## How could other repositories consume it?

| Delivery option | Benefit | Cost or limitation | Initial position |
|---|---|---|---|
| Copy a starter template | Fastest onboarding; all code visible locally | Fixes diverge across copies; every consumer maintains the toolchain | Use for thin configuration/workflow examples only |
| Versioned Python CLI package | Same behavior locally and in any CI; direct unit testing; explicit upgrades | Requires package/CLI/schema compatibility and developer-side Python distribution | Recommended shared core |
| SHA-pinned reusable GitHub workflows | Share matrices and multi-job artifact/evidence flow | Cross-repository identity, secrets, checkout, and job evidence need explicit design | Add after the CLI works for two different extensions |
| Small composite action around the CLI | Convenient setup/invocation inside an existing job | Does not replace the multi-job lifecycle or credential isolation | Optional convenience, not the core architecture |
| Hosted service or centrally installed GitHub App | Could reduce per-repository configuration | Adds service operation, credential custody, tenant isolation, and support obligations | Exclude from the first project |

GitHub reusable workflows share complete jobs; composite actions share steps within a job. A reusable workflow's default checkout checks out the **calling repository**, not the repository containing the shared workflow. Moving the YAML alone therefore will not make `tools/release_cli.py` available. Install the toolkit explicitly or check out its reviewed revision separately from consumer source. [GitHub reuse concepts](https://docs.github.com/en/actions/concepts/workflows-and-actions/reusing-workflow-configurations)

The CLI could initially be installed from a pinned toolkit Git commit, then distributed as a versioned package once the interface settles. `uvx --from` supports exact package versions and Git commit sources, making it a plausible developer entrypoint. For publication CI, choose and document artifact integrity and dependency locking as well; a version pin alone is not the entire supply-chain policy. No package name has been reserved or published. [uv tools guide](https://docs.astral.sh/uv/guides/tools/)

A Spec Kit extension exposing convenient developer commands could wrap this CLI later. It should not be the only distribution channel: maintainers need to validate archives before their extension is installed, and CI needs deterministic commands without an agent session.

## Proposed consumer experience

This is a proposed flow, not an implemented CLI or configuration schema:

1. Add a pinned development-tool dependency and a small declarative packaging/test policy. Existing `extension.yml` remains the identity source.
2. Run local validation and build commands; inspect the resulting archive, catalog entry, checksums, and machine-readable results.
3. Add a thin PR workflow using the same CLI and a pinned Spec Kit host. No release credentials are needed.
4. Add consumer-owned behavioral tests for the installed archive. Use the generic harness for setup and evidence, not for invented product assertions.
5. Optionally adopt the candidate/publication workflow with that repository's explicit credentials and approval settings.
6. Upgrade the toolkit through a reviewed dependency/workflow-pin change. Run compatibility tests before adopting the new version; rollback means restoring a known pin, not modifying existing releases.

Recommended ownership boundary:

```text
Shared toolkit repository
  Versioned CLI, pinned native-tool invocation, extension archive support, evidence formats
  Optional reusable workflows, regression fixtures, compatibility tests

Consumer extension repository
  extension.yml, package policy, behavioral tests, thin workflow calls
  Release credentials, approvals, required checks, release decisions

Installed extension archive
  Only that extension's declared runtime files and required legal material
```

## Cross-repository trust is the difficult part

The current [attestation verifier](../../tools/github_api.py) trusts a Usage Bridge predicate URI, the consumer's `release-pipeline.yml`, and `refs/heads/main`. A shared workflow can change the signer identity and relationship between caller source, toolkit source, and workflow source. The extracted verifier must bind all three correctly. Do not loosen signer checks until a live cross-repository experiment establishes the exact attestation fields and verification arguments.

Likewise, current job collection recognizes specific workflow paths and job names. Nested reusable workflows and consumer-specific matrices require an explicit evidence contract; accepting an arbitrary uploaded JSON success flag would weaken the existing checks.

Consumer policy used for privileged operations should come from a reviewed revision. Do not execute consumer-provided build/test hooks in jobs carrying publication credentials. Start with credential-free validation and leave privileged jobs consumer-owned until the shared boundary is demonstrated.

Environment secrets have special behavior in reusable workflows; they are not ordinary `workflow_call` inputs. Secret inheritance also has organization/enterprise restrictions, so the current `secrets: inherit` wiring is not a universal onboarding mechanism for unrelated community repositories. Design and test explicit secret/environment wiring. [GitHub reusable workflow inputs and secrets](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)

## Smallest useful extraction experiment

**Phase 0 — prove the source implementation.** Finish reviewing the current release work and exercise its real candidate lifecycle. Local tests are strong evidence, but they do not prove App permissions, live attestations, or hosted workflow behavior.

**Phase 1 — prove two consumers without publishing.** First map the native capabilities available in the supported host releases. Wrap native validation/installation and bundle building where applicable; extract only missing extension packaging and release-evidence checks into a small installable CLI. Keep Usage Bridge working through a thin invocation layer. Add a second, differently named extension with a different layout, preferably Markdown-only or a different runtime language. Use a local fixture first, then a consenting real maintainer's repository. No special case for its repository name should be necessary. Separately use a pinned Spec Kit checkout as a read-only built-in-extension pilot; this tests monorepo/wheel assumptions without committing to a second release framework.

**Phase 2 — share CI.** Deliver a pinned validation/install workflow. Test calls across repository owners, Linux and Windows, explicit minimum/current host revisions, and tool upgrades. At the local baseline both host channels used `v1.0.12`; the 2.2 alignment changes select `v1.0.12` for minimum and `v1.1.0` for current. A cross-repository pilot must demonstrate that distinct-version evidence survives shared workflow adoption.

**Phase 3 — consider privileged features.** Extract candidate publication and promotion only after live signer/evidence/credential boundaries are understood. Keep repository administration, merge-back, and catalog issue submission opt-in. A successful validation-only product does not need all of these to launch.

Pilot acceptance evidence:

- Both extension repositories consume the same toolkit revision without copying its source.
- Valid extension archives install; omitted command/resource files, escaping paths, tampering, stale source evidence, and inappropriate publication credentials are rejected. Actual `bundle.yml` artifacts use the native builder and validator.
- Usage Bridge's output and runtime regressions still pass; the second extension's own behavior is tested independently.
- Developer tooling never appears in either installed archive.
- Consumer policies and test failures stay isolated; one project's settings cannot authorize another project's release.
- A toolkit upgrade and rollback are reproducible, with documented CLI and metadata compatibility.

## Questions to settle before an implementation plan

1. Is the initial audience GitHub-hosted extensions only, or should local validation support any Git host from day one? Recommendation: portable local CLI, GitHub-only publishing initially.
2. Which real second extension and maintainer will test the assumptions? Synthetic fixtures cannot establish adoption value alone.
3. Which packaging rules are universal Spec Kit requirements, and which are optional strict defaults? Verify against the supported host rather than treating Usage Bridge's allowlist as the standard.
4. Should candidate-first releases be a recommended profile or a requirement? Recommendation: optional adoption of the release lifecycle; never silently weaken it once selected.
5. Who owns toolkit releases, security fixes, host-version support, and upstream catalog-policy updates?
6. What command and evidence formats need a compatibility promise, and how long should old consumers remain supported?

## Evidence limits and next decision

This draft combines local source inspection at the stated baseline, measured file sizes, the existing community survey, official documentation, and pinned upstream source inspection. It is not a completed dependency analysis, current census of competing tools, effort estimate, or proof of cross-repository operation. Upstream code was read, not executed; upstream CI state, release delivery and wheel payload correctness were not verified. General documentation links outside the pinned upstream section may move; implementation should record reviewed revisions where behavior or policy depends on them.

The decision worth making next is whether to fund the **two-consumer validation/packaging pilot**. It would test the central claim with a small scope: common tooling can replace duplicated repository machinery while each extension keeps its own behavior, trust decisions, and release authority.
