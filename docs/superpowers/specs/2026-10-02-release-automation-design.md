# Usage Bridge release automation and repository protection

Date: 2026-10-02
Status: Proposed written specification; user review required before implementation planning.

## 1. Intent and decisions

Provide a GitHub Actions release lifecycle that lets the maintainer prepare a
release, make final fixes on a release branch, publish candidates, and promote a
tested candidate to a stable release. Stable releases must never skip prerelease.
Normally every required check must pass. A deliberately requested exception needs
a separate approval and a recorded reason.

Ship only the files needed to install and run the extension. After publishing and
verifying a stable release, submit its metadata to official github/spec-kit using
the official issue-driven process. The user selected that process on 2026-10-02;
it replaces the earlier proposal to create catalog PRs from a personal fork.

Separately, require PRs and passing CI for main, including the maintainer's own
changes. Merge release fixes back through a PR; automate merging only when the
protected branch requirements pass and there are no conflicts.

This specification does not publish a release, submit an issue, or apply repository
settings. Those operations belong to implementation after the required reviews.

## 2. Verified starting point

- Repository: CrazyBaran/spec-kit-usage-bridge, public, default branch main.
- extension.yml version: 0.2.1. This design does not prescribe the next version.
- release.yml currently publishes on v* tag pushes after calling ci.yml.
- ci.yml includes lint, four Linux/Windows Python test combinations, and two
  Linux/Windows integration jobs. All seven checks on main passed when inspected.
- main has no branch protection or rulesets; repository auto-merge is disabled.
- CrazyBaran/spec-kit is a fork of github/spec-kit. Its main was identical to
  upstream main when inspected: zero commits ahead and zero behind.
- Existing packaging uses tracked files and a denylist. Replace archive selection
  with a runtime allowlist rather than relying on exclusions alone.
- Existing installation integration tests exercise a generated archive, but do
  not yet establish the full isolated runtime behavior of a published archive.

## 3. Release states and entry points

Use manually dispatched Prepare release, Publish candidate, and Promote release
workflows with explicit version inputs. Reuse CI and validation jobs and call
follow-up operations explicitly; do not depend on events produced by GITHUB_TOKEN
starting another workflow. Workflows containing publishing authority run from
protected main and check out release code separately for unprivileged testing.

### Prepare release

1. Validate an X.Y.Z target version newer than the latest stable release. Refuse
   duplicate stable versions and a different concurrently active release train.
2. Capture main's commit, create release/X.Y.Z, update extension.yml and the
   matching CHANGELOG.md section, and open one draft PR back to main.
3. If the same train already exists, return its branch and PR rather than create
   duplicates or overwrite maintainer changes.
4. No release or candidate is published by preparation alone.

### Publish candidate

1. Capture the release branch tip as a commit SHA and validate that exact SHA.
2. Run the existing full CI matrix, packaging checks, and isolated archive install
   and runtime smoke tests. Missing, skipped, cancelled, pending, or unavailable
   results are not successful checks.
3. Ensure the branch still points to that SHA before tagging. If it moved, stop
   and require another run for the new tip.
4. Publish a new immutable vX.Y.Z-rc.N tag and GitHub prerelease. The candidate's
   extension manifest retains the target X.Y.Z version; distinguish candidate
   status with the tag, release metadata, and tag-pinned download URL. The builder
   must accept a release tag independently of the manifest version.
5. Candidates are not marked latest and are never submitted to the community
   catalog. Candidate catalog metadata must point to its own tag-pinned assets,
   not the stable latest catalog URL.
6. Record source SHA, check evidence, workflow run, artifact digests, version,
   candidate tag, and any approved exception as machine-readable release metadata.

### Final fixes and stable promotion

Final fixes go onto release/X.Y.Z. Any new commit after the last candidate makes
that candidate ineligible for promotion. Publish and validate another candidate
from the new branch tip before attempting stable promotion.

Promotion resolves an existing, published prerelease for the target version and
requires its tag SHA to equal the current release branch tip. Revalidate the
candidate's downloaded ZIP, digest, manifest, packaging, and isolated installation;
run required CI for that exact source SHA. Recheck the branch immediately before
publishing. Tags are immutable and existing published assets are never replaced.

Create vX.Y.Z at the same SHA as the eligible candidate. Reuse the verified
candidate runtime ZIP bytes for the stable asset; generate stable catalog metadata
with a stable tag-pinned URL. Publish the stable ZIP, catalog.json, checksums,
release metadata, and matching changelog notes. Explicitly update latest only for
the newest eligible stable version.

After publication, download the actual stable assets and repeat digest, metadata,
installation, and runtime smoke checks. This verification also runs for manually
published releases through release: published as a detection path. It does not
retroactively gate manual publication. Publication through Actions calls it
explicitly, so token event suppression cannot skip verification.

