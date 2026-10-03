# Repository maintenance

Development-only tooling protects `main` of `CrazyBaran/spec-kit-usage-bridge`.
It is not part of the shipped extension. The tool refuses any other repository and
makes no API call at all for one.

## What is enforced

A single repository ruleset named `usage-bridge-main` targets `refs/heads/main`:

- Changes must arrive through a pull request, with **zero required approvals**
  (the sole maintainer can merge their own PRs).
- Review conversations must be resolved before merging.
- Seven required status checks, each bound to the GitHub Actions app:
  `lint`, `test (ubuntu-latest, 3.9)`, `test (ubuntu-latest, 3.x)`,
  `test (windows-latest, 3.9)`, `test (windows-latest, 3.x)`,
  `integration (ubuntu-latest)`, `integration (windows-latest)`.
- Branches must be up to date with `main` before merging (strict status checks).
- Force pushes (non-fast-forward) and deletion of `main` are blocked.
- No bypass actors are configured.

Two repository settings are also ensured: auto-merge is enabled and merge commits
are allowed (releases rely on merge commits; linear history is never required).

The Actions app id is discovered from the check runs on `main`, never assumed. If the
seven contexts do not all come from exactly one app with slug `github-actions`, the
tool stops with an error and changes nothing.

## Inspect (dry run)

Inspection is the default and performs only GET requests:

```text
python tools/configure_repository.py main --repo CrazyBaran/spec-kit-usage-bridge
```

Requires an authenticated `gh` CLI with admin authority on the repository.

## Apply

```text
python tools/configure_repository.py main --repo CrazyBaran/spec-kit-usage-bridge --apply
```

Planned writes run in order; none is retried. After they finish the tool re-reads the
repository, the owned ruleset and the effective rules on `main`, and reports
`verified: true` only if that read-back matches the policy. A successful HTTP write
alone never counts as verified. Re-running after success plans nothing, and the owned
ruleset is updated in place rather than duplicated. The tool never deletes or relaxes
protections to recover from an error.

## Reading the report

The report is printed as JSON and saved to
`build/repository-config/main-<UTC timestamp>.json` (git-ignored; override with
`--report-dir`). It holds no credentials.

- `mode`: `dry-run` or `apply`.
- `actions_app_id`: the discovered GitHub Actions app id, or `null`.
- `planned`: the exact operations (`method`, `path`, `payload`) the tool would run.
- `applied`: operations that succeeded. After a partial failure this still lists the
  earlier writes.
- `verified`: whether the observed state matches the policy. Expect `false` in a dry
  run before the first apply.
- `problems`: what differs from the policy.
- `errors`: blockers or failures. Exit code is 1 if any exist, or if `--apply` did not
  verify; otherwise 0.

## Scope and limits

Only the `usage-bridge-main` ruleset and the two settings above are touched. Other
rulesets and unrelated settings are never modified. If another ruleset or rule would
block solo merge-commit merges (required approvals, linear history, no merge method),
the tool reports it as a blocker rather than editing it.

Repository admins can still change settings or edit the ruleset itself. Enforcement
here targets everyone without admin authority over rules; it is not a defense against
an admin who chooses to alter it.

## When CI job names change

The required contexts are `REQUIRED_CONTEXTS` in `tools/repository_policy.py`. Update
that tuple (and the tests) to match the new job names, merge the change, let CI run on
`main` so check runs with the new names exist, then run the dry run and `--apply`
again. The existing owned ruleset is merged forward, adding the new contexts; remove
stale ones in the repository settings UI as an admin.
