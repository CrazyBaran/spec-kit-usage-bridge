# Usage Bridge pipeline development: research and references

Research date: **2026-10-02**. Purpose: inform the proposed Usage Bridge release
lifecycle and everyday repository maintenance. Recommendations apply to this
repository, not to projects installing the extension.

## Scope and evidence

The survey covered **all 176 entries in the official community extension catalog**,
representing **171 distinct GitHub repositories**, plus upstream `github/spec-kit`
and the other three public repositories under the `speckit-community` account.
Its fourth repository, `spec-kit-fixit`, was already in the catalog. That makes
**175 distinct repositories** in total. Every queried tree was accessible and none
reported truncation. This covers the catalog as inspected, not every unlisted
extension on GitHub.

Of the catalog repositories, **64 had GitHub Actions workflow files** and **107
had none at the surveyed default-branch tree**. The former contained **150 YAML
workflow files**. Absence of such files does not establish absence of tests,
manual releases, external CI, or maintenance.

Fetched **368 workflow and maintenance documents** across the survey, then another
ten upstream manifests/version-guard/index/form documents: **378 successful reads**.
The initial reads include workflow Markdown, generated workflow YAML, dependency
update configuration, security/contribution policies, CODEOWNERS, extension ignore
files, and community index documentation. Automated content scans identified
patterns; selected workflows received detailed review below. This is an exhaustive
repository/workflow inventory with selective deeper analysis, not a full code or
security audit of every extension. No remote code was executed, and no example's
CI success, release provenance, or repository protection was independently proved.

The machine-readable [survey ledger](pipeline-extension-survey.json) records every
repository, extension IDs, observed tree SHA, workflow paths, inspected document
URLs, and hashes of fetched text. Tree SHAs identify file-tree snapshots, not
commit SHAs. Default branches can move during a live survey; fetched document
hashes identify what was read and do not prove all reads form one atomic snapshot.
The upstream commit observed during research was
`838f1184d1b2ed254a99e8b818dbc23aa80a7f1f`.

Repository examples show maintainer intent and concrete execution wiring. GitHub
documentation establishes platform behavior; tool documentation explains supported
checks; original articles explain principles. Recommendations and priorities are
project-specific judgments, not conclusions that popular projects are necessarily
secure. Summaries are paraphrased and links were inspected during research.

## Recommended additions to the release design

These are proposed amendments, not implemented settings or approved scope changes.
The current [release design](../superpowers/specs/2026-10-02-release-automation-design.md)
already covers candidate-first promotion, exact-source validation, approvals,
minimal packaging, checksums, main protection, and official submission issues.

| Priority | Addition | Why it helps Usage Bridge | Evidence |
|---|---|---|---|
| Include in release work | Deterministic ZIP construction | Same commit and packaging inputs produce the same runtime ZIP digest, including across retries | R1, G10 |
| Include in release work | Draft, upload, verify, then publish an immutable release | Avoid publicly exposing a partial release and lock published assets and tags | G1 |
| Include in release work | Attest the exact runtime ZIP and verify its provenance | Associate the downloadable artifact with its source/workflow, beyond a plain checksum | R5, G2 |
| Include in release work | Archive installation against minimum and current stable Spec Kit | Detect packaging omissions and host compatibility failures before promotion | R2, R3 |
| Include in release work | actionlint and zizmor checks | Validate Actions syntax/wiring and identify security weaknesses in the new workflows | R5, G5, G6 |
| Include in release work | Locked, hashed development dependencies and pinned action commits | Reduce surprise changes in CI and publishing tooling | R4, U2, G3, G7 |
| Include in release work | Explicit timeouts and retained failure evidence | A stuck job cannot consume resources indefinitely; release failures remain diagnosable | R1, R5, G12 |
| Include in release work | One tested release-policy module called by thin workflows | Test refused publication, retries, version races, and approval handling without making real releases | R2, A1 |
| Separate maintenance PR | Stable aggregate required check | Matrix evolution does not require constantly renaming branch-protection contexts | R4, G8 |
| Separate maintenance PR | Dependency updates and recurring security audits | Newly disclosed vulnerabilities matter even when repository code has not changed | R4, U2, G7, G9 |
| Separate maintenance PR | Scheduled host compatibility/policy checks with PRs for updates | Discover upstream changes early without directly modifying main | C1, C2 |

## What extension maintainers actually use

### R1. Dotdog: deterministic packaging and verification of a real release

`specdog/dotdog` stages a selected extension surface, normalizes timestamps, sorts
files, removes ZIP extra fields, emits a checksum, and refuses replacement of an
existing release. Its separate verification workflow downloads the published ZIP
and checksum, installs through Spec Kit, and checks the installed file set.

Adopt those principles with our stricter runtime-only file list. Do not copy its
README/changelog payload or hard-coded verification version. It checks a current
upstream main checkout; our release gate should resolve current stable to an exact
tag/SHA, leaving moving-main testing to an optional compatibility probe. Checking
a checksum downloaded beside the ZIP establishes consistency, not independent
publisher identity; pair it with immutable publication and verified provenance.