Only verified stable assets proceed to upstream submission. A verification failure
must produce a visible failed workflow and withhold submission; do not replace
assets, rewrite tags, or merge back automatically. Recovery is a new candidate and
release version if the published artifact itself was incorrect.

## 4. Approval for an exceptional release

Default to no override. An explicit override request requires a nonempty reason
and an exact list of failed, completed quality checks to waive. Show their run
links and conclusions before the approval job. It must not accept incomplete,
pending, cancelled, or missing checks as completed failures.

Use a release-override environment requiring approval by CrazyBaran. Permit
self-review because the maintainer may initiate and approve the run; this is an
additional explicit approval step, not a requirement for a second person. Disable
administrator bypass of the environment approval. Limit publishing credentials to
the approved job, then recheck the source SHA and immutable release prerequisites.

Never waive candidate existence, source-to-candidate equality, version/tag
consistency, runtime allowlist, legal files, archive digests, or successful isolated
installation/runtime verification. An override cannot release arbitrary unchecked
code or promote a stable version directly from main.

Record requester, approver, reason, source SHA, waived failures, and run links in
the release metadata and notes. Override applies only to that run and SHA. It does
not bypass main's merge requirements or spec-kit's submission checklists. If the
waived checks mean an upstream claim lacks evidence, withhold automatic submission.

## 5. Minimal installation archive

Maintain one usage-bridge/ top-level folder and explicitly allow:

