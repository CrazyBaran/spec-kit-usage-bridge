# Release and update guide

This guide describes the release workflow for maintainers and installation for Spec Kit users.
Publication is a `workflow_dispatch` from protected `main`, not a tag push. Creating tags
and publishing releases requires the release App and the `release-publish` environment.

The catalog and archive commands below are the intended public install after a verified
release. As of 2026-10-02 those URLs are not live; use a source checkout until a real
asset has been verified. The sections below keep the archive contents and the install
commands. [Automated release authority](#automated-release-authority) covers App
setup, candidate promotion, overrides, and catalog issues.

## Release contents

Version 0.2.0 writes schema v2 and reads existing v1 author reports as exact Claude
data. Upgrade **all contributors** before sharing new reports. Downgrading writers
to v0.1 is unsupported; restore a backup if a downgrade is necessary. Existing
configuration files keep their settings and use default runtime settings when omitted.

The archive includes the local Codex adapter, Cursor bridge adapter and OpenAI
pricing table. Vendor hashes are unchanged. Codex and Cursor authenticated automatic
delivery remains manual/unverified; see [native smoke coverage](native-smoke.md).

The release workflow runs CI, builds `usage-bridge-vX.Y.Z.zip` with one top-level `usage-bridge/` folder, generates
`catalog.json`, and publishes both assets with the matching `CHANGELOG.md` section as release notes. Packaging follows
the runtime allowlist in `tools/release/artifacts.py`. The catalog entry carries the extension manifest fields, release download URL, documentation,
changelog, requirements, provided commands and hooks, tags and timestamps.

Before releasing, update `extension.yml` and `CHANGELOG.md` together. The changelog records the vendored token-usage
version and commit. Versioning follows these rules: patch for a vendor update without behavior changes, minor for
report content or number changes, and major for output-file or schema changes. Run the tests and `ruff` checks, verify
the vendor hashes, and review the generated archive and catalog.

To update the pinned token-usage files, inspect the requested upstream ref and run:

```bash
python tools/update-vendor.py <tag>
```

Use `--commit <sha>` only when intentionally pinning a commit instead of a tag. The tool refuses to overwrite modified
vendored files, refreshes `VENDOR.json`, and prints the upstream changelog between refs for review. The manifest
records the latest released version separately from a hash of any Unreleased section; changed unreleased notes
are included in the review output even when the release version stays the same. Run the contract
tests, including oracle reconciliation, after every vendor update. On upstream breakage, retain the old pin and adapt
only in `tu_compat.py` while the issue is investigated.

## Install and update a project

Add the install-allowed catalog and install once per project:

```bash
specify extension catalog add --name usage-bridge --install-allowed https://github.com/CrazyBaran/spec-kit-usage-bridge/releases/latest/download/catalog.json
specify extension add usage-bridge
```

Then update through that catalog:

```bash
specify extension update usage-bridge
```

Spec Kit backs up and restores the extension configuration during updates. Native hooks point to the Spec Kit
dispatcher and survive updates; per-feature report files are rebuilt at the next `Stop` event. Without a catalog, an
installation can use the release archive directly:

```bash
specify extension add usage-bridge --from <release zip URL>
```

## Distribution chain

The extension vendors a pinned, unmodified token-usage library and records its source and hashes in
`scripts/python/vendor/token_usage/VENDOR.json`. Maintainers update that pin through `tools/update-vendor.py`, verify
the compatibility contract, then release the extension archive and catalog. Developers install the extension in
their Spec Kit project using the catalog or archive instructions above. See [the changelog](../CHANGELOG.md) for the
released extension version and upstream token-usage pin.

## v0.2.1 preparation

Version 0.2.1 retains schema v2 and adds the checkpoint entrypoint/package module,
binding module and command instructions. The catalog must advertise four commands
and three workflow hooks. Build with `python tools/build_release.py --version 0.2.1
--out dist --base-url https://github.com/CrazyBaran/spec-kit-usage-bridge` and inspect
the archive before publishing. Vendor hashes stay unchanged. Update/reinstall each
project to render the new command; development installs use `specify extension add
D:/spec-kit-usage-bridge --dev`. Preserve existing configuration and report history.
Preparing this branch does not publish a tag or release.

## Automated release authority

Publication uses a GitHub App installed only in `CrazyBaran/spec-kit-usage-bridge`.
The App needs contents and pull-request write, plus checks, actions, deployments,
attestations, and administration read. Set the repository variable `RELEASE_APP_ID`.
`RELEASE_APP_PRIVATE_KEY` is an environment secret on
`release-publish` only. Build and test jobs do not receive
it. There is no personal-token fallback. If the App is not installed, packaging
can still run locally and publishing stays blocked.

`SPEC_KIT_SUBMISSION_TOKEN` is a CrazyBaran credential stored only in
`catalog-submit`. It opens or updates the upstream catalog issue. It is not a
publishing token.

| Environment | Who approves | What it may do |
|---|---|---|
| `release-publish` | protected `main` workflow | prepare a branch, publish a verified candidate or stable asset |
| `release-override` | CrazyBaran, self-review allowed, admins cannot bypass | waive a completed quality-check failure |
| `catalog-submit` | CrazyBaran, self-review allowed, admins cannot bypass | create or update the Spec Kit submission issue |

Tag creation, update, and deletion for `v*` is limited to the release App through
the `usage-bridge-tags` ruleset. The App cannot bypass `usage-bridge-main`.
Immutable releases are enabled and checked through the repository's
`immutable-releases` REST endpoint. A retry reconciles the existing tag and assets. The
publisher refuses to replace an asset whose digest differs and does not create a
second release for the same tag.

A completed immutable release is reused only after downloading and validating its
original metadata and assets against the requested source and ZIP digest. For an
interrupted draft, resume with the original evidence and asset bundle. A conflicting
rebuild must use a new candidate/version; uploaded assets are never overwritten.

Repository admins can still change rules or publish by hand. A manually published
stable release is detected and flagged. Follow-through does not submit it and
does not merge it.

### Prepare, candidate, promote

1. Dispatch Prepare release with version `X.Y.Z` and the current `main` SHA. The
   App opens `release/X.Y.Z` and a draft pull request. Re-running reuses that
   branch. The job does not create a tag or a release.
2. Dispatch Release with the same version and the exact release commit. CI runs
   on that SHA alongside the install matrix (Linux and Windows, minimum and current
   Spec Kit host, Python 3.12). Minimum compatibility uses `v1.0.12`; current
   uses newest stable verified for this cycle, `v1.1.0`. Ordinary CI integration
   also uses `v1.1.0`. Host refs are explicit and checked against evidence
   reporting; newer releases are adopted through a reviewed change.
   Publication calls `python tools/release_cli.py publish`
   and does not call `gh release create`.
3. Dispatch Promote release with the stable version, the published candidate tag,
   and the same source SHA. A missing, draft, or stale candidate is refused. A
   newer fix needs a new candidate before stable promotion.

Preparation and publication runs share the concurrency group `usage-bridge-release` with
`cancel-in-progress: false`. Actions concurrency has no `queue: max` key, so
that key is not set. Merge-back and catalog mutations have separate serialized groups.
Job budgets are 15 minutes for prepare, 20 minutes for
lint, policy, and publication, 30 minutes for the unit matrix, and 45 minutes
for the install matrix.

### Override scope

An override can waive one of the seven completed CI quality checks when its
conclusion is `failure`, `timed_out`, `action_required`, or `startup_failure`.
The waiver must name that check, include a reason, and match the run id,
attempt, and source SHA. Approval comes from `release-override` history bound
to that attempt and the artifact digest. A JSON field `approved=true` is not
approval. Pending, missing, skipped, and cancelled checks are never waived.
Packaging, digest, source SHA, candidate existence, and install evidence are
never waived.

Supply `waived_checks` as a JSON array of exact failed check names, for example
`["lint"]`, along with `override_reason`. Installation runs even when quality CI
fails. Publication waits for the separate approval job and then re-reads this
run attempt's job results and environment approval history.

### Evidence and credential boundaries

Candidate and stable dispatches share `release-pipeline.yml`. Tools and dependencies
come from protected `main`; the release checkout is read only as build input.
The build signs a custom attestation binding the ZIP digest, source commit, run ID,
and attempt. Credential-free installation jobs consume those exact bytes. The
publisher collects actual Actions results, verifies provenance, and rechecks remote
branch/tag state before writes. It publishes the ZIP, `catalog.json`, `SHA256SUMS`,
and `release-metadata.json`.

### Native host checks and local release checks

| Responsibility | Owner and evidence |
|---|---|
| Manifest semantics, compatibility, command registration and updates | Public Spec Kit CLI, invoked in disposable projects against explicit supported refs |
| Required runtime, legal and vendor files; deterministic extension ZIP | Usage Bridge builder and tracked-file allowlist |
| Installed checkpoint, capture, report and check behavior | Usage Bridge installed-archive integration tests |
| Published bytes, source SHA, checksums, attestations and immutable candidate history | Usage Bridge release verifier and trusted Actions job evidence |
| Community catalog acceptance | Spec Kit's upstream submission review; local submission remains explicit and opt-in |

The install suite checks native rejection of an unsupported manifest schema and
absence of a registered extension after failure. Forced reinstall uses
`extension add --force` and checks preservation of local configuration and reports.
A separate native `extension update` test installs an older fixture version, then
updates through a local catalog to the exact supplied release ZIP. It checks the
installed version and manifest, preserved user data, and unchanged target digest.
Both release host lanes run these checks before their `upgrade` evidence is accepted.

The fixture's local `release-verification.json` records a host ref and archive name
for diagnostics. It is not the signed release proof; the pipeline separately binds
job results, source SHA, run/attempt and artifact digests. Installation acceptance
cannot replace offline archive bounds, product allowlists or release provenance.
No local release gate was removed on the basis of native feature overlap.

An extension ZIP uses `extension.yml`. A bundled extension ships within Spec Kit's
host package. A Spec Kit bundle uses `bundle.yml` and has native build/validate
commands; those commands do not build this extension's release archive. Unreleased
source may inform future designs only with its exact SHA recorded, independently
of mandatory stable-host evidence. No official nightly artifact is assumed.

### Verification of published assets

`verify-release.yml` downloads those four assets, verifies their digests, contents,
and signed provenance, then exercises installation and runtime commands again on
Linux and Windows. Only the completed verification artifact feeds merge-back and
submission. Missing maintainer attestations leave submission pending; dispatch
Release follow-through from `main` with the stable tag, exact SHA/digest and human
review evidence to retry it. A manual release event runs detection and verification
without enabling merge-back or submission.

### Catalog issue

Stable submission opens an issue in `github/spec-kit` using the reviewed
extension form. The download URL is the tag-pinned stable ZIP plus its SHA-256.
The body does not apply upstream labels and does not write the upstream catalog.
Missing real-project, documentation, or security attestation leaves a prepared
body and does not open an issue. Prereleases are refused. An untriaged owned
issue for an older version is updated in place. The same version is reused. A
triaged issue is not rewritten; a newer verified stable release opens one
superseding issue.

The reviewed upstream snapshot is commit
`ae5ade7234be5cb1d975f736c4e06dd46d1326d6`. Those files are data. They are not
executed and they do not change our rules.

Follow-through is separate from publication. A submission failure does not
remove a verified release, and merge-back does not run downloaded release code.
Branch deletion happens only after the release pull request has merged.

Exit `0` is success or reuse, `2` is a policy or input block, `3` is an API
failure, and `4` means a required file or credential is missing. The first
production candidate and the first stable release stay a deliberate maintainer
dispatch after these checks.
