# Bootstrap prompt — `spec-kit-usage-bridge` v0.1.0

> Paste everything below the line into **Claude Code**, started in an **empty git repository**, with the
> [Superpowers](https://github.com/obra/superpowers) plugin installed
> (`/plugin install superpowers@claude-plugins-official`).
> Section 8 (**Parked questions**) is intentionally open — brainstorming must resolve it first.
> Facts in section 3 were verified on 2026-09-29 against spec-kit v1.0.12 (main `8d3f64c`) and
> token-usage v0.6.0 / main 0.6.1 (`f407827`).

---

## 0. How you must work (Superpowers process — mandatory)

This is an **architectural** task (new project, no existing code). Follow the Superpowers
architectural path end to end; do not skip or merge gates:

1. **brainstorming** — read this prompt and the reference repos (read-only, section 3.0), then walk
   me through **every item in section 8 (Parked questions), one at a time**, proposing 2–3 options
   with trade-offs and a recommendation for each. Record my answer before moving on. Where I say
   "your call", take the recommendation and mark it *assumed* in the spec. Do **not** re-open
   decisions in sections 1–2 unless you find evidence that contradicts them — then say so explicitly.
   Then present the design in sections and get my approval per section.
2. Write the approved spec to `docs/superpowers/specs/YYYY-MM-DD-usage-bridge-v0.1-design.md`,
   run the spec self-review, commit, and **stop for my review of the file**.
3. **using-git-worktrees** — isolated worktree/branch; verify a clean baseline (empty test suite passes).
4. **writing-plans** — `docs/superpowers/plans/YYYY-MM-DD-usage-bridge-v0.1.md`: bite-sized tasks with
   exact paths, code and verification steps. Stop and let me choose the execution mode.
5. **subagent-driven-development** (default) or **executing-plans**, with
   **test-driven-development** for every task (red → green → refactor, commit per task).
6. **requesting-code-review** between tasks; **receiving-code-review** when acting on feedback.
7. **verification-before-completion** — run the full acceptance checklist (section 7) with evidence.
8. **finishing-a-development-branch** — present merge/PR options.

Hard rules: no implementation, scaffolding or dependency install before the written spec is
approved. Evidence over claims. YAGNI — v0.1 ships only section 5. Nothing is pushed, published
or posted anywhere external without my explicit confirmation in chat.

Style reference: token-usage itself is developed with Superpowers — its
`docs/superpowers/specs/*-design.md` files are good examples of the spec depth expected.

## 1. Goal

Build a **Spec Kit extension** (`usage-bridge`) that automatically records how many tokens (and
estimated cost) each phase of the Spec-Driven Development flow consumed —
`/speckit.constitution`, `specify`, `clarify`, `plan`, `tasks`, `analyze`, `checklist`,
`implement` — **per feature, across all sessions**, and writes the result next to the feature's spec.
It reuses the parser from [Wicked-Sick-Ltd/token-usage](https://github.com/Wicked-Sick-Ltd/token-usage)
(MIT) by **vendoring** it — not by installing the token-usage Claude Code plugin.

Primary users: an engineering team using Spec Kit with Claude Code, some developers on Windows.
Primary question answered: *"What did this feature's SDD flow cost, per phase, and did splitting
phases into separate sessions (for context-size optimisation) pay off?"*

### 1.1 Identity (decided)

| Field | Value |
|---|---|
| Extension ID | `usage-bridge` (verified free in `catalog.json` + `catalog.community.json`, 2026-09-29) |
| Display name | **Usage Bridge — token-usage for Spec Kit** |
| Repository | `spec-kit-usage-bridge` (org/visibility: parked Q20) |
| Manifest / catalog description (<200 chars) | Bridges token-usage into Spec Kit: automatic per-phase, per-feature token & cost audit of the SDD flow across sessions, from agent transcripts. |
| GitHub "About" description | Spec Kit extension bridging token-usage into SDD: automatic per-phase, per-feature token & cost audit across sessions, straight from agent transcripts. |
| GitHub topics | `spec-kit`, `speckit-extension`, `spec-driven-development`, `sdd`, `token-usage`, `llm-tokens`, `token-tracking`, `llm-cost`, `ai-observability`, `claude-code`, `developer-tools`, `python` |
| GitHub website field | empty until listed; then `https://speckit-community.github.io/extensions/usage-bridge` |
| Manifest tags | `tokens`, `cost`, `observability`, `token-usage`, `claude-code` |
| Commands | `speckit.usage-bridge.capture`, `speckit.usage-bridge.report`, `speckit.usage-bridge.check` |
| Python package | `usage_bridge` |
| Project config file | `usage-bridge-config.yml` |

Naming rules: one-verb command names; keep "token-usage" visible in name/description/README for
discoverability (`specify extension search token`); credit upstream prominently.

### 1.2 Positioning vs existing community extensions (verified from their manifests/READMEs)

| Extension | What it does | Data source | Relation to Usage Bridge |
|---|---|---|---|
| `token-analyzer` | Per-step baselines, run-vs-run compare, artifact quality scoring | **Headless CLI JSON** piped into a script; optional agent hooks after specify/plan/tasks/implement | Partial overlap (per-phase tokens). It = deliberate benchmarks; we = automatic everyday telemetry. Do not build compare/quality scoring. |
| `cost` (Cost Tracker) | $ cost, per-feature/phase budgets, model re-pricing, CSV/JSON finance export | **Manual** token entry (`track input_tokens=…`); transcript parsing listed as future work | Complementary — we produce the numbers it lacks. Do not build budgets/finance export (parked Q26). |
| `token-budget` | Compacts artifacts, scopes per-phase reading, artifact size report | File-size estimates | None — it reduces, we measure. |
| `token-economy` | Evidence routing, rtk/Headroom savings | External tools | None. |
| `analytics` | Wall-clock per command, LLM-estimated human time | 16 mandatory agent hooks (timestamps) | None today; token/cost is an unchecked roadmap item there — watch it. |

**What only Usage Bridge adds** (must-haves; everything else is scope creep):
1. Automatic, deterministic capture via Spec Kit **`events:`** (`stop`) — no LLM, no manual step.
2. **Actual** transcript usage incl. cache read/write and **subagent rollups**.
3. **Per-feature totals across sessions** with cross-file `requestId` dedup.
4. **Feature attribution** (active feature from `.specify/feature.json` + git branch), output next to the spec.
5. **Session re-priming cost** — evidence whether session splitting pays off.
6. Integration **check**, so silent no-capture is detected.

## 2. Decisions already made (and alternatives rejected — don't re-litigate without new evidence)

| Decision | Rejected alternatives and why |
|---|---|
| **Vendor** `token_usage.py` + `pricing.json`, pinned, unmodified | *Install the token-usage plugin from the extension* — plugins are user-scoped (`~/.claude`, marketplace), extensions are project-scoped, and there is no install-time hook. *Call a user-installed plugin at runtime* — undocumented install path, version drift across devs, can't be guaranteed. *Copy its SKILL.md into `.claude/skills/`* — unmanaged by Spec Kit, survives `extension remove`, collides with the plugin, misses Cursor. |
| Capture via **`events: stop`** (deterministic script) | *Agent-executed `hooks: after_*`* — cost tokens, unreliable, fire mid-turn so the phase's tail is missing. |
| Re-express token-usage's report skill as our own **Spec Kit command** (`report`) | Registering an MCP server — no manifest field for it. |
| Branch-per-integration logic lives **in our script** (detect runtime from stdin payload) | Manifest has no per-integration `events:`; `.specify/integration-events.yml` is user-owned and replaces the whole set. |
| **Warn, don't block** on unsupported integrations (`check` command + one-time hook; setup scripts may enforce) | Native install blocking — not supported (`requires.tools` is informational only). |
| Output next to the spec, aggregated **per feature across sessions** | Per-session reports only. |

## 3. Verified background

### 3.0 Reference material (clone into a scratch folder outside this repo, read-only)
- `https://github.com/github/spec-kit` — read `extensions/EXTENSION-DEVELOPMENT-GUIDE.md`,
  `EXTENSION-API-REFERENCE.md`, `EXTENSION-USER-GUIDE.md`, `EXTENSION-PUBLISHING-GUIDE.md`,
  `extensions/template/`, `src/specify_cli/events/__init__.py`,
  `src/specify_cli/integrations/{claude,cursor_agent}/__init__.py`, `src/specify_cli/integrations/base.py`
  (`select_script_variant`), `templates/commands/*.md` (hook blocks).
- `https://github.com/Wicked-Sick-Ltd/token-usage` at tag `v0.6.0` (and main for comparison) —
  `scripts/token_usage.py`, `data/pricing.json`, `hooks/hooks.json`, `skills/report/SKILL.md`,
  `docs/cursor-adapter.md`, `tests/`.
- Community catalog: `extensions/catalog.community.json` in spec-kit, and
  `https://speckit-community.github.io/extensions/all-extensions`.

### 3.1 Spec Kit extension mechanics
- Manifest `extension.yml`: `schema_version: "1.0"`,
  `extension{id,name,version,description,author,repository,license,homepage?}`,
  `requires{speckit_version, tools[]}`, `provides{commands[], templates[], scripts[], config[]}`,
  `hooks`, `events`, `tags`, `defaults`. Command names must match `^speckit\.<ext-id>\.<name>$`;
  aliases must stay in the same namespace. At least one command/hook/event/template/script required.
- **`hooks:`** (`before_/after_` × `constitution, specify, clarify, plan, tasks, implement, analyze,
  checklist, taskstoissues`) are **agent-executed**: core command templates tell the agent to emit
  `EXECUTE_COMMAND:` for mandatory (`optional: false`) hooks and run them. They cost tokens.
- **`events:`** (agent runtime events) are **deterministic**. Canonical names only:
  `session_start, pre_tool_use, post_tool_use, session_end, user_prompt_submit, stop`
  (no `SubagentStop` equivalent). Handler fields: `command` (required), `matcher?`, `timeout?` (s).
  `specify extension add/remove` re-renders them into the agent's native config via a generated
  dispatcher `.specify/events.py` — Claude: `.claude/settings.json` (`Stop`, `UserPromptSubmit`, …,
  command prefixed with `"${CLAUDE_PROJECT_DIR}/.specify/events.py"`); Cursor: `.cursor/hooks.json`
  (`stop`, `beforeSubmitPrompt`, …). Other event-capable integrations: codex, copilot, gemini, qwen,
  opencode, devin, tabnine, vibe.
- The dispatcher locates the event's command template, reads its frontmatter `scripts:`, and runs
  the script **directly** (no LLM), with the agent's hook payload on **stdin**, cwd = project root,
  inner timeout = handler timeout. It does **not** pass the integration name. For `py` scripts it
  resolves the Python interpreter portably (fixes `python3` vs `python` on Windows). A `py`-only
  `scripts:` entry is chosen as fallback when the project's script type is `sh` or `ps`. Script paths
  are confined to the project tree and anchored at `.specify/extensions/<id>/`.
- Stdout per integration: plain passthrough for Claude; **suppressed** for Cursor (plain text breaks
  its JSON hook protocol). Our handlers print nothing.
- Extension commands are rendered per integration — Claude and Cursor get **skills**
  (`.claude/skills/…`, `.cursor/skills/…`). `{SCRIPT}` and `$ARGUMENTS` placeholders are supported.
- `requires.tools` is **informational only** (`specify extension info`); nothing is enforced at
  install. No install-time hook for extension code. No manifest field for MCP servers.
- Installed integrations: `.specify/integration.json` (`installed_integrations`, `default_integration`).
- Local dev install: `specify extension add <path> --dev`; zip: `--from <url>`.
- `specify extension update` compares against a catalog that **allows installs**; config files are
  backed up and restored. The public community catalog is discovery-only. Private catalogs:
  `specify extension catalog add`.
- **Feature identity in current Spec Kit:** branch creation/numbering is no longer core — it lives
  in the bundled optional **`git` extension** (`before_specify` hook, sequential or timestamp
  numbering, configurable `branch_template`). Core resolves the active feature from
  `SPECIFY_FEATURE` / `SPECIFY_FEATURE_DIRECTORY` env or the persisted
  **`.specify/feature.json`** (`feature_directory`; `SPECIFY_FEATURE_NO_PERSIST` disables it).
  So "branch = feature" is only true when the git extension is used.
- Events feature: fixes appear from v0.15.x; Windows/`pwsh`, script-path confinement and stdin fixes
  landed through the 1.0.x line → see parked Q16 for the minimum version.

### 3.2 Claude Code hook payload (Stop)
stdin JSON includes `session_id`, `transcript_path`, `cwd`, `hook_event_name` (and
`stop_hook_active`). Transcripts: `~/.claude/projects/<cwd-slug>/<session-id>.jsonl`, subagents in
`<session-id>/subagents/agent-*.jsonl` (+ `.meta.json`). Separate working directories (worktrees)
get separate project folders.

### 3.3 token-usage internals we rely on
- Stdlib-only, Python ≥3.9. `scripts/token_usage.py` (~4.4k lines) + `data/pricing.json`.
- **Layout constraint:** `bundled_pricing_path()` = `Path(__file__).parent.parent / "data" /
  "pricing.json"` → the vendored copy **must keep** `scripts/token_usage.py` + `data/pricing.json`
  as siblings-of-parent. A user overlay may exist at `$XDG_CONFIG_HOME/token-usage/pricing.json`
  (merged by `load_pricing()`) — decide whether to honour it (parked Q19).
- `parse_session(transcript_path)` → chronological **segments**
  `{label, start_ts, by_model, prompt, subagents}`; a new segment starts at each user prompt with
  `<command-name>/…</command-name>` (**sticky**: later plain prompts stay with the active command);
  Cowork `Skill` tool uses also start segments. Dedup by `requestId` **within one file only**.
  Subagents are rolled into the segment active when each agent started.
- Useful functions: `load_pricing`, `normalize_usage`, `cost_usd`, `aggregate`, `iter_jsonl`,
  `sum_transcript`, `projects_dir`, `cached_summary` (mtime-keyed cache under
  `~/.cache/token-usage/index`).
- Env overrides (use them for **hermetic tests** and to avoid writing into users' caches):
  `TOKEN_USAGE_PROJECTS_DIR`, `TOKEN_USAGE_LEDGER_DIR`, `TOKEN_USAGE_CURSOR_DIR`, `XDG_CONFIG_HOME`.
- CLI: `report, json, hook, cursor-hook, history, insights, top_consumers, dashboard, live, export`;
  `--runtime {claude,cursor,auto}`.
- Cursor adapter: payloads carry `conversation_id`, `generation_id`, `workspace_roots`,
  `transcript_path`, optional **undocumented** cumulative token fields; SQLite `tokenCount` often 0;
  results labelled `partial` / `activity-only`. Upstream uses `subagentStart/Stop`, which Spec Kit
  cannot map.
- None of this is a documented API → pin, isolate behind `tu_compat.py`, contract-test.

## 4. Architecture (baseline — brainstorming may change it)

```
spec-kit-usage-bridge/
├── extension.yml
├── README.md  CHANGELOG.md  LICENSE  THIRD_PARTY_NOTICES.md
├── config-template.yml                   # → .specify/extensions/usage-bridge/usage-bridge-config.yml
├── commands/
│   ├── capture.md                        # event target; frontmatter scripts: py → capture entrypoint
│   ├── report.md                         # /speckit.usage-bridge.report (agent presents table)
│   └── check.md                          # /speckit.usage-bridge.check
├── scripts/python/
│   ├── capture.py  report.py  check.py   # thin entrypoints (never raise; exit 0)
│   ├── usage_bridge/                     # our package
│   │   ├── runtime.py                    # detect runtime from stdin payload (claude | cursor | unknown)
│   │   ├── discovery.py                  # transcripts for this repo (+ configured worktree dirs)
│   │   ├── attribution.py                # speckit segments → phase/feature; cross-file dedup
│   │   ├── timeline.py                   # per-stop snapshot of active feature (5.1)
│   │   ├── metrics.py                    # totals, re-priming cost, /compact lines
│   │   ├── render.py                     # md + json writers (schema-versioned)
│   │   ├── config.py  log.py
│   │   └── tu_compat.py                  # the ONLY module importing vendored token_usage
│   └── vendor/token_usage/               # upstream layout preserved (see 3.3)
│       ├── scripts/token_usage.py
│       ├── data/pricing.json
│       ├── LICENSE
│       └── VENDOR.json                   # repo, tag, commit, sha256 per file
├── tools/update-vendor.py
├── tests/
│   ├── fixtures/                         # synthetic transcripts (5.9)
│   ├── golden/                           # expected token-usage.md/json
│   └── test_*.py
├── docs/  (superpowers specs/plans, limitations.md, release.md)
└── .github/workflows/{ci.yml,release.yml}
```

Flow: turn ends → Claude `Stop` → `.specify/events.py` → `capture.py` (stdin payload) → detect
runtime → discover transcripts → parse (vendored) → keep `/speckit.*` segments → dedup across
files → attribute to feature → write `specs/<feature>/token-usage.md` + `.json`. Silent, exit 0.

Baseline manifest (fill during implementation):

```yaml
schema_version: "1.0"
extension:
  id: usage-bridge
  name: "Usage Bridge — token-usage for Spec Kit"
  version: "0.1.0"
  description: "Bridges token-usage into Spec Kit: automatic per-phase, per-feature token & cost audit of the SDD flow across sessions, from agent transcripts."
  author: "<parked Q20>"
  repository: "https://github.com/<org>/spec-kit-usage-bridge"
  license: "MIT"
requires:
  speckit_version: ">=<parked Q16>"
  tools:
    - { name: claude, required: false }
    - { name: git, required: false }
provides:
  commands:
    - { name: speckit.usage-bridge.capture, file: commands/capture.md, description: "Refresh token-usage audit (runs on agent stop)" }
    - { name: speckit.usage-bridge.report,  file: commands/report.md,  description: "Token usage audit per feature / phase / session" }
    - { name: speckit.usage-bridge.check,   file: commands/check.md,   description: "Check integration, hooks and environment" }
  config:
    - { name: usage-bridge-config.yml, template: config-template.yml, description: "Usage Bridge settings", required: false }
events:
  stop: { command: speckit.usage-bridge.capture, timeout: 30 }
hooks:
  before_specify: { command: speckit.usage-bridge.check, optional: false, description: "One-time capture sanity check" }
  after_implement: { command: speckit.usage-bridge.report, optional: true, prompt: "Show token usage audit for this feature?" }
tags: [tokens, cost, observability, token-usage, claude-code]
```

## 5. v0.1 scope — functional requirements

### 5.1 Capture (event `stop`)
- Read stdin JSON (cap size); `runtime.py`: `transcript_path` + `session_id` → **claude**;
  `conversation_id`/`generation_id` → **cursor** (v0.1: log + no-op); anything else → no-op.
- Discover **all** transcripts of this repo under the Claude projects dir (+ subagents), plus extra
  dirs from config (worktrees / other checkouts).
- Parse via `tu_compat` → keep segments whose label starts with `/speckit.` (normalise skills-style
  names, parked Q13); others → `unattributed`.
- **Cross-file dedup by `requestId`** (resumed sessions can duplicate calls).
- **Feature attribution** (final rule: parked Q8/Q9). Baseline, in priority order:
  1. **Attribution timeline** we record ourselves: on every `stop`, append
     `{session_id, timestamp, feature_directory (from .specify/feature.json / env), git branch}` to a
     small state file; segments are attributed by timestamp. Works with and without the git extension
     and for sessions split across days.
  2. Git branch recorded in transcript entries (branch of the segment's *last* entry, because the
     branch may be created during `/speckit.specify`), mapped `NNN-name` ↔ `specs/NNN-name/`.
  3. Otherwise `unattributed`.
- Write per-feature `token-usage.md` and `token-usage.json` (**schema-versioned**) atomically
  (temp file + rename); skip write if content unchanged (avoid git noise).
- Performance: well under the event timeout (target < 5 s for ~200 transcripts); reuse an
  mtime/size-keyed cache (parked Q14).
- **Never** raise, never write to stdout, always exit 0; log to `.specify/extensions/usage-bridge/logs/`.
- Privacy: store only metadata and counts — no prompt text by default (parked Q5).

### 5.2 Report content (per feature)
- Rows per phase; sub-rows per session and per re-run. Columns: sessions, calls, input, output,
  cache read, cache write, est. cost, models, subagents, first/last timestamp.
- Totals; `unattributed` row; **session re-priming cost** (formula: parked Q12) and a verdict line
  on session splitting; `/compact` calls as their own line.
- Header: vendored token-usage version, pricing source, generation time, runtime, data completeness
  (`complete` / `partial`).
- Pricing disclaimer (API-equivalent estimate; subscription plans aren't billed per token).

### 5.3 Command `/speckit.usage-bridge.report [feature|--all]`
Frontmatter `scripts: py: scripts/python/report.py`; body = re-expressed token-usage report skill,
SDD-scoped: run `{SCRIPT}`, show the table verbatim, add 1–2 sentences (most expensive phase,
re-priming cost, anything from `insights`), keep the disclaimer. `--all` = cross-feature rollup
(average cost per phase). May shell out to the vendored CLI for `insights`.

### 5.4 Command `/speckit.usage-bridge.check` + `before_specify` hook
Checks and remediation text for: supported integration in `.specify/integration.json`
(else: "run `specify integration install claude` or `specify extension disable usage-bridge`");
native `Stop` entry present in `.claude/settings.json` (catches `--events false`); Python version;
git available; Claude projects dir found and readable; last successful capture time. After the
first pass writes a marker and becomes a no-op. Must be scriptable (non-zero exit on failure when
run directly) so team setup scripts can enforce it.

### 5.5 Config `usage-bridge-config.yml`
Enable/disable, output location, extra transcript dirs, pricing overrides (negotiated/cloud rates),
include-prompt-previews (default off), log level.

### 5.6 Vendoring
- Vendored files are **never edited**; `VENDOR.json` pins repo, tag, commit, sha256 per file.
- Preserve upstream layout (3.3). Keep upstream `LICENSE`; list in `THIRD_PARTY_NOTICES.md`.
- `tu_compat.py` sets `TOKEN_USAGE_*` env/paths so we never write into the user's
  `~/.cache/token-usage` unless configured (parked Q14).

### 5.7 Update process (token-usage → extension → developers)
- `tools/update-vendor.py <tag>`: download tag archive, replace only the vendored files, update
  `VENDOR.json`, refuse if local sha256 drifted, print upstream CHANGELOG between tags for the PR.
- CI: sha256 check of vendored files; contract tests on `tu_compat` (shape of `parse_session`,
  `load_pricing`, `aggregate`); golden-file tests; CLI `--help` checks for subcommands we call;
  readable `pricing.json` diff.
- Breakage policy: keep the old pin; adapt only in `tu_compat.py`; open an upstream issue.
- Versioning: patch = vendor bump without behaviour change; minor = report content/numbers change;
  major = output file/schema change. `CHANGELOG.md` entry names the token-usage version.
- Release: tag → `release.yml` builds the zip and GitHub release → catalog entry updated (parked
  Q21) → devs run `specify extension update usage-bridge`. Native hooks point at the dispatcher, so
  they survive updates; per-feature files are rebuilt on the next Stop with the new logic.
- Document the whole flow in `docs/release.md`. Automation (Renovate/scheduled Action) is v0.2.

### 5.8 Runtime seam for Cursor (design only)
Interfaces in `runtime.py`/`discovery.py` must allow a later Cursor path: `user_prompt_submit` event
to label `/speckit.*` turns, token-usage `cursor-hook` ledger as source, `git branch --show-current`
for attribution, rows marked `partial`, no subagents.

### 5.9 Tests (TDD, pytest; runtime stays stdlib-only)
Hermetic (temp HOME + `TOKEN_USAGE_*` env). Synthetic fixtures: specify→plan in one session;
phases split across sessions; resumed session duplicating `requestId`s; `/speckit.specify`
creating the branch mid-segment; subagent rollup; `/compact`; `/clear`; plain prompts after a
command (sticky); two features in one session; non-speckit work; malformed/partial JSONL lines;
Windows paths; project dir with spaces; project **without** the git extension (feature from `.specify/feature.json` only); feature switched mid-session. Plus: contract tests on `tu_compat`; golden-file md/json;
capture prints nothing and exits 0 on garbage/empty/oversized stdin; atomic write; integration test
that runs `specify init --integration claude` in a temp dir, `specify extension add <repo> --dev`,
asserts the `Stop` entry in `.claude/settings.json`, pipes a sample payload into the generated
dispatcher and asserts the output files; `extension remove` cleans the entry.

## 6. Out of scope for v0.1
Cursor runtime implementation (seam only); Cowork runtime; MCP server; dashboards/HTML;
budgets/alerts and finance export (Cost Tracker covers it); run-vs-run comparison and quality
scoring (token-analyzer covers it); Jira/Confluence export; publishing to the community catalog;
Renovate/automated vendor bumps.

## 7. Acceptance checklist (verification-before-completion)
- [ ] `specify extension add <repo> --dev` (and from the release zip) succeeds in a fresh
      `specify init --integration claude` project; `Stop` handler present in `.claude/settings.json`.
- [ ] `specify extension info usage-bridge` shows commands, events and informational tools.
- [ ] `specify extension remove usage-bridge` removes the handler and commands.
- [ ] Real run: `/speckit.specify` + `/speckit.plan` in session 1, `/speckit.tasks` in session 2 →
      `specs/<feature>/token-usage.md` shows 3 phases, 2 sessions, re-priming cost for session 2;
      totals reconcile with `token_usage.py json` for both transcripts after dedup.
- [ ] Resumed session does not double count.
- [ ] Capture silent, exit 0, < 5 s; errors only in the log file.
- [ ] `/speckit.usage-bridge.check` flags a project without the Claude integration and a project
      with events disabled.
- [ ] CI green on ubuntu + windows, Python 3.9 and latest; vendored sha256 check green.
- [ ] README (install, config, how numbers are computed, limitations, relation to token-analyzer /
      Cost Tracker, credit to token-usage), CHANGELOG, THIRD_PARTY_NOTICES, `docs/release.md`,
      `docs/limitations.md`.

## 8. Parked questions (resolve in brainstorming, one at a time)

**Scope & users**
1. v0.1 **Claude Code only**, or Claude + Cursor? (Recommendation: Claude only; seam per 5.8.)
2. Is the Cowork (Claude desktop) runtime in scope at all? It segments on `Skill` tool use and may lack branch info.
3. Who consumes the output — individual devs, team lead reports, finance? Drives JSON schema and whether cost or tokens lead.

**Output & privacy**
4. Output location: `specs/<feature>/token-usage.{md,json}` (committed with the spec) vs `.specify/usage-bridge/` (gitignored)? Merge-conflict risk when two devs work on one feature.
5. Committed files: include prompt previews / session IDs / usernames, or strip them? Any GDPR / internal policy concern about committing usage data?
6. If committed, whose usage counts — each dev only has their own transcripts, so they'd overwrite each other's numbers. Per-author files (`token-usage.<user>.json`) + merged view, or a merge strategy?
7. Markdown table layout and exact JSON schema (versioned) — agree before golden files.

**Attribution rules**
8. Attribution source: accept the baseline order in 5.1 (own timeline from `.specify/feature.json` → transcript `gitBranch` → unattributed)? Verify with real transcripts that Claude Code entries carry `gitBranch` (not in token-usage fixtures). Where does the timeline state live (`.specify/extensions/usage-bridge/state/`, gitignored?) and how is history before install handled (branch-only backfill)?
9. Does the team use the Spec Kit `git` extension (branch per feature) and which `branch_template` / numbering? How to map non-standard names, `SPECIFY_FEATURE_DIRECTORY` custom locations, and `SPECIFY_FEATURE_NO_PERSIST`?
10. Sticky attribution: plain follow-ups after `/speckit.plan` count toward plan — accept? How to label `/speckit.implement` spread over many sessions (per task batch?).
11. Does `/clear` start a new transcript file? (Believed yes — verify.) How to show it.
12. "Re-priming cost" formula — first request's cache-creation tokens? All requests until first cache hit? Something else?
13. Normalise skills-mode invocations (`/speckit-plan`, `$speckit-plan`) to the same phase labels?

**Mechanics**
14. Re-parse everything on every `stop`, or reuse token-usage's `cached_summary` index / our own mtime cache? Where may the cache live (user `~/.cache` vs project `.specify/`)? Acceptable latency?
15. Background subagents still running at `Stop` — accept late attribution on the next Stop/report?
16. Minimum `requires.speckit_version`: `>=1.0.0`, or pin to the tested `>=1.0.12` given the events fixes through 1.0.x?
17. Keep the mandatory `before_specify` check hook (a few tokens once) or rely on README + manual `check`?
18. `capture` appears as a slash command automatically — acceptable, or rename/describe it as internal?
19. Pricing: vendored `pricing.json` + config overrides — honour the user's `$XDG_CONFIG_HOME/token-usage/pricing.json` overlay too? Actual rates (Anthropic direct vs Bedrock/Azure/Vertex)? USD only?

**Distribution & maintenance**
20. Repo home: which GitHub org hosts `spec-kit-usage-bridge` (company org vs personal, public vs private)? Author string. Licence — MIT to match upstream?
21. Private Spec Kit catalog now (needed for `specify extension update`) or `--from` zip for v0.1? Submit to the community catalog later?
22. Integrate with the team's existing Spec Kit tooling/bootstrap script — should it run `check` and fail setup?
23. Pin `v0.6.0` tag or a main commit (0.6.1)? Upstream 0.7 (dashboard/live/export) is in design — wait or not?
24. Contribute upstream later (cross-file dedup, branch in segments, integration test)?
25. CI provider (GitHub Actions assumed); Windows runner required?

**Ecosystem**
26. Cost Tracker interop: v0.1 only keeps `token-usage.json` easy to import; v0.2 either (a) `export --format cost` producing Cost Tracker ledger entries, (b) contribute "accept transcript path / Usage Bridge JSON" to `Quratulain-bilal/spec-kit-cost`, or (c) neither. Keep our own cost estimate once Cost Tracker is wired in?
27. Recommend `token-analyzer` side-by-side in the README (benchmarks vs everyday telemetry), or stay silent?
28. Upstream credit wording; notify the token-usage author / ask for a link back?

## 9. Deliverables of this session
1. Approved spec in `docs/superpowers/specs/`.
2. Approved plan in `docs/superpowers/plans/`.
3. Working extension v0.1.0 on a branch with passing CI, README, CHANGELOG, THIRD_PARTY_NOTICES.
4. `docs/limitations.md` listing every *assumed* answer from section 8, and `docs/release.md`.
5. Nothing pushed or published without my explicit confirmation.