- extension.yml and config-template.yml;
- commands/*.md required by the manifest;
- scripts/python/capture.py, report.py, check.py, and checkpoint.py;
- scripts/python/usage_bridge Python modules and declared runtime data;
- the pinned vendored token-usage script, pricing data, provenance manifest, and
  vendor license;
- root LICENSE and THIRD_PARTY_NOTICES.md.

Exclude README.md, CHANGELOG.md, docs, tests, tools, CI workflows, development
configuration, repository instructions, Git metadata, caches, and unrelated files.
Documentation remains accessible in the public source repository. catalog.json,
checksums, and release metadata are separate release assets, not ZIP payload files.

Validate every packaged member against the allowlist, reject symlinks and escaping
paths, verify all manifest command files and runtime data exist, and retain vendor
hash validation. Build from a clean checkout of the captured commit. Test install,
checkpoint, capture, report, and check against the extracted/installed archive
without access to repository runtime files. Preserve existing configuration on an
upgrade. Publish SHA-256 in both checksums and the generated catalog entry.

## 6. main protection and merge-back

Apply an active main ruleset with no bypass actors:

- Require a pull request for all updates; no direct human or automation pushes.
- Require the branch to be current with main and require GitHub Actions checks:
  lint; test (ubuntu-latest, 3.9); test (ubuntu-latest, 3.x);
  test (windows-latest, 3.9); test (windows-latest, 3.x);
  integration (ubuntu-latest); integration (windows-latest).
- Block force pushes and branch deletion.
- Require resolution of review conversations, but zero mandatory approving
  reviewers so the sole maintainer can merge their own passing PRs.

Enable repository auto-merge. After verified stable publication, mark the release
PR ready and enable normal merge-commit auto-merge, preserving release commit
ancestry. PR CI validates the proposed merge with current main. Conflicts or failed
checks leave the PR open and report the required action. Release override grants
no exemption from these main checks. Delete the release branch only after merging.

Apply repository settings through authenticated GitHub APIs and verify the stored
rules and actual check names. Preserve unrelated existing settings. Workflow
changes themselves arrive through a PR after protection is enabled.

## 7. Release authority and practical enforcement limits

Protect v* tags from creation, updates, and deletion except for a dedicated release
GitHub App. That App has no bypass for main. Prefer short-lived App credentials;
scope the private key to publishing environments and trusted workflow jobs.
Configure trusted Actions so ordinary test jobs cannot read publishing credentials.
Creating branches/PRs with App authentication also allows their normal CI to run.

GitHub does not offer a workflow status requirement on the act of creating a
release itself. People with sufficient repository permissions may use UI/API
publication, and administrators can change protections. Therefore the guarantee
is enforced for the supported Actions publishing path; tag restrictions reduce
manual alternatives but cannot make publication impossible for repository owners.
Document this limit rather than claim an absolute lock. A manual-publication
detector validates, flags policy violations, and withholds automated follow-through.

External prerequisites are a configured release App and an upstream submission
credential. Do not silently fall back to an unrestricted personal token for tag
publication when the App is absent; leave publishing blocked with setup guidance.

## 8. Official spec-kit submission

The accepted path is a structured [Extension]: submission issue in github/spec-kit.
Do not create catalog branches or PRs in CrazyBaran/spec-kit, and do not directly
edit upstream catalog files. Its maintainer-owned workflow produces the PR after
triage. Fork synchronization and contributor branch naming are consequently outside
this release automation; the fork remains available for separate contributions.

Before submission, inspect the live upstream publishing guide, CONTRIBUTING.md,
issue form, and submission workflow. Maintain a reviewed compatibility fingerprint
for those policy files. Changed policy or unsupported form requirements block only
submission and report the new files for review; they do not undo a verified release.
Do not execute policy text or automatically change our security rules from it.

Build the issue body with the official form headings, manifest metadata, a stable
tag-pinned ZIP download URL, SHA-256, proposed catalog entry, usage example, and
specific test evidence. Never claim tests, vulnerability checks, real-project
verification, or documentation review that did not occur. Collect maintainer
attestations for human-only checklist items in a submission approval environment;
bind the attestation to the version, artifact digest, and evidence. Missing evidence
leaves submission pending rather than filling every checkbox automatically.

Use a credential representing CrazyBaran for issue creation and updates: ordinary
GITHUB_TOKEN is repository-scoped, and the current upstream workflow skips common
bot identities. Use the existing public-repository authority of an approved user
credential only in the submission job; never expose it to pull-request code.

Identify automation-owned submissions by repository URL, extension ID, author,
and a stable hidden marker. Serialize operations. Before upstream validation has
started, update one pending, untriaged submission issue to the newest verified
stable release instead of generating duplicates. Compare semantic versions so an
older rerun cannot overwrite a newer submission.

Once a maintainer has applied extension-submission or a generated PR exists, freeze
that issue's validated version. The upstream workflow currently triggers on label
addition, not issue edits, and does not promise to refresh an open generated PR.
For a newer verified version, file one new update submission as the official guide
requires, link the superseded submission/PR, and record the superseding version in
our release summary. Do not edit a maintainer-owned PR or claim it was updated.
Deduplicate retries for the same version. If multiple matching pending issues are
ambiguous, stop submission rather than update an arbitrary one.

Do not apply the maintainer-only submission label or repeatedly request triage.
Only verified stable releases are submitted. Upstream automation currently names
its own PR branches add-usage-bridge-extension or update-usage-bridge-extension;
our workflow does not control those names.

## 9. Failure handling, concurrency, and tests

Allow one active release train. Serialize preparation, candidate numbering,
promotion, publication, and submission mutations; do not cancel a publishing run
halfway through its external writes. Recheck remote SHA and release state before
each mutation. Workflow concurrency is supplemented with immutable tags and remote
state checks. Never use force push to recover a release branch.

Retries inspect existing tags, releases, digests, PRs, and issue markers. Matching
state is reused; conflicting source SHA, asset digest, or version stops the run.
If publication succeeds but submission fails, retry submission without republishing.
If merge-back fails, keep its PR open; upstream submission can still proceed from
a verified stable release. A run summary reports each independent outcome and links.

Test both intended and refused paths: no prior candidate, stale candidate, moved
branch, wrong version, missing/pending/failed CI, missing override approval, absent
reason, attempted nonwaivable bypass, unexpected ZIP contents, bad vendor hashes,
tampered downloads, duplicate release retries, older submission reruns, changed
upstream policy, untriaged issue reuse, validated issue supersession, and conflicts
in the merge-back PR. Mock external APIs for deterministic failure coverage and
exercise full install/runtime behavior on the existing Linux/Windows matrix.

Verify applied branch/tag/environment settings through read-back APIs. Exercise
the new lifecycle with a disposable candidate; do not publish a stable release or
submit upstream merely to test implementation. Require maintainer intent and all
gates for the first production release.

## 10. Maintenance additions and scope

Include operational release summaries, checksums, immutable tags, retryable
follow-through, and documented credential/configuration setup in this work.
Add a single stable CI gate for future protection simplification only as a later
migration after it is present and verified; initial protection uses existing checks.

Recommended separate maintenance work: Dependabot for Python and Actions; scheduled
compatibility tests against the minimum supported and newest stable Spec Kit;
dependency vulnerability checks; and monitoring upstream submission-policy changes.
These should use separate PRs rather than expand this release lifecycle spec.

## 11. Primary references

Verified against live github/spec-kit main and GitHub settings on 2026-10-02:

- https://github.com/github/spec-kit/blob/main/CONTRIBUTING.md#community-catalog-submissions
- https://github.com/github/spec-kit/blob/main/extensions/EXTENSION-PUBLISHING-GUIDE.md
- https://github.com/github/spec-kit/blob/main/.github/ISSUE_TEMPLATE/extension_submission.yml
- https://github.com/github/spec-kit/blob/main/.github/workflows/add-community-extension.md
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
