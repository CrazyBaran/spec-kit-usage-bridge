# Usage Bridge — token-usage for Spec Kit

> [!WARNING]
> **Work in progress — not usable yet.** This repository currently contains only the design brief.
> There is no release, no installable extension and no stable interface. Everything below describes
> the **planned** v0.1 and may change during design.

A [Spec Kit](https://github.com/github/spec-kit) extension that bridges
[token-usage](https://github.com/Wicked-Sick-Ltd/token-usage) into the Spec-Driven Development
flow: an automatic, per-phase, per-feature **token and cost audit** across sessions, straight from
agent transcripts.

## Why

Spec Kit tells you *what* each phase produced — `constitution`, `specify`, `clarify`, `plan`,
`tasks`, `implement`. It doesn't tell you what each phase **cost**, or whether splitting phases into
separate sessions to keep context small actually saves tokens. Usage Bridge answers:

- How many tokens (input, output, cache read/write) and how much estimated cost did each phase of
  this feature consume?
- How is that spread across sessions and re-runs, including subagents?
- What did starting a fresh session cost in context re-loading, and did the split pay off?

## Planned v0.1

- **Automatic capture** after every agent turn via Spec Kit agent runtime events (`stop`) — a plain
  script, no LLM calls, nothing to remember to run.
- **Real usage from transcripts**, including prompt-cache tokens and subagent rollups.
- **Per-feature totals across sessions**, with duplicate calls from resumed sessions removed.
- **Feature attribution** from Spec Kit's active feature and the git branch.
- **Report file next to the spec**: `token-usage.md` (readable) and `token-usage.json` (machine).
- Commands:
    - `/speckit.usage-bridge.report` — per-feature table, or `--all` for a cross-feature rollup
    - `/speckit.usage-bridge.check` — verifies the integration, hooks and environment
    - `/speckit.usage-bridge.capture` — runs automatically; can be invoked to force a refresh

**Supported agents (planned):** Claude Code first. Cursor is designed for but not implemented in v0.1.

**Out of scope for v0.1:** budgets and finance exports, run-vs-run benchmarking, dashboards,
MCP server, Cursor/Cowork runtimes.

## Relation to other extensions

| Extension | Focus | Together with Usage Bridge |
|---|---|---|
| [token-analyzer](https://github.com/coderandhiker/spec-kit-token-analyzer) | Deliberate benchmark runs, preset/model comparison, quality scoring | Use it to benchmark; Usage Bridge measures everyday work |
| [Cost Tracker](https://github.com/Quratulain-bilal/spec-kit-cost) | Budgets, model re-pricing, finance exports (token counts entered manually) | Usage Bridge can supply the counts |
| [token-budget](https://github.com/tinesoft/spec-kit-token-budget) | Reducing context and artifact size | It reduces tokens; Usage Bridge shows whether it worked |

## Installation (not available yet)

Once the first release exists, installation is planned to be:

```bash
specify extension add usage-bridge --from https://github.com/<org>/spec-kit-usage-bridge/archive/refs/tags/v0.1.0.zip
```

Requirements (planned): Spec Kit with agent runtime events, Python 3.9+, git, Claude Code integration.

## Status and roadmap

| Stage | Status |
|---|---|
| Design brief | ✅ [`docs/prompts/usage-bridge-bootstrap-prompt_1.md`](docs/prompts/usage-bridge-bootstrap-prompt_1.md) |
| Design spec (brainstorming) | 📝 In review — [`docs/superpowers/specs/2026-09-29-usage-bridge-v0.1-design.md`](docs/superpowers/specs/2026-09-29-usage-bridge-v0.1-design.md) |
| Implementation plan | ⏳ Not started |
| v0.1.0 implementation & tests | ⏳ Not started |
| First release | ⏳ Not started |

Development follows the [Superpowers](https://github.com/obra/superpowers) workflow: brief →
brainstorming → spec (`docs/superpowers/specs/`) → plan (`docs/superpowers/plans/`) → test-driven
implementation.

## Credits

Usage Bridge is built on [token-usage](https://github.com/Wicked-Sick-Ltd/token-usage) by
Craig Fletcher / Wicked Sick Ltd (MIT), which does the transcript parsing, attribution and pricing.
A pinned, unmodified copy will be bundled with the extension. Usage Bridge adds the Spec Kit
integration: automatic capture, per-feature aggregation across sessions and reports next to specs.

Usage Bridge is a community project and is not affiliated with GitHub, Spec Kit or Wicked Sick Ltd.

## License

To be decided (MIT planned, matching token-usage).
