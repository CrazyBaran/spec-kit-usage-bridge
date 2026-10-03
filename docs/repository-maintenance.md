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
`build/repository-config/main-<UTC timestamp>.json` under the repository root
(git-ignored; override with `--report-dir`, a relative path resolves against the
repository root). It holds no credentials.

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
rulesets, classic branch protection and unrelated settings are never modified. The tool
also reads classic branch protection on `main` (when `main` is protected). If another
ruleset, rule or classic protection would block solo merge-commit merges (required
approvals, code owner review, last-push approval, required reviewers, linear history,
`update`, merge queue, required deployments, or no merge-commit method), the tool
reports it as a blocker rather than editing it. On the owned ruleset those settings
are reconciled to the policy instead.

Repository admins can still change settings or edit the ruleset itself. Enforcement
here targets everyone without admin authority over rules; it is not a defense against
an admin who chooses to alter it.

## When CI job names change

Adding a new CI job is safe: it is not required until you add it to the policy.
Renaming or removing a *required* job is not safe to do in one step. Once protection
is active, a pull request that renames a required job never reports the old context,
so it can never merge (there is no bypass), and the tool cannot help: the ruleset
union never removes contexts, and planning refuses until check runs with the new
names exist on `main`.

Do it in this order:

1. **Before merging the rename PR**, an admin edits the `usage-bridge-main` ruleset
   (repository settings UI, or `gh api` `PUT repos/<owner>/<repo>/rulesets/<id>`) to
   remove the old required contexts and add the new ones, each bound to the GitHub
   Actions app (integration id 15368).
2. Merge the rename PR; CI now runs with the new names on `main`.
3. Update `REQUIRED_CONTEXTS` in `tools/repository_policy.py` (and the tests) through a
   normal pull request.
4. Re-run the dry run (`python tools/configure_repository.py main --repo
   CrazyBaran/spec-kit-usage-bridge`) and confirm `verified: true`.
