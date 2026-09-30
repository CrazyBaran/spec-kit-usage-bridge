# Usage Bridge — token-usage for Spec Kit

Usage Bridge connects [token-usage](https://github.com/Wicked-Sick-Ltd/token-usage) to
[Spec Kit](https://github.com/github/spec-kit). It captures Claude Code transcript usage after each turn and writes a
per-feature, per-phase token and estimated cost audit beside the feature's spec. Reports combine sessions and authors,
include subagent usage, and remove duplicate API requests from resumed sessions.

## What it answers

- How many input, output, cache-read and cache-write tokens did each Spec Kit phase use?
- How is usage split across runs, sessions and authors?
- Did splitting phases across sessions appear to save cost after accounting for the context loaded again?

The generated `token-usage.md` is the merged report. Per-author source data lives in
`token-usage/<author>.<machine>.json`. There is no merged JSON file; `report --json` prints the merged view. Reports
contain token counts, costs, model names, timestamps, session ids and author names. They do not contain prompt text or
local paths unless prompt previews are explicitly enabled.

## Install

Requirements: Spec Kit 1.0.12 or later, Python 3.9 or later, and Claude Code integration. Git is recommended for
branch and worktree attribution. Capture is automatic through the Claude `Stop` hook after the extension and Claude
runtime events are configured.

Add the install-allowed catalog and install the extension in a Spec Kit project:

```bash
specify extension catalog add --name usage-bridge --install-allowed https://github.com/CrazyBaran/spec-kit-usage-bridge/releases/latest/download/catalog.json
specify extension add usage-bridge
```

To install directly from a release archive instead, use `specify extension add usage-bridge --from <release zip URL>`.
The catalog route is needed for `specify extension update usage-bridge`.

After installation, check the project integration. In Bash:

```bash
python3 .specify/extensions/usage-bridge/scripts/python/check.py || exit 1
```

In PowerShell:

```powershell
python .specify/extensions/usage-bridge/scripts/python/check.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

The check reports missing Python, Claude integration or runtime events as failures. Transcript discovery and git issues
are warnings. Cursor projects receive a warning because Cursor capture is not supported in v0.1.

## Commands

- `/speckit-usage-bridge-report [feature-id | --all] [--json]` refreshes capture and prints a feature report or a
  cross-feature rollup. With no feature argument it selects the active or most recently active feature.
- `/speckit-usage-bridge-check [--verbose] [--json]` checks the integration and environment. A failure exits 1.
- `/speckit-usage-bridge-capture` forces a manual refresh; normal capture runs after each turn. Hook capture is silent
  and exits 0 so reporting problems do not interrupt the agent.

## Configuration

The installed template is `.specify/extensions/usage-bridge/usage-bridge-config.yml`. It is copied once and is not
overwritten on extension updates. A machine-specific `usage-bridge-config.local.yml` can override settings without
being committed. Environment variables prefixed `SPECKIT_USAGE_BRIDGE_` can also override configuration.

```yaml
enabled: true
output:
  dir: "{feature_dir}"
transcripts:
  extra_dirs: []
pricing:
  overrides: {}
privacy:
  prompt_previews: false
capture:
  deadline_seconds: 15
log:
  level: info
```

`output.dir` supports `{feature_dir}` and `{feature_id}`. Pricing overrides use USD per million tokens, for example
`{input: 5.0, output: 25.0, cache_read: 0.5}` for a model prefix. The deadline is capped at 15 seconds within the
30-second Spec Kit event timeout. The runtime directory is `<git common dir>/usage-bridge/` (or the extension's
`.runtime/` fallback outside git); it holds capture state and logs, not committed reports.

## How numbers are computed

The pinned token-usage library supplies transcript parsing, segmentation and base pricing. Usage Bridge adds Spec Kit
phase recognition, request-level deduplication across files, feature attribution and per-feature reports. Each API
request is counted once using the maximum observed token values across streamed entries. Subagent requests are included
in the phase active when the agent started. Phase runs group the requests between recognized command or skill
boundaries; ordinary prompts remain with the current phase.

Feature attribution uses a capture timeline entry matching the run’s closing request first, then the git branch,
then an unattributed bucket. A missed Stop cannot assign earlier work to a later active feature. `git user.name`
is converted to an author slug by default; `author.alias` can override it. A short machine id keeps two computers from
writing the same author file. The merged Markdown is rebuilt deterministically from the per-author files. After an alias change, overlapping
sessions on the same machine count once using the newest snapshot; historical source files remain intact.

Costs are estimates at the vendored API list prices. Input, output, cache-read and cache-write usage use the upstream
pricing table and cache multipliers; unknown models are reported as unpriced. The session-splitting verdict compares
observed phase costs with estimated context reload costs and prints its assumptions in the report. It is an estimate,
not a billing statement.

## Related extensions

| Extension | Focus | How it relates to Usage Bridge |
|---|---|---|
| [token-analyzer](https://github.com/coderandhiker/spec-kit-token-analyzer) | Deliberate benchmark runs, preset/model comparison and quality scoring | Use it for benchmarks; Usage Bridge records everyday work. |
| [Cost Tracker](https://github.com/Quratulain-bilal/spec-kit-cost) | Budgets, model repricing and finance exports with manually entered counts | Usage Bridge measures transcript counts that may inform that workflow. |
| [token-budget](https://github.com/tinesoft/spec-kit-token-budget) | Reducing context and artifact size | It reduces token use; Usage Bridge shows observed usage. |

## Limitations

See [limitations and assumptions](docs/limitations.md), including transcript format uncertainty, attribution gaps,
pricing assumptions and author data in committed reports.

## Credits and affiliation

**token-usage does the transcript parsing, segmenting and pricing. Usage Bridge adds Spec Kit capture, attribution and
per-feature reports.** The extension vendors an unmodified token-usage copy at commit
`f4078277e79c007993e0cb595bb95f924a2a8777`; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Usage Bridge is a community project and is not affiliated with GitHub, Spec Kit or Wicked Sick Ltd.

## License

Usage Bridge is licensed under the MIT License; see [LICENSE](LICENSE).

## Project status

| Stage | Status |
|---|---|
| Design brief | Complete |
| Design spec | Complete |
| Implementation plan | Complete |
| v0.1.0 implementation and tests | Complete |
| First release | Prepared; not published |
