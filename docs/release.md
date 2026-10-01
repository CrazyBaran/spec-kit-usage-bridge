# Release and update guide

This guide describes the release workflow for maintainers and installation for Spec Kit users. A release is created
from a version tag after CI passes; creating tags and publishing releases requires maintainer authorization.

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
`.extensionignore`. The catalog entry carries the extension manifest fields, release download URL, documentation,
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