Sources: [packaging workflow](https://github.com/specdog/dotdog/blob/main/.github/workflows/spec-kit-extension-release.yml),
[published release verification](https://github.com/specdog/dotdog/blob/main/.github/workflows/verify-spec-kit-extension-release.yml).

### R2. Jira Mirror: publication contracts outside YAML

`Fyloss/spec-kit-jira-mirror` delegates building, completeness/purity checks, and
publication to repository scripts. Publication is blocked by artifact validation.
Its install workflow builds the real archive, serves it locally, and checks a
pristine consumer against both the declared minimum host and a current host. It
also compares the installed surface and verifies lifecycle event registration.

Adopt the separation of packaging policy from Actions plumbing. Extend our current
ZIP integration test from manifest existence to command execution, data loading,
hook registration, and configuration preservation. Keep the minimum Spec Kit
version derived from the manifest; resolve the current stable host once per run.
Our override must never waive packaging completeness or isolated installation.

Sources: [release](https://github.com/Fyloss/spec-kit-jira-mirror/blob/main/.github/workflows/release.yml),
[consumer installation tests](https://github.com/Fyloss/spec-kit-jira-mirror/blob/main/.github/workflows/install-e2e.yml).

### R3. Repository Governance: explicit required and forbidden archive members

`bigsmartben/spec-kit-agent-governance` verifies required archive entries and
rejects development-only files. Its artifact workflow also checks versions and
source/tag agreement for manually requested integration work.

Use a positive allowlist and assert the exact installed runtime surface. Do not
copy its development-checkout smoke as a substitute for installing the built ZIP,
its asset replacement behavior, or its integration PR automation targeting the
maintainer's own Spec Kit fork. Those choices do not meet this repository's
immutable-release and official issue-submission requirements.

Source: [extension artifact workflow](https://github.com/bigsmartben/spec-kit-agent-governance/blob/main/.github/workflows/extension-artifact.yml).

### R4. AEE: preserved aggregate check and hashed dependency installation

`electrohire/spec-kit-aee` runs a Linux/Windows Python matrix, installs hashed
development requirements, pins actions to full SHAs, and keeps one `validate` job
whose result depends on every matrix job succeeding. It also uses dependency
review and a scheduled OpenSSF Scorecard workflow.

An aggregate `CI / required` gate would simplify future Python/matrix changes.
It must run despite prerequisite failures and explicitly reject any result other
than success; a skipped dependency must not turn a green aggregator into a bypass.
Install the new gate, prove its failure behavior, and then migrate protection
settings. Scorecard findings inform review rather than supply a universal release
score; its own configuration shows narrowly scoped job permissions.

Sources: [test matrix and aggregate gate](https://github.com/electrohire/spec-kit-aee/blob/main/.github/workflows/test.yml),
[dependency review](https://github.com/electrohire/spec-kit-aee/blob/main/.github/workflows/dependency-review.yml),
[Scorecard](https://github.com/electrohire/spec-kit-aee/blob/main/.github/workflows/scorecard.yml).

### R5. Schedule: workflow linting, asset checks, and artifact attestations

`jfranc38/spec-kit-schedule` checks tag/manifest agreement, verifies archive assets,
and generates build provenance attestations. CI includes actionlint, shellcheck,
ZIP installation, license reporting, security auditing, and benchmark artifacts.

Adopt workflow linting and verified ZIP provenance. Treat its warn-only security
audit and conditionally omitted attestation as example-specific choices, not our
default gate. Do not copy whole-repository `git archive` packaging. Our ZIP remains
minimal, and a required provenance job must not silently disappear when prerequisites
are missing. Coverage percentages and performance limits should be based on actual
Usage Bridge risks and measurements, not another extension's numeric thresholds.

Sources: [CI](https://github.com/jfranc38/spec-kit-schedule/blob/main/.github/workflows/ci.yml),
[release](https://github.com/jfranc38/spec-kit-schedule/blob/main/.github/workflows/release.yml).

### R6. ADRKit: installed artifacts and trusted policy checks

`mbeacom/adrkit` packs artifacts and smoke-tests installed packages on multiple
runtimes. Its trusted-gates workflow reads policy from the default branch and
inspects PR metadata/commit objects without executing PR code. This addresses the
problem that a PR can modify a workflow and the check it uses to certify itself.

Adopt clean installed-artifact tests and explicit review of changes to `.github/`,
packaging, and approval policy. A separate trusted metadata gate could be useful
later, but do not copy its DCO requirement, multi-package release system, or
privileged event without a specific need. GitHub's current event-policy guidance
must be checked before using `pull_request_target`; the documented default policy
has an enforcement transition on November 2, 2026. Ordinary PR tests need no such
privileged event.

Sources: [release smoke checks](https://github.com/mbeacom/adrkit/blob/main/.github/workflows/release.yml),
[trusted gates](https://github.com/mbeacom/adrkit/blob/main/.github/workflows/trusted-gates.yml),
[GitHub event guidance](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target).

### R7. DocGuard: exact-run auto-merge and recoverable publishing

`raccioly/docguard` separates version detection, validation, and publication. Its
bot auto-merge workflow checks the current PR head against the completed CI run,
evaluates expected job results, and applies different policies to bot changes.
Trusted policy code comes from the default branch rather than the PR. A scheduled
release workflow prepares release changes through PRs and includes recovery for an
unpublished version.

Use native auto-merge for our release PR, tied to required checks. For future
dependency auto-merge, allow only explicitly selected update types and recheck the
current head; major updates and workflow/security changes deserve review. Preserve
separate recovery for publication, submission, and merge-back. Its catalog workflow
prepares a local reminder and submission data; this is a useful fallback if an
upstream credential or human attestation is unavailable.

Sources: [auto-merge policy](https://github.com/raccioly/docguard/blob/main/.github/workflows/auto-merge.yml),
[release](https://github.com/raccioly/docguard/blob/main/.github/workflows/release.yml),
[scheduled release](https://github.com/raccioly/docguard/blob/main/.github/workflows/scheduled-release.yml),
[submission preparation](https://github.com/raccioly/docguard/blob/main/.github/workflows/sync-speckit-catalog.yml).

### R8. Squad and Roadmap: two issue-submission patterns

`jwill824/spec-kit-squad` creates a structured upstream submission issue after
publication using a separate credential and reports the issue URL. It closes
older submissions first. `srobroek/speckit-roadmap` uses release-please for release
PRs and creates a local reminder with submission metadata, leaving human checklist
claims to the maintainer.

Keep our selected automatic submission after evidence approval, with a local
prepared-body fallback. Do not close submissions indiscriminately: an upstream
maintainer may already be reviewing a generated PR. Reuse only clearly identified,
untriaged issues and freeze versions once validation starts. Release-please is
useful for maintaining release notes/version PRs, but its standard publication
path is not a drop-in replacement for our mandatory candidate/promotion flow.

Sources: [Squad issue submission](https://github.com/jwill824/spec-kit-squad/blob/main/.github/workflows/catalog-submit.yml),
[Roadmap release/reminder](https://github.com/srobroek/speckit-roadmap/blob/main/.github/workflows/release-please.yml),
[release-please documentation](https://github.com/googleapis/release-please).

## Upstream Spec Kit practices

### U1. Split release responsibilities and enforce extension versions

Spec Kit documents separate version preparation, GitHub publication, and package
publication, allowing failures to be recovered independently. Its extension
version guard detects changed bundled extension content without a version increase
and mismatches between catalog and manifest versions. This matters because update
discovery is version-driven.

For Usage Bridge, validate stable tag, manifest, catalog, and changelog agreement
in one testable release check. Keep development version policy compatible with
final fixes on release branches: do not require a fresh stable version bump for
every candidate fix. Preserve independent recovery of our ZIP publication,
submission, and merge-back. Upstream's own release flow does not establish our
candidate-first requirement; maintain it explicitly.

Sources: [release process](https://github.com/github/spec-kit/blob/main/.github/workflows/RELEASE-PROCESS.md),
[version guard](https://github.com/github/spec-kit/blob/main/.github/scripts/check_extension_version_bump.py),
[version workflow](https://github.com/github/spec-kit/blob/main/.github/workflows/extension-version-guard.yml).

The inspected upstream tree contained seven extension manifest directories:
`agent-context`, `assess`, `bug`, `git`, `github`, `selftest`, and `template`.
The last two are a testing utility/scaffold rather than normal catalog-managed
extensions. The manifest reads and version-guard source are in the survey ledger.
This is separate from the 176 community entries; do not count them as additional
community repositories.

### U2. Pin tools and separate deterministic PR audits from recurring audits

Upstream pins actions to full commit SHAs. Its security workflow checks a committed
hashed requirements snapshot for PR/push runs, then performs scheduled live
resolution across operating systems and Python versions. This balances stable
review results against detection of newly disclosed or platform-specific risks.

Adopt a compatible locked/hash-pinned development tool set, reviewed updates, and
recurring audits. Usage Bridge's vendored runtime is not fully represented by
development requirements: retain vendor hashes/provenance and separately monitor
upstream advisories. A clean dependency audit does not prove absence of all runtime
vulnerabilities or satisfy every human submission claim automatically.

Sources: [security workflow](https://github.com/github/spec-kit/blob/main/.github/workflows/security.yml),
[dependency updates](https://github.com/github/spec-kit/blob/main/.github/dependabot.yml).

### U3. Submission issues produce maintainer-owned catalog PRs

Official catalog additions and updates go through the extension submission issue
form. Maintainer triage applies the label that starts validation. Validation checks
tag-pinned downloads, versions, supplied hashes, and checklist evidence before
generating a draft catalog PR. Editing an issue does not automatically rerun its
label-triggered workflow or update an existing generated PR.

Retain issue-driven automation and never directly mutate an upstream PR. Never
claim an unperformed test passed. Preserve evidence and flag superseded validated
versions. Some surveyed repositories still contain direct catalog-PR workflows;
these are examples of policy drift, not current official guidance.

Sources: [contribution policy](https://github.com/github/spec-kit/blob/main/CONTRIBUTING.md#community-catalog-submissions),
[issue form](https://github.com/github/spec-kit/blob/main/.github/ISSUE_TEMPLATE/extension_submission.yml),
[validation workflow](https://github.com/github/spec-kit/blob/main/.github/workflows/add-community-extension.md).
Example to avoid for official submissions:
[direct-PR workflow](https://github.com/RogerBestMsft/spec-kit-FxToNet/blob/main/.github/workflows/community-catalog-pr.yml).

## Community maintenance repositories

### C1. Refresh upstream assets through reviewable PRs

`speckit-community/cc-spec-kit` periodically checks upstream releases, regenerates
platform variants, and opens an update PR. The useful pattern is detection followed
by reproducible generation and a reviewable diff. For our vendored dependency,
prefer an updater PR with contract tests over silently bumping a pin on main.
Resolve release tags to SHAs and compare versions semantically rather than copying
its inequality-based version comparison.

Source: [upstream asset update](https://github.com/speckit-community/cc-spec-kit/blob/main/.github/workflows/update-speckit-assets.yml).

### C2. Selective regeneration and generated-output checks

`cc-spec-kit-extensions` checks for upstream updates, builds a matrix of affected
extensions, regenerates Bash/PowerShell assets, checks manifests and generated
skills, and opens PRs. Its configured extension subset was `verify` and `aide`,
both already included in the official catalog survey.

Keep refresh work limited to changed inputs and validate generated outputs.
Automation should open one clearly identified PR per dependency/update stream.
Do not copy direct interpolation of remote/input strings into shell code.

Sources: [regeneration](https://github.com/speckit-community/cc-spec-kit-extensions/blob/main/.github/workflows/regenerate-extensions.yml),
[configured subset](https://github.com/speckit-community/cc-spec-kit-extensions/blob/main/.tooling/extensions.json).

### C3. The community browser consumes the official catalog

`speckit-community/extensions` builds a browsing site from a Spec Kit submodule,
supports a supplied catalog commit, and refreshes periodically. It is a downstream
view, not another authoritative catalog-submission endpoint. Do not add another
submission pipeline for it; successful upstream catalog inclusion is the source.

Sources: [site purpose](https://github.com/speckit-community/extensions/blob/main/README.md),
[deployment](https://github.com/speckit-community/extensions/blob/main/.github/workflows/deploy.yml).

## GitHub and pipeline development references

### G1. Immutable releases and draft-first publication

GitHub documents immutable releases that lock published assets and their tag and
produce a release attestation. It recommends preparing a draft, attaching assets,
then publishing. Immutability applies to future releases when enabled; release
notes and prerelease/latest classification remain editable. It does not enforce
our CI or candidate-history requirements.

Recommendation: enable immutability, create drafts, verify the complete expected
asset set and digests before publication, then verify public download installation.
Recover incorrect published content with a new version. Avoid upload replacement
flags and do not reuse a published tag. Keep stable and candidate tags distinct.

Sources: [immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases),
[enable immutability](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes),
[release verification](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity).

### G2. Build provenance and actual artifact promotion

Artifact attestations link digests to build identity and source; they help only
when verified. They do not prove the software is safe. For candidate-to-stable
promotion, preserve the runtime ZIP bytes and original build provenance rather
than rebuild and claim an identical tested artifact. Record stable promotion as
a distinct operation referencing the candidate's source and digest.

Recommendation: publish/retain the candidate ZIP's build attestation, verify its
expected repository/workflow/source identity during promotion, and retain the
stable release attestation. Merely hashing a downloaded candidate ZIP in a later
workflow is not evidence of how that ZIP was originally built.

Source: [artifact attestation guidance](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations).

### G3. Minimal job authority and immutable action references

Use read-only default permissions and grant publication/submission authority only
to jobs that need it. Pin external actions to reviewed full SHAs with human-readable
version comments. Disable persisted checkout credentials unless a later write
requires them. Protect publishing secrets with environments and restrict privileged
jobs to trusted policy/workflow sources. Never execute PR code with release tokens.

Source: [GitHub secure use reference](https://docs.github.com/en/actions/reference/security/secure-use).

### G4. Treat input and downstream artifacts as untrusted data

GitHub Security Lab explains how executing fork code in a privileged workflow can
expose repository authority. `workflow_run` does not make downloaded artifacts
trusted. Pass user/remote strings through environment variables or structured
arguments, validate version/ref/repository/URL formats, and avoid embedding values
into shell program text. Bound JSON/ZIP size, paths, and member counts as well as
checking digests.

Source: [Preventing pwn requests](https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/),
[script injection guidance](https://docs.github.com/en/actions/concepts/security/script-injections).

### G5. actionlint checks workflow structure and wiring

actionlint checks workflow syntax, expressions, action interfaces, reusable workflow
contracts, shell snippets, and dependency wiring. It complements Python tests and
does not exercise real API permissions or publication. Pin its binary/action and
validate relevant Windows shells too; do not blindly adopt a moving download script.

Source: [actionlint](https://github.com/rhysd/actionlint).

### G6. zizmor checks Actions security patterns

zizmor provides security-focused workflow analysis. Use it alongside actionlint,
review findings, and keep narrowly explained exceptions where needed. Static
analysis does not certify that a credential setup or release policy is correct.

Source: [zizmor documentation](https://docs.zizmor.sh/).

### G7. Update automation must preserve review and compatibility

Dependabot can update GitHub Actions and supported dependency ecosystems with
grouping and update limits. Configure reviewable, bounded update streams. Preserve
Python 3.9 compatibility when selecting development pins and avoid indiscriminate
auto-merge of major updates, workflow changes, or new permissions. For vendored
source files, use the existing specialized updater rather than expecting Dependabot
to infer the upstream pin from VENDOR.json.

Source: [Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).

### G8. Required checks must have stable, unique names

GitHub warns that reused job names across workflows can create ambiguous required
checks. Whole-workflow path filtering can leave a required context pending.
Use a unique always-evaluated aggregate gate and explicitly require its dependencies
to succeed. Register required checks with their expected GitHub Actions source;
evaluate the exact SHA/run rather than accepting any green status with a matching
name. Keep the existing contexts until their replacement is proven.

Source: [protected branch guidance](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
[workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

### G9. Scorecard is diagnostic evidence, not a release oracle

OpenSSF Scorecard documents checks for dangerous workflows, token permissions,
dependency updates, branch protection, and other maintenance signals. Use specific
findings to prioritize work. A high aggregate score does not prove runtime safety;
a low score can include choices that need project context rather than cargo-cult
changes. An advisory scheduled scan is a reasonable later addition.

Source: [Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md).

### G10. Reproducible archives require controlled inputs

The Reproducible Builds project documents SOURCE_DATE_EPOCH as a conventional
timestamp input. For Python ZIP packaging, implement a fixed timestamp derived
from the source commit (within ZIP's supported range), sorted paths, normalized
permission metadata, and pinned build tooling. Account for compression-library
differences; test byte-identical rebuilds on the designated publishing environment
rather than promise universal identity across every machine.

Source: [SOURCE_DATE_EPOCH](https://reproducible-builds.org/docs/source-date-epoch/).

### G11. Concurrency is a queue policy, not a transactional lock

Current GitHub guidance documents one pending run by default; later arrivals replace
it. `cancel-in-progress: false` preserves the running job but does not preserve all
pending requests. `queue: max` permits up to 100 pending runs and cannot be combined
with cancellation of the running job. Waiting-time order does not guarantee dispatch
order. Use a common mutation group, immutable refs, remote-state checks, version
monotonicity, and idempotent operations regardless of queue configuration.

Source: [workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

### G12. Reuse checks explicitly and retain bounded evidence

Reusable workflows provide typed inputs and explicit outputs/secrets. Reuse CI for
candidate and stable validation; keep publish tokens out of test jobs. GitHub token
event behavior can prevent follow-up runs or require approval, so explicitly call
publication verification/submission rather than assuming release/PR events will
complete the chain. Add job/network timeouts and publish bounded reports on failure,
without transcripts, personal data, or secrets.

Sources: [reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows),
[workflow triggering](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

## Original articles and how to apply them

### A1. Martin Fowler: Deployment Pipeline (2013-05-30)

Fowler describes staged confidence: early fast checks, deeper validation later,
optional human gates, and visible delivery history. For Usage Bridge, run inexpensive
syntax/version checks first, then matrix and archive installation tests, then
approved publication. Promote the validated artifact and retain clear evidence of
which stage failed. This supports our staged design; it does not prescribe specific
GitHub syntax or replace current platform documentation.

Source: [Deployment Pipeline](https://martinfowler.com/bliki/DeploymentPipeline.html).

### A2. Ashish Kurmi / StepSecurity: GitHub Actions security (2024-10-14)

The article advocates least privilege, protected secrets, action governance, and
workflow change controls. These principles support a small privileged publishing
surface and reviewed workflow updates. It is a vendor-authored article; confirm
platform details in current GitHub documentation and do not infer that its paid
products are required. Cloud OIDC does not automatically solve authentication for
creating an issue in an unrelated public GitHub repository.

Source: [GitHub Actions security practices](https://www.stepsecurity.io/blog/github-actions-security-best-practices).

## Patterns to avoid or defer

- **Direct catalog PRs:** historical community examples conflict with current
  official submission policy. Use the issue form and upstream validation.
- **Release on every main push:** conflicts with the requested candidate-first
  lifecycle. Release-please may assist preparation without owning promotion.
- **ZIP the whole checkout:** fails the requested minimal runtime payload.
- **Replace uploaded assets:** retries must compare existing bytes and refuse
  conflicts; publication of different content needs another version.
- **Accept a successful workflow without inspecting required jobs:** skipped,
  cancelled, missing, or unrelated results cannot satisfy release checks.
- **Keep publishing authority in the build/test job:** validate on an unprivileged
  runner; publish on a separate runner with trusted scripts and verified artifacts.
- **Treat pipeline policy files as executable upstream configuration:** review
  upstream changes and update our policy deliberately.
- **Adopt every ecosystem tool:** wheels, npm, containers, Pages, DCO, complex
  multi-package releases, and large AI triage systems are unnecessary for this
  file-distributed Python extension unless a concrete maintenance need appears.
- **Close support issues merely for inactivity:** prefer useful templates and
  labels first; automated stale closure can hide unresolved compatibility bugs.

## Implementation acceptance checklist

When the release design and plan are approved, verify:

1. The same source/build inputs reproduce the runtime ZIP; no tests/docs/development
   files appear, and vendor/legal/runtime data remain present.
2. All entrypoints and declared commands work after clean archive installation;
   minimum/current stable hosts are resolved explicitly and upgrade preserves config.
3. A stable release cannot skip a published candidate of the same SHA. Branch
   movement, missing checks, and nonwaivable failures stop promotion.
4. An override needs a reason, completed identified failures, and approval bound to
   that run and SHA; it grants no main-merge or upstream-checklist bypass.
5. Draft publication contains the expected assets; immutability is verified after
   publication and a provenance verifier checks the candidate build identity.
6. Publication retries, submission retries, and merge-back retries do not replace
   assets, duplicate issues, or let older runs overwrite newer metadata.
7. Required CI contexts cannot be satisfied by skipped checks or ambiguous names;
   tests have no publishing/submission credentials.
8. Official issues use current form headings, tag-pinned URLs, and truthful evidence;
   validated issues/generated PRs are not silently rewritten to another version.
9. Applied main/tag/environment settings are read back from GitHub; workflow lint
   and security scans pass, and failure paths are exercised without stable publishing.

## Complete repository coverage

The table below includes every catalog repository plus upstream/community support
repositories. Counts are discovered YAML workflow paths, not proof those workflows
ran or passed. The ledger has the full path lists and per-document evidence.

| Repository | Catalog extension IDs | YAML workflows |
|---|---|---:|
| [aaronrsun/spec-kit-checkpoint](https://github.com/aaronrsun/spec-kit-checkpoint) | checkpoint | 0 |
| [aaronrsun/spec-kit-confluence](https://github.com/aaronrsun/spec-kit-confluence) | confluence | 0 |
| [aaronrsun/spec-kit-issue](https://github.com/aaronrsun/spec-kit-issue) | issue | 0 |
| [aaronrsun/spec-kit-openspec](https://github.com/aaronrsun/spec-kit-openspec) | openspec | 0 |
| [abir-ommezzine/extension-github-spec-kit](https://github.com/abir-ommezzine/extension-github-spec-kit) | agentdocx-speckit | 0 |
| [aeltayeb/spec-kit-spec-validate](https://github.com/aeltayeb/spec-kit-spec-validate) | spec-validate | 0 |
| [ahmed200346/Extension_GithubSpecKit](https://github.com/ahmed200346/Extension_GithubSpecKit) | agentdocx-speckitv2 | 0 |
| [AI-MDE/spec-kit-mde](https://github.com/AI-MDE/spec-kit-mde) | mde | 0 |
| [alexcpn/catalogify](https://github.com/alexcpn/catalogify) | okf | 1 |
| [alfredoperez/speckit-companion](https://github.com/alfredoperez/speckit-companion) | companion | 5 |
| [andstepanuk/speckit-test-validate](https://github.com/andstepanuk/speckit-test-validate) | test-by | 0 |
| [anvigo12/specup](https://github.com/anvigo12/specup) | openup | 0 |
| [Arcadia822/taco](https://github.com/Arcadia822/taco) | taco | 4 |
| [arrrrny/speckit-extensions](https://github.com/arrrrny/speckit-extensions) | gh-triage | 1 |
| [artursopelnik/spec-kit-design-system](https://github.com/artursopelnik/spec-kit-design-system) | design | 2 |
| [arunt14/spec-kit-critique](https://github.com/arunt14/spec-kit-critique) | critique | 0 |
| [arunt14/spec-kit-qa](https://github.com/arunt14/spec-kit-qa) | qa | 0 |
| [arunt14/spec-kit-retro](https://github.com/arunt14/spec-kit-retro) | retro | 0 |
| [arunt14/spec-kit-ship](https://github.com/arunt14/spec-kit-ship) | ship | 0 |
| [arunt14/spec-kit-staff-review](https://github.com/arunt14/spec-kit-staff-review) | staff-review | 0 |
| [ashbrener/spec-kit-arch-governance](https://github.com/ashbrener/spec-kit-arch-governance) | arch-governance | 0 |
| [ashbrener/spec-kit-atlas](https://github.com/ashbrener/spec-kit-atlas) | atlas | 1 |
| [ashbrener/spec-kit-jira-sync](https://github.com/ashbrener/spec-kit-jira-sync) | jira-sync | 1 |
| [ashbrener/spec-kit-linear-sync](https://github.com/ashbrener/spec-kit-linear-sync) | linear | 1 |
| [ashbrener/spec-kit-red-team](https://github.com/ashbrener/spec-kit-red-team) | red-team | 1 |
| [Azure-Samples/Spec2Cloud](https://github.com/Azure-Samples/Spec2Cloud) | spec2cloud | 1 |
| [AzureCosmosDB/spec-kit-cosmosdb](https://github.com/AzureCosmosDB/spec-kit-cosmosdb) | cosmosdb | 1 |
| [bbjwz/agentstandards](https://github.com/bbjwz/agentstandards) | agentstandards | 3 |
| [BenBtg/spec-kit-m365](https://github.com/BenBtg/spec-kit-m365) | m365 | 0 |
| [BenBtg/spec-kit-markitdown](https://github.com/BenBtg/spec-kit-markitdown) | markitdown | 0 |
| [bendlikeabamboo/pre-spec](https://github.com/bendlikeabamboo/pre-spec) | prespec | 0 |
| [benizzio/spec-kit-coding-standards-drift-control](https://github.com/benizzio/spec-kit-coding-standards-drift-control) | coding-standards-drift-control | 0 |
| [benizzio/spec-kit-data-model-diagram](https://github.com/benizzio/spec-kit-data-model-diagram) | data-model-diagram | 0 |
| [benizzio/spec-kit-orchestration-task-context-management](https://github.com/benizzio/spec-kit-orchestration-task-context-management) | orchestration-task-context-management | 1 |
| [benizzio/spec-kit-test-coverage-drift-control](https://github.com/benizzio/spec-kit-test-coverage-drift-control) | test-coverage-drift-control | 0 |
| [bgervin/spec-kit-sync](https://github.com/bgervin/spec-kit-sync) | sync | 1 |
| [bigsmartben/spec-kit-agent-governance](https://github.com/bigsmartben/spec-kit-agent-governance) | agent-governance, repository-governance | 3 |
| [bigsmartben/spec-kit-arch](https://github.com/bigsmartben/spec-kit-arch) | arch | 2 |
| [bigsmartben/spec-kit-discovery](https://github.com/bigsmartben/spec-kit-discovery) | discovery | 0 |
| [bigsmartben/spec-kit-intake](https://github.com/bigsmartben/spec-kit-intake) | intake | 2 |
| [bigsmartben/spec-kit-preview](https://github.com/bigsmartben/spec-kit-preview) | preview | 0 |
| [cadugevaerd/spec-kit-verify-review-ship](https://github.com/cadugevaerd/spec-kit-verify-review-ship) | verify-review-ship | 0 |
| [capatinore/contextforge-mcp](https://github.com/capatinore/contextforge-mcp) | contextforge-mcp | 2 |
| [chordpli/spec-kit-blueprint](https://github.com/chordpli/spec-kit-blueprint) | blueprint | 0 |
| [chordpli/spec-kit-ripple](https://github.com/chordpli/spec-kit-ripple) | ripple | 0 |
| [coderandhiker/spec-kit-token-analyzer](https://github.com/coderandhiker/spec-kit-token-analyzer) | token-analyzer | 0 |
| [d0whc3r/spec-kit-axi](https://github.com/d0whc3r/spec-kit-axi) | axi | 4 |
| [d0whc3r/spec-kit-improve](https://github.com/d0whc3r/spec-kit-improve) | improve | 4 |
| [d0whc3r/spec-kit-product](https://github.com/d0whc3r/spec-kit-product) | product | 4 |
| [d0whc3r/spec-kit-tdd](https://github.com/d0whc3r/spec-kit-tdd) | tdd | 4 |
| [dango85/spec-kit-worktree-parallel](https://github.com/dango85/spec-kit-worktree-parallel) | worktrees | 2 |
| [datastone-inc/spec-kit-verify-tasks](https://github.com/datastone-inc/spec-kit-verify-tasks) | verify-tasks | 0 |
| [DevAbdullah90/spec-kit-whatif](https://github.com/DevAbdullah90/spec-kit-whatif) | whatif | 0 |
| [dhruv-15-03/spec-kit-ears](https://github.com/dhruv-15-03/spec-kit-ears) | ears | 0 |
| [dmux/spec-kit-onboard](https://github.com/dmux/spec-kit-onboard) | onboard | 0 |
| [dsrednicki/spec-kit-cleanup](https://github.com/dsrednicki/spec-kit-cleanup) | cleanup | 0 |
| [DyanGalih/architecture-guard](https://github.com/DyanGalih/architecture-guard) | architecture-guard | 1 |
| [DyanGalih/security-review](https://github.com/DyanGalih/security-review) | security-review | 1 |
| [DyanGalih/spec-kit-memory-hub](https://github.com/DyanGalih/spec-kit-memory-hub) | memory-md | 0 |
| [electrohire/spec-kit-aee](https://github.com/electrohire/spec-kit-aee) | aee | 4 |
| [electrohire/spec-kit-evaluator](https://github.com/electrohire/spec-kit-evaluator) | evaluator | 2 |
| [emi-dm/spec-kit-retrospective](https://github.com/emi-dm/spec-kit-retrospective) | retrospective | 0 |
| [Fatima367/spec-kit-github-issues](https://github.com/Fatima367/spec-kit-github-issues) | github-issues | 0 |
| [formin/multi-model-review](https://github.com/formin/multi-model-review) | multi-model-review | 0 |
| [formin/spec-kit-harness](https://github.com/formin/spec-kit-harness) | harness | 1 |
| [formin/spec-kit-loop](https://github.com/formin/spec-kit-loop) | loop | 1 |
| [formin/spec-kit-token-economy](https://github.com/formin/spec-kit-token-economy) | token-economy | 0 |
| [formin/spec-kit-wiki](https://github.com/formin/spec-kit-wiki) | wiki | 0 |
| [Fyloss/spec-kit-analytics](https://github.com/Fyloss/spec-kit-analytics) | analytics | 1 |
| [Fyloss/spec-kit-charter](https://github.com/Fyloss/spec-kit-charter) | charter | 1 |
| [Fyloss/spec-kit-figma](https://github.com/Fyloss/spec-kit-figma) | figma | 1 |
| [Fyloss/spec-kit-jira-mirror](https://github.com/Fyloss/spec-kit-jira-mirror) | jira-mirror | 8 |
| [fyloss/spec-kit-multi-repo-sync](https://github.com/fyloss/spec-kit-multi-repo-sync) | multi-repo-sync | 1 |
| [GenieRobot/spec-kit-maqa-azure-devops](https://github.com/GenieRobot/spec-kit-maqa-azure-devops) | maqa-azure-devops | 0 |
| [GenieRobot/spec-kit-maqa-ci](https://github.com/GenieRobot/spec-kit-maqa-ci) | maqa-ci | 0 |
| [GenieRobot/spec-kit-maqa-ext](https://github.com/GenieRobot/spec-kit-maqa-ext) | maqa | 0 |
| [GenieRobot/spec-kit-maqa-github-projects](https://github.com/GenieRobot/spec-kit-maqa-github-projects) | maqa-github-projects | 0 |
| [GenieRobot/spec-kit-maqa-jira](https://github.com/GenieRobot/spec-kit-maqa-jira) | maqa-jira | 0 |
| [GenieRobot/spec-kit-maqa-linear](https://github.com/GenieRobot/spec-kit-maqa-linear) | maqa-linear | 0 |
| [GenieRobot/spec-kit-maqa-trello](https://github.com/GenieRobot/spec-kit-maqa-trello) | maqa-trello | 0 |
| [github/spec-kit](https://github.com/github/spec-kit) | Upstream/community support | 18 |
| [hupe1980/spec-kit-threatspec](https://github.com/hupe1980/spec-kit-threatspec) | threatspec | 3 |
| [imviancagrace/spec-kit-iterate](https://github.com/imviancagrace/spec-kit-iterate) | iterate | 0 |
| [imviancagrace/spec-kit-learn](https://github.com/imviancagrace/spec-kit-learn) | learn | 0 |
| [ismaelJimenez/spec-kit-review](https://github.com/ismaelJimenez/spec-kit-review) | review | 1 |
| [ismaelJimenez/spec-kit-verify](https://github.com/ismaelJimenez/spec-kit-verify) | verify | 1 |
| [jasstt/spec-kit-golden-demo](https://github.com/jasstt/spec-kit-golden-demo) | golden-demo | 0 |
| [jfranc38/spec-kit-schedule](https://github.com/jfranc38/spec-kit-schedule) | schedule | 2 |
| [jiezeng2004-design/spec-kit-patchwarden](https://github.com/jiezeng2004-design/spec-kit-patchwarden) | patchwarden-evidence | 0 |
| [JoaquinRuiz/SpecJudge](https://github.com/JoaquinRuiz/SpecJudge) | specjudge | 2 |
| [juangcarmona/productshape](https://github.com/juangcarmona/productshape) | pdac, pdac-product | 7 |
| [jwill824/spec-kit-squad](https://github.com/jwill824/spec-kit-squad) | squad | 4 |
| [keeldiscovery/spec-kit-keel](https://github.com/keeldiscovery/spec-kit-keel) | keel | 0 |
| [KevinBrown5280/spec-kit-memory-loader](https://github.com/KevinBrown5280/spec-kit-memory-loader) | memory-loader | 0 |
| [KevinBrown5280/spec-kit-spec-reference-loader](https://github.com/KevinBrown5280/spec-kit-spec-reference-loader) | spec-reference-loader | 0 |
| [KevinBrown5280/spec-kit-version-guard](https://github.com/KevinBrown5280/spec-kit-version-guard) | version-guard | 0 |
| [KhawarHabibKhan/spec-kit-doctor](https://github.com/KhawarHabibKhan/spec-kit-doctor) | doctor | 0 |
| [KhawarHabibKhan/spec-kit-status](https://github.com/KhawarHabibKhan/spec-kit-status) | status | 0 |
| [kotnisofiane-bit/dubsar-memory](https://github.com/kotnisofiane-bit/dubsar-memory) | dubsar | 1 |
| [leocamello/spec-kit-v-model](https://github.com/leocamello/spec-kit-v-model) | v-model | 3 |
| [lihan3238/speckit-superpowers-bridge](https://github.com/lihan3238/speckit-superpowers-bridge) | speckit-superpowers-bridge | 1 |
| [liuyiyu/spec-kit-repoindex](https://github.com/liuyiyu/spec-kit-repoindex) | repoindex | 0 |
| [LoogacyStudio/spec-kit-reqnroll-bdd](https://github.com/LoogacyStudio/spec-kit-reqnroll-bdd) | reqnroll-bdd | 0 |
| [luno/spec-kit-plan-review-gate](https://github.com/luno/spec-kit-plan-review-gate) | plan-review-gate | 0 |
| [MaksimShevtsov/BrownKit](https://github.com/MaksimShevtsov/BrownKit) | brownkit | 0 |
| [mancioshell/spec-kit-tasks-to-project](https://github.com/mancioshell/spec-kit-tasks-to-project) | tasks-to-project | 0 |
| [maximiliamus/spec-kit-canon](https://github.com/maximiliamus/spec-kit-canon) | canon | 1 |
| [mbachorik/spec-kit-jira](https://github.com/mbachorik/spec-kit-jira) | jira | 0 |
| [mbeacom/adrkit](https://github.com/mbeacom/adrkit) | adrkit | 8 |
| [mnriem/spec-kit-extensions](https://github.com/mnriem/spec-kit-extensions) | aide, extensify, presetify | 2 |
| [MRZHUH/spec-kit-ascii-diagram](https://github.com/MRZHUH/spec-kit-ascii-diagram) | ascii-diagram | 0 |
| [mvanhorn/speckit-utils](https://github.com/mvanhorn/speckit-utils) | speckit-utils | 0 |
| [NaviaSamal/spec-kit-threatmodel](https://github.com/NaviaSamal/spec-kit-threatmodel) | threatmodel | 0 |
| [ogil109/spec-kit-blueprint](https://github.com/ogil109/spec-kit-blueprint) | blueprint-index | 1 |
| [OmneWave/spec-kit-figma-starter](https://github.com/OmneWave/spec-kit-figma-starter) | figma-starter | 0 |
| [Open-Agent-Tools/spec-kit-status](https://github.com/Open-Agent-Tools/spec-kit-status) | status-report | 0 |
| [pragya247/spec-kit-azure-devops](https://github.com/pragya247/spec-kit-azure-devops) | azure-devops | 0 |
| [pragya247/spec-kit-orchestrator](https://github.com/pragya247/spec-kit-orchestrator) | agent-orchestrator | 0 |
| [Quratulain-bilal/spec-kit-api-evolve](https://github.com/Quratulain-bilal/spec-kit-api-evolve) | api-evolve | 0 |
| [Quratulain-bilal/spec-kit-branch-convention](https://github.com/Quratulain-bilal/spec-kit-branch-convention) | branch-convention | 0 |
| [Quratulain-bilal/spec-kit-brownfield](https://github.com/Quratulain-bilal/spec-kit-brownfield) | brownfield | 0 |
| [Quratulain-bilal/spec-kit-bugfix](https://github.com/Quratulain-bilal/spec-kit-bugfix) | bugfix | 0 |
| [Quratulain-bilal/spec-kit-catalog-ci](https://github.com/Quratulain-bilal/spec-kit-catalog-ci) | catalog-ci | 0 |
| [Quratulain-bilal/spec-kit-changelog](https://github.com/Quratulain-bilal/spec-kit-changelog) | changelog | 0 |
| [Quratulain-bilal/spec-kit-ci-guard](https://github.com/Quratulain-bilal/spec-kit-ci-guard) | ci-guard | 0 |
| [Quratulain-bilal/spec-kit-cost](https://github.com/Quratulain-bilal/spec-kit-cost) | cost | 0 |
| [Quratulain-bilal/spec-kit-diagram-](https://github.com/Quratulain-bilal/spec-kit-diagram-) | diagram | 0 |
| [Quratulain-bilal/spec-kit-fix-findings](https://github.com/Quratulain-bilal/spec-kit-fix-findings) | fix-findings | 0 |
| [Quratulain-bilal/spec-kit-orchestrator](https://github.com/Quratulain-bilal/spec-kit-orchestrator) | orchestrator | 0 |
| [Quratulain-bilal/spec-kit-pr-bridge-](https://github.com/Quratulain-bilal/spec-kit-pr-bridge-) | pr-bridge | 0 |
| [Quratulain-bilal/spec-kit-refine](https://github.com/Quratulain-bilal/spec-kit-refine) | refine | 0 |
| [Quratulain-bilal/spec-kit-scope-](https://github.com/Quratulain-bilal/spec-kit-scope-) | scope | 0 |
| [Quratulain-bilal/spec-kit-spectest](https://github.com/Quratulain-bilal/spec-kit-spectest) | spectest | 0 |
| [Quratulain-bilal/spec-kit-tinyspec](https://github.com/Quratulain-bilal/spec-kit-tinyspec) | tinyspec | 0 |
| [Quratulain-bilal/spec-kit-trace](https://github.com/Quratulain-bilal/spec-kit-trace) | trace | 0 |
| [Quratulain-bilal/spec-kit-worktree](https://github.com/Quratulain-bilal/spec-kit-worktree) | worktree | 0 |
| [qurore/speckit-tldr](https://github.com/qurore/speckit-tldr) | tldr | 0 |
| [raccioly/docguard](https://github.com/raccioly/docguard) | docguard | 7 |
| [RbBtSn0w/spec-kit-extensions](https://github.com/RbBtSn0w/spec-kit-extensions) | memorylint, superb | 2 |
| [rdryfoos/specassay](https://github.com/rdryfoos/specassay) | specassay-check | 5 |
| [RogerBestMsft/spec-kit-FxToNet](https://github.com/RogerBestMsft/spec-kit-FxToNet) | fx-to-dotnet | 6 |
| [RSginer/spec-kit-bdd](https://github.com/RSginer/spec-kit-bdd) | bdd | 1 |
| [Rubiss-Projects/spec-kit-ralph](https://github.com/Rubiss-Projects/spec-kit-ralph) | ralph | 3 |
| [sakitA/spec-kit-optimize](https://github.com/sakitA/spec-kit-optimize) | optimize | 1 |
| [sakitA/spec-kit-workiq](https://github.com/sakitA/spec-kit-workiq) | workiq | 0 |
| [schwichtgit/spec-gates](https://github.com/schwichtgit/spec-gates) | gates | 2 |
| [Sertxito/spec-kit-extension-rag-azure-builder](https://github.com/Sertxito/spec-kit-extension-rag-azure-builder) | rag-azure-builder | 0 |
| [sharathsatish/spec-kit-fleet](https://github.com/sharathsatish/spec-kit-fleet) | fleet | 0 |
| [shawnhvac/spec-kit-pay-x402](https://github.com/shawnhvac/spec-kit-pay-x402) | pay-x402 | 0 |
| [shawnhvac/spec-kit-prepay-audit](https://github.com/shawnhvac/spec-kit-prepay-audit) | prepay-audit | 0 |
| [shiersa/vurnix-spec-kit](https://github.com/shiersa/vurnix-spec-kit) | vurnix | 0 |
| [specdog/dotdog](https://github.com/specdog/dotdog) | dotdog | 5 |
| [speckit-community/cc-spec-kit](https://github.com/speckit-community/cc-spec-kit) | Upstream/community support | 1 |
| [speckit-community/cc-spec-kit-extensions](https://github.com/speckit-community/cc-spec-kit-extensions) | Upstream/community support | 1 |
| [speckit-community/extensions](https://github.com/speckit-community/extensions) | Upstream/community support | 3 |
| [speckit-community/spec-kit-fixit](https://github.com/speckit-community/spec-kit-fixit) | fixit | 1 |
| [srobroek/speckit-roadmap](https://github.com/srobroek/speckit-roadmap) | roadmap | 2 |
| [stn1slv/spec-kit-archive](https://github.com/stn1slv/spec-kit-archive) | archive | 0 |
| [stn1slv/spec-kit-reconcile](https://github.com/stn1slv/spec-kit-reconcile) | reconcile | 0 |
| [SuhaibAslam/spec-kit-reconcile](https://github.com/SuhaibAslam/spec-kit-reconcile) | intent | 1 |
| [tarunkumarbhati/spec-kit-team-assign](https://github.com/tarunkumarbhati/spec-kit-team-assign) | team-assign | 0 |
| [teeyo/spec-kit-multi-sites](https://github.com/teeyo/spec-kit-multi-sites) | multi-sites | 0 |
| [teeyo/spec-kit-time-machine](https://github.com/teeyo/spec-kit-time-machine) | time-machine | 0 |
| [tinesoft/spec-kit-token-budget](https://github.com/tinesoft/spec-kit-token-budget) | token-budget | 1 |
| [tonydwoodhouse/spec-kit-linear-weave](https://github.com/tonydwoodhouse/spec-kit-linear-weave) | linear-weave | 0 |
| [TortoiseWolfe/spec-kit-extension-wireframe](https://github.com/TortoiseWolfe/spec-kit-extension-wireframe) | wireframe | 0 |
| [twbrandon7/spec-kit-conduct-ext](https://github.com/twbrandon7/spec-kit-conduct-ext) | conduct | 1 |
| [UmmeHabiba1312/spec-kit-architect-preview](https://github.com/UmmeHabiba1312/spec-kit-architect-preview) | architect-preview | 0 |
| [VaiYav/speckit-product-forge](https://github.com/VaiYav/speckit-product-forge) | product-forge | 1 |
| [WangX0111/superspec](https://github.com/WangX0111/superspec) | superspec | 1 |
| [xymelon/spec-kit-agent-assign](https://github.com/xymelon/spec-kit-agent-assign) | agent-assign | 0 |
| [Yash-Chindam/spec-kit-inventory-alignment](https://github.com/Yash-Chindam/spec-kit-inventory-alignment) | speckit-inventory | 0 |
| [yoshi1220/speckit-grill-me](https://github.com/yoshi1220/speckit-grill-me) | grill | 0 |
| [ysumanth06/spec-kit-sf](https://github.com/ysumanth06/spec-kit-sf) | sf | 0 |
| [zaytsevand/spec-kit-memory](https://github.com/zaytsevand/spec-kit-memory) | memory | 0 |
