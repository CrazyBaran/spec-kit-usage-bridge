# Usage Bridge — token-usage for Spec Kit

Usage Bridge connects [token-usage](https://github.com/Wicked-Sick-Ltd/token-usage) to
[Spec Kit](https://github.com/github/spec-kit), turning local agent history into a
per-feature, per-phase usage audit. It vendors an unmodified, pinned token-usage copy for
transcript parsing, segmenting and pricing, and adds runtime adapters, Spec Kit phase
recognition, feature attribution, explicit checkpoints and merged contributor reports.

**v0.2.1** reads Claude Code transcripts, local Codex rollouts and best-available Cursor
history/activity. It writes `token-usage.md` beside each feature's spec, with measured
tokens and API-equivalent cost estimates where the source and pricing permit. The table
below summarizes what Usage Bridge currently supports for each runtime.

## What Usage Bridge v0.2.1 supports

| Capability | Claude Code | Codex | Cursor |
|---|---|---|---|
| Local sources | Claude project transcripts | `CODEX_HOME/sessions`, `archived_sessions`, configured extra directories | Bridge hook ledgers, owned exports, then available local SQLite history |
| Token measurement | Recorded request usage, including cache buckets | Conservatively reconciled token counters | Measured usage where present; otherwise activity only |
| Phase reports and explicit feature checkpoints | Supported | Supported; manual continuation verified | Supported |
| Request counts and session-splitting estimates | Supported when required evidence is available | Unavailable | Unavailable |
| Native capture | Claude `Stop` hook path when runtime events are configured and delivered | Automatic delivery manual/unverified; use manual refresh | Automatic delivery manual/unverified; use manual refresh |

Claude subagent requests join the phase active when the subagent started. Codex child
history is handled conservatively to avoid counting proven inherited usage twice.
Codex counter observations and Cursor segments are not API request counts.

Windows tests verify Spec Kit installation, dispatcher compatibility and removal for all
three integrations. Synthetic events do **not** establish authenticated native delivery.
See [native verification](docs/native-smoke.md) for the tested scope.

## Install and configure

Requirements: **Spec Kit 1.0.12+**, **Python 3.9+**, and a supported Spec Kit integration.
Git is recommended for branch attribution and worktree discovery.

### Install from source today

As of **2026-10-02**, the public repository has no published GitHub releases; the v0.2.1
release and latest catalog URLs return 404. Public release publishing is planned.
Use a source checkout until release assets are available.

Clone [this repository](https://github.com/CrazyBaran/spec-kit-usage-bridge). From the root
of an existing Spec Kit project, replace `PATH_TO_USAGE_BRIDGE_CHECKOUT` with the absolute
path to that checkout:

```bash
specify extension add "PATH_TO_USAGE_BRIDGE_CHECKOUT" --dev
```

To refresh a source installation, update that checkout and rerun the command in each
consuming project. This renders the v0.2.1 checkpoint command and workflow hook.

### One or several integrations

Install the integrations you use in the consuming project before adding the extension:

```bash
specify integration install claude
specify integration install codex
specify integration install cursor-agent
```

All three are declared safe to install together in Spec Kit v1.0.12. `cursor-agent` is
its integration key; `cursor` is the Usage Bridge runtime name. Cursor's editor CLI is
distinct from the authenticated `cursor-agent` CLI.

For an installed integration, `install` does not refresh its files or options. Use
`upgrade` when runtime events need to be enabled:

```bash
specify integration upgrade claude --integration-options="--events true"
specify integration upgrade codex --integration-options="--events true"
specify integration upgrade cursor-agent --integration-options="--events true"
```

Syntax is checked against the
[Spec Kit v1.0.12 implementation](https://github.com/github/spec-kit/tree/v1.0.12/src/specify_cli/integrations).
Configuring events does not establish automatic delivery. Check the extension:

```powershell
python .specify/extensions/usage-bridge/scripts/python/check.py --verbose
```

Use `python3` instead of `python` where required by your shell. Required check failures
exit 1; optional discovery warnings do not. A successful check or recent capture does
not prove automatic native delivery.

### Published installation, once assets exist

The planned catalog route below is **not currently usable** because the public catalog
asset has not been published:

```bash
specify extension catalog add --name usage-bridge --install-allowed https://github.com/CrazyBaran/spec-kit-usage-bridge/releases/latest/download/catalog.json
specify extension add usage-bridge
specify extension update usage-bridge
```

Direct archive installation uses `specify extension add usage-bridge --from RELEASE_ZIP_URL`.
Replace `RELEASE_ZIP_URL` with an actual published archive URL. Catalog updates require
an installed catalog. See the [release guide](docs/release.md) for packaging details.
v0.2.x writes schema v2; upgrade all contributors before sharing new reports.

### Settings

The shared configuration is `.specify/extensions/usage-bridge/usage-bridge-config.yml`.
Use `usage-bridge-config.local.yml` in the same directory for machine-specific paths or
`author.alias`, and keep the local file out of version control. Updates preserve existing
configuration. Settings apply in order: defaults, shared file, local file, then supported
`SPECKIT_USAGE_BRIDGE_` environment overrides.

```yaml
enabled: true
runtimes:
  enabled: [claude, codex, cursor]
  codex:
    extra_dirs: []
  cursor:
    extra_dirs: []
    data_dir: ""
transcripts:
  extra_dirs: []
output:
  dir: "{feature_dir}"
pricing:
  overrides: {}
privacy:
  prompt_previews: false
capture:
  deadline_seconds: 15
log:
  level: info
```

`transcripts.extra_dirs` adds Claude sources; runtime `extra_dirs` adds Codex or Cursor
sources. `runtimes.cursor.data_dir` selects a nonstandard Cursor data directory.
Custom output templates must contain `{feature_dir}` or `{feature_id}` and cannot use
parent traversal (`..`); invalid templates fall back to the feature directory.
See the [configuration template](config-template.yml) for defaults.

## Capture, measurement and attribution

These are separate steps:

- **Discovery** finds local history owned by the checkout. A discovered session need not
  contain token counts, recognized phases or correct feature evidence.
- **Measurement** reads recorded usage. Missing or ambiguous counts remain unavailable;
  a checkpoint cannot recover them.
- **Phase recognition** groups work by observed Spec Kit or extension invocations.
  Ordinary prompts and helper skills remain in their surrounding phase.
- **Feature attribution** uses an explicit binding first, matching capture-timeline
  evidence second, then a resolvable recorded branch. Unresolved work stays unattributed;
  constitution work is project-level.
- **Workflow hooks** request a check before specify, a checkpoint after specify and an
  optional report after implement. They are separate from runtime events.
- **Automatic native capture** requires the agent to deliver the configured event.
  Installed hooks and synthetic dispatch tests do not prove that delivery.

A session started before feature creation can retain an old branch in its history.
Manual capture discovers that history but does not automatically correct its destination.
The after-specify workflow requests a binding for that invocation; it does not establish
an entire-session feature or guarantee capture of later phases.

## Checkpoint ongoing work

A checkpoint binds **one observed phase invocation** to an existing feature directory
inside the checkout. Use it for missing or stale attribution. Later phases need their
own checkpoints when continuing with explicit attribution, including `clarify`, `plan`,
`tasks`, `implement` and recognized extension phases such as `superspec.brainstorm`.
Switching features requires another checkpoint for the new invocation.

### Get the session ID inside Codex

Ask Codex in the session you want to checkpoint to print its shell's `CODEX_THREAD_ID`.
In PowerShell:

```powershell
$env:CODEX_THREAD_ID
```

In Bash:

```bash
printf '%s\n' "$CODEX_THREAD_ID"
```

Copy the value as the session ID. Codex can omit `--runtime` and `--session-id` when the
executing shell supplies `CODEX_THREAD_ID`. If it is absent, obtain a verified native ID;
never guess from the newest transcript or `.specify/feature.json`. Claude and Cursor
require explicit runtime and native session IDs.

### Preview, apply and report

Run these from the consuming project's root **after invoking the relevant phase**.
`SESSION_ID` and `specs/FEATURE_DIRECTORY` are placeholders: replace them with your
verified session ID and an existing feature directory.

```powershell
# Preview the latest observed clarify invocation without saving a binding.
python .specify/extensions/usage-bridge/scripts/python/checkpoint.py --runtime codex --session-id SESSION_ID --feature "specs/FEATURE_DIRECTORY" --phase clarify --latest

# Check the preview's session, invocation timestamp and destination, then apply.
python .specify/extensions/usage-bridge/scripts/python/checkpoint.py --runtime codex --session-id SESSION_ID --feature "specs/FEATURE_DIRECTORY" --phase clarify --latest --apply

# Refresh and print the feature report.
python .specify/extensions/usage-bridge/scripts/python/report.py "specs/FEATURE_DIRECTORY"
```

For a Superspec command use the observed canonical phase, e.g. `--phase superspec.brainstorm`.
A general brainstorming helper skill does not create that Superspec command phase.
Preview the new feature's invocation before applying a feature switch.

Repeated phases need explicit `--latest` or the exact observed invocation timestamp.
**Historical repair is a separate selection**, not a side effect of checkpointing ongoing
work. Replace `INVOCATION_TIMESTAMP` below with the earlier specify invocation's timestamp:

```powershell
python .specify/extensions/usage-bridge/scripts/python/checkpoint.py --runtime codex --session-id SESSION_ID --feature "specs/FEATURE_DIRECTORY" --phase specify --invocation-ts INVOCATION_TIMESTAMP
```

Inspect the preview, then repeat with `--apply` to save and refresh. Bindings preserve
measurement quality, never manufacture tokens, and do not rewrite raw transcripts or
repair another contributor's committed sources. They are private state and do not travel
between machines. If saving succeeds but refresh fails, retry capture; the binding survives.

## Commands and manual refresh

The manifest provides `speckit.usage-bridge.check`, `speckit.usage-bridge.capture`,
`speckit.usage-bridge.checkpoint` and `speckit.usage-bridge.report`. Spec Kit renders their
invocation syntax for each integration. The Python entrypoints also work directly:

```powershell
python .specify/extensions/usage-bridge/scripts/python/check.py --verbose
python .specify/extensions/usage-bridge/scripts/python/capture.py
python .specify/extensions/usage-bridge/scripts/python/report.py --all
python .specify/extensions/usage-bridge/scripts/python/report.py --all --json
```

`report.py` refreshes before printing. Pass a feature directory or unique name for one
report; no argument selects the active or most recently active feature. `--all` includes
project work and unattributed coverage in the cross-feature rollup. Checkpoint previews
change neither bindings nor feature reports; `--apply` saves and refreshes.
Capture is silent in hook mode and always exits 0; use diagnostics and logs to detect
capture failures rather than relying on its exit status.

## Read the numbers

Unknown token buckets are unavailable (`null` in JSON), **not zero**. Explicit measured
zeros remain zero. Reports distinguish exact, partial and activity-only measurement from
scan completeness. Measured-token subtotals exclude unavailable usage; a complete scan
does not make missing counters measurable.

Claude requests are deduplicated across files and streamed entries. Codex reconciliation
subtracts cache reads from input and keeps reasoning tokens within output; resets and
uncertain inherited history reduce coverage. Cursor prefers bridge-owned ledgers over
owned exports and local SQLite state.

Unpriced models retain their measured tokens while complete cost remains unavailable.
Known-cost subtotals include priced usage only and may be unavailable when nothing is
priced. Pricing overrides map model prefixes to confirmed USD-per-million-token rates,
for example `{input: 5.0, output: 25.0, cache_read: 0.5}`. These are illustrative rates,
not a recommendation for any particular model; never infer a price from its name.

Costs use bundled tables and overrides. They are **API-equivalent estimates**, not
subscription charges or billing statements. Compaction summarization calls absent from
transcripts are not costed; not every billing option is modeled. Claude session-splitting
estimates print their assumptions. Codex/Cursor lack that verdict and request/repriming counts.

## Files and privacy

Default output:

```text
specs/FEATURE_DIRECTORY/
  token-usage.md
  token-usage/
    AUTHOR.MACHINE.json
```

These stand for your real feature directory, author slug and short machine ID. Markdown
merges contributor sources deterministically; there is no merged JSON file (`report.py
--json` prints that view). `git user.name` supplies the default author identity, overridden
by a local `author.alias`. Source files can be shared through Git.

Private bindings, state, caches, Cursor ledgers and `logs/usage-bridge.log` live under
`<git common dir>/usage-bridge/`, shared by worktrees with bindings scoped to their checkout.
Outside Git the fallback is `.specify/extensions/usage-bridge/.runtime/`.

Reports identify authors and sessions and include models, timestamps, usage and costs.
Prompt previews default off. Private state can contain paths and command/phase evidence.
Enabling previews adds text to bridge-owned data; disabling them removes text from ledgers
and caches on refresh, leaving original agent files intact. Review files before sharing.

## Troubleshooting and limitations

- **No sessions or usage:** run an agent turn, check `--verbose`, and confirm local paths
  and enabled runtimes. Cloud-only Codex history is unavailable until stored locally.
- **Missing phase:** invoke it first. Checkpoints require observed invocation evidence;
  a helper skill is not a substitute for a Superspec command.
- **Wrong feature or unattributed usage:** preview and apply that invocation's checkpoint.
  Repair earlier phases separately.
- **Ambiguous invocation:** use its timestamp for repeated phases. Conflicting Codex
  local/archived histories must be resolved first; timestamps cannot bypass that conflict.
- **No automatic refresh:** run capture or report manually. Codex/Cursor delivery is
  unverified; inspect configured events and private logs.
- **Partial or interrupted refresh:** retry; large first scans may need a warm cache.
  Source failures retain prior snapshots. Features in another worktree need capture in
  a checkout where the destination exists.
- **Unavailable price:** tokens may still be measured. Add confirmed overrides or keep
  the estimate unavailable.

Formats and Cursor sources vary by version and OS. macOS/Linux authenticated native
delivery remains unverified. See [limitations and assumptions](docs/limitations.md) for
accounting, platform and privacy boundaries.

## Verified v0.2.1 behavior

A user-operated Windows Codex continuation test verified manual checkpointing of
`superspec.brainstorm`, saved bindings, report generation and identical totals across two
refreshes. Measured tokens stayed visible for the unpriced `gpt-6.1-sol` model. The outputs
do not isolate checkpointing as the cause of the initial attribution change.

It did **not** validate automatic native capture, automatic after-specify delivery,
feature switching, historical specify repair or real Claude/Cursor delivery. Detailed
evidence and test qualifications are in [v0.2.1 verification](docs/v0.2.1-verification.md),
with delivery procedures in [native smoke documentation](docs/native-smoke.md).

## Related projects and credits

[token-analyzer](https://github.com/coderandhiker/spec-kit-token-analyzer) focuses on
benchmarks and model comparison; [Cost Tracker](https://github.com/Quratulain-bilal/spec-kit-cost)
on budgets and finance exports; [token-budget](https://github.com/tinesoft/spec-kit-token-budget)
on reducing context size. Usage Bridge records everyday work.

[token-usage](https://github.com/Wicked-Sick-Ltd/token-usage) supplies transcript parsing, segmenting and pricing.
Usage Bridge adds adapters, Spec Kit phase recognition, capture, deduplication, attribution
and reports. The vendored token-usage copy is unmodified and pinned to
`f4078277e79c007993e0cb595bb95f924a2a8777`;
see [third-party notices](THIRD_PARTY_NOTICES.md).

Usage Bridge is a community project and is not affiliated with GitHub, Spec Kit or Wicked
Sick Ltd.

## License

Usage Bridge is licensed under the [MIT License](LICENSE). Vendored token-usage retains
its own [license](scripts/python/vendor/token_usage/LICENSE); see
[third-party notices](THIRD_PARTY_NOTICES.md) for attribution and licensing details.
