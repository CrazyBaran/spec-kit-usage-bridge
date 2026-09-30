# Usage Bridge v0.1 — design spec

| | |
|---|---|
| Status | Draft for review — brainstorming completed 2026-09-29 |
| Extension | `usage-bridge` · "Usage Bridge — token-usage for Spec Kit" · v0.1.0 |
| Brief | [`docs/prompts/usage-bridge-bootstrap-prompt_1.md`](../../prompts/usage-bridge-bootstrap-prompt_1.md) |
| Verified against | spec-kit main `8d3f64cd` (1.0.13.dev0; tags v1.0.11, v1.0.12) · token-usage main `f407827` (plugin 0.6.1 + unreleased 0.7) and tag `v0.6.0` · local Claude Code transcripts from versions 2.1.177–2.1.284 (metadata-only survey) · Claude Code documentation |

## Goal

Build a Spec Kit extension that automatically records how many tokens — and an API-equivalent cost estimate —
each phase of the Spec-Driven Development flow consumed, **per feature, across all sessions and developers**, and
writes the result next to the feature's spec. It reuses the transcript primitives and the pricing table of
[token-usage](https://github.com/Wicked-Sick-Ltd/token-usage) (MIT, Craig Fletcher / Wicked Sick Ltd) by vendoring
a pinned, unmodified copy.

It answers: *"What did this feature's SDD flow cost, per phase, and did splitting phases into separate sessions pay
off?"* Audience: developers and tech leads of the many teams that use Spec Kit with Claude Code, some of them on
Windows. v0.1 is done when the checklist in §9 passes.

## Hard constraints

1. Vendored token-usage files are pinned (`VENDOR.json`) and never edited; `tu_compat.py` is the only module that
   imports them.
2. Capture is a deterministic script on the Spec Kit runtime event `stop`: no LLM, stdlib only, Python ≥ 3.9.
3. Capture never disturbs the agent: nothing on stdout/stderr on the hook path, always exit 0, and it finishes inside
   its own deadline. (On timeout the generated dispatcher exits 2, and a Claude `Stop` hook that exits 2 keeps Claude
   working instead of stopping — F9, F18.)
4. Committed output holds counts, tokens, costs, model names, timestamps, session ids and author names — never prompt
   text or local paths. Prompt previews are an explicit opt-in.
5. YAGNI: v0.1 ships exactly what this spec describes.
6. Each workflow step's files are committed and pushed on their own branch. Tags, releases, catalog submissions and
   upstream issues need explicit confirmation.

## Investigation findings

Facts verified during brainstorming that the design depends on. "F" ids are referenced throughout.

**Claude Code transcripts** — survey of 223 main and 1,150 subagent transcripts on the author's machine; only
structure, counts and command names were read.

- **F1** `gitBranch`, `cwd`, `sessionId` and `timestamp` are present on 100% of user/assistant/system entries,
  subagent entries included. token-usage reads none of them.
- **F2** Spec Kit invocations are skills-style: `/speckit-specify` (89×), `/speckit-plan` (86×), … and extension
  commands `/speckit-<ext>-<cmd>`. The dot form `/speckit.plan` occurs **0** times. Built-in commands appear the same
  way (`/model` 63×, `/compact`).
- **F3** Hook-executed extension skills run inside phases (`attributionSkill` values `speckit-git-feature`,
  `speckit-git-commit`, `speckit-agent-context-update`).
- **F4** Current Claude Code resumes into the same file: 0 files with more than one `sessionId`, 0 cross-file duplicate
  `requestId`s. `--fork-session` creates a new session id (docs), so cross-file duplicates remain possible. Inside one
  file, one API request is written as several entries (streamed blocks) sharing a `requestId`.
- **F5** Every subagent transcript has a `.meta.json` (`agentType`, `description`, `model`, `parentAgentId`,
  `spawnDepth`, `toolUseId`, …). 370 of the 1,150 live nested under `<session>/subagents/workflows/…` (Workflow tool).
- **F6** Compaction is an in-file `system` entry with `subtype: compact_boundary` and `compactMetadata`
  `{trigger: manual|auto, preTokens, postTokens, …}`. The summarisation request itself has **no usage entry**; the next
  request writes the compacted context to cache (e.g. 43,942 tokens).
- **F7** The first request of a fresh `/speckit-*` session already reads from the prompt cache (n = 88: median 34k
  cache-read, 26k cache-write tokens) — system prompt and tools are shared across sessions.
- **F8** Usage objects carry `cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`,
  `service_tier`, `speed`, `inference_geo` and `server_tool_use.*`. All observed values were `standard`.

**Spec Kit** (main `8d3f64cd`, v1.0.12)

- **F9** The generated dispatcher `.specify/events.py` is invoked by a native Claude hook entry
  `"<python>" "${CLAUDE_PROJECT_DIR}/.specify/events.py" <command> <event> <timeout>` marked `__speckit_event__`
  (native timeout = handler timeout + 5 s). It caps stdin at 1 MiB, runs the command's `py` script with
  cwd = project root and the payload on stdin (UTF-8 pinned since v1.0.6, #4337), propagates the script's exit code,
  passes Claude stdout through — and **exits 2 on timeout or on its own errors**.
- **F10** For Claude and Cursor, commands are rendered only as skills: `.claude/skills/speckit-<ext>-<cmd>/SKILL.md`,
  invoked as `/speckit-<ext>-<cmd>`. Skill frontmatter is rebuilt from a whitelist (`name`, `description`,
  `compatibility`, `metadata`, plus `argument-hint` for Claude) and Claude injects `user-invocable` and
  `disable-model-invocation: false`, so an extension command cannot be hidden.
- **F11** `{SCRIPT}` for a `py` script renders as `<interpreter> <script>`, the interpreter being resolved at install
  time: project `.venv` → `python3` → `python` (skipping the Windows Store stub) → `sys.executable`.
- **F12** Active feature: `SPECIFY_FEATURE_DIRECTORY` env → `.specify/feature.json` `{"feature_directory": "<relative
  path>"}` → error. The file is rewritten only when the value changes; `SPECIFY_FEATURE_NO_PERSIST` disables writes.
  Spec Kit's managed `.specify/.gitignore` ignores `feature.json`; everything else under `.specify/extensions/<id>/`
  is tracked.
- **F13** git extension 1.0.1: mandatory `before_specify` → `speckit.git.feature`; sequential (`NNN`) or timestamp
  (`YYYYMMDD-HHMMSS`) numbering; `branch_template` placeholders `{author}`, `{app}`, `{number}`, `{slug}`;
  `branch_prefix`.
- **F14** Installing copies the whole extension directory minus `.extensionignore` patterns. Config templates are
  copied once and never overwritten. `requires.speckit_version` is enforced at install; `requires.tools` entries
  (`name`, `version`, `required`) are informational. Hooks support priority/optional/prompt but have no run-once
  semantics. A `--from` archive may hold `extension.yml` at its root or inside exactly one top-level folder.
- **F15** `specify extension catalog add --install-allowed <url>` writes the project-scoped
  `.specify/extension-catalogs.yml`; the community catalog is discovery-only; `specify extension update` needs an
  install-allowed catalog.
- **F16** Runtime events exist since v0.15.0 (#3704); events fixes followed up to v1.0.6; v1.0.10 only moved the
  module. Runtime events of the Claude integration are toggled by the integration option `--events true|false`.

**Claude Code documentation**

- **F17** `/clear` fires `SessionStart` with `source: "clear"` and "saves the previous conversation" — a new
  transcript is implied, not stated.
- **F18** A `Stop` hook exiting 2 "prevents Claude from stopping"; hooks run synchronously by default.
- **F19** Inside a git worktree, `${CLAUDE_PROJECT_DIR}` stays at the checkout where the session started, while the
  hook input `cwd` follows the worktree.
- **F20** `Stop` input: `session_id`, `prompt_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, ….
  Hook parity of the desktop Code tab and IDE extensions with the CLI is not documented.

**token-usage** (main `f407827`)

- **F21** `parse_session()` starts a segment at every `<command-name>` prompt **and at every `Skill` tool use** (the
  code is not limited to Cowork), keeps plain prompts sticky, dedups by `requestId` within one file (per-field max),
  rolls subagents into the segment active when each agent started (`rglob` on main; v0.6.0 uses a non-recursive
  `glob` and misses F5's nested files), and returns per-segment aggregates only — no request ids, no per-request
  timestamps.
- **F22** Pricing = bundled `data/pricing.json` (USD per million tokens: `input`, `output`, optional `cache_read`)
  merged with a personal overlay `$XDG_CONFIG_HOME/token-usage/pricing.json`. Cache reads cost 0.1 × input unless an
  explicit rate is given; 5-minute cache writes 1.25 × input, 1-hour writes 2.0 × input. Unknown models are unpriced.
  No fast-mode, long-context, data-residency or web-search pricing.
- **F23** Library-safe: no import side effects, stdlib only, Python 3.9+. Upstream writes caches only under
  `TOKEN_USAGE_LEDGER_DIR` (default `~/.cache/token-usage`).

**Corrections to the brief.** The brief's section-2 decisions all stand; these statements were contradicted:

| # | Brief | Correction |
|---|---|---|
| C1 | Keep segments whose label starts with `/speckit.` | Real labels are `/speckit-<cmd>` (F2) → normalisation is mandatory (D13) |
| C2 | Skill-tool segments are a Cowork concern | Every Skill tool use starts a segment (F21) → nested skills fold back into the phase (§3.1) |
| C3 | `token_usage.py` ~4.4k lines with `bundled_pricing_path`, `--runtime` | True for main only; v0.6.0 has 1,866 lines (D23) |
| C4 | "Never raise, exit 0" | Also finish inside a deadline — the dispatcher's exit 2 blocks Claude's stop (F9, F18) |
| C5 | `/compact` calls as their own line | The summary call has no usage (F6) → compaction events plus reload cost (§3.5) |
| C6 | Parse, then dedup across files | `parse_session` has no request-level data (F21) → Approach B (§1) |
| C7 | YAML config file | PyYAML is not guaranteed on the resolved interpreter (F11) → stdlib subset parser (§5.2) |
| C8 | Logs in `.specify/extensions/usage-bridge/logs/` | All runtime state lives in `<git common dir>/usage-bridge/` (D-S2) |
| C9 | token-usage 0.7 "in design" | Implemented on main, not yet tagged (D23) |

## Decisions

All 28 parked questions of the brief were answered explicitly — none is *assumed*.

| Id | Decision |
|---|---|
| D1 | Claude Code only (CLI, desktop Code tab, IDE extensions — same transcripts). Cursor payloads are detected, logged and ignored; `check` warns. Seam per brief §5.8. |
| D2 | Cowork is out of scope (no Spec Kit integration, nothing triggers capture); documented. |
| D3 | Audience: developers and tech leads. **Tokens lead**; estimated cost is a secondary column. The splitting verdict is cost-weighted, and the report says so. JSON for tools, no finance fields. |
| D4 | Output next to the spec, committed; files written only when their content changes; `output.dir` can redirect. |
| D5 | Committed data: counts, tokens, costs, models, timestamps, session ids and a **named author** (slug of git `user.name`, overridable alias). No prompt text, no local paths. Prompt previews opt-in. Limitations note on employee-monitoring policy. |
| D6 | Per-author source files keyed by author + machine id, one writer each; the merged md is regenerated from all sources and is deterministic. |
| D7a | md layout: header → headline → per-phase table → runs table → session splitting → disclaimer (§4.1). |
| D7b | Per-author JSON shaped session → runs (§4.2). No merged JSON file; `report --json` prints the merged view. |
| D8 | Attribution: own timeline → git branch → unattributed. Pre-install history is backfilled by branch; each run records `attributed_by`. |
| D9 | Must work for many teams: a config-free dynamic branch resolver (§3.2), `NNN-slug` as the primary case. A regex override is out of scope. |
| D10 | Sticky until the next command; only core-phase skills start a phase via the Skill tool; runs are numbered; no cross-session carry-over. |
| D11 | Built-in session commands are transparent; `/compact` and `/clear` are recorded as events; user-typed extension commands get their own rows; other commands start "other work". |
| D12 | Re-priming = first request of each non-first session; verdict = avoided carry-over vs re-priming (§3.4). |
| D13 | Normalise `/speckit-x`, `/speckit.x`, `$speckit-x` and Skill `speckit-x`; extension ids resolved via the registry. |
| D14 | Own per-session digest cache; deadline at 50% of the handler timeout. |
| D15 | Late subagent data is accepted; `partial` while a subagent is still running (§3.5). |
| D16 | `requires.speckit_version: ">=1.0.12"`. |
| D17 | Mandatory `before_specify` check; full check every time; one line when healthy. |
| D18 | `capture` is presented as a manual refresh; `report` refreshes before rendering. |
| D19 | Rates: vendored `pricing.json` + team overrides; personal overlay ignored; USD; costs stored at capture time. |
| D20 | Repository github.com/CrazyBaran/spec-kit-usage-bridge (public, personal), author `CrazyBaran`, MIT. |
| D21 | Each release ships the zip and a `catalog.json` as release assets; teams add the catalog once with `--install-allowed`; `--from <zip>` as fallback; community catalog later. |
| D22 | Scriptable `check` plus copy-paste setup snippets; each team decides warn vs fail. |
| D23 | v0.1 vendors token-usage main `f407827`; afterwards only pinned tags (first bump: v0.7.0 when tagged). |
| D24 | Upstream contributions after v0.1; candidates listed in `docs/limitations.md`; nothing posted without explicit OK. |
| D25 | GitHub Actions: {ubuntu, windows} × {Python 3.9, latest}; integration tests on both OSes. |
| D26 | Cost Tracker interop decided after v0.1; our own estimate stays. |
| D27 | README keeps a neutral "relation to other extensions" table. |
| D28 | Credit now (README, vendored LICENSE, THIRD_PARTY_NOTICES, VENDOR.json); a thank-you note to upstream after the release, only with explicit OK. |
| D-A | **Approach B**: our own request-level pass built on vendored primitives; `parse_session` is the reconciliation oracle in tests. |
| D-S2 | Runtime state in `<git common dir>/usage-bridge/`, shared by all worktrees; fallback `.specify/extensions/usage-bridge/.runtime/`. |
| D-S3 | `constitution` runs are project-level and never land in a feature's files. |
| D-S5 | The vendored `insights` CLI is not used in v0.1. |

Rejected approaches for using the vendored code: **A** — `parse_session` in the production path with our own
request-level pass mapped onto its segments by timestamp (double parse, timestamp heuristic, duplicated subagent
logic); **C** — `parse_session` only (cannot provide first-request re-priming, run start/end times or cross-file
dedup — fails C6).

## 1. Architecture

### 1.1 Repository layout

```
spec-kit-usage-bridge/
├── extension.yml
├── config-template.yml            # → .specify/extensions/usage-bridge/usage-bridge-config.yml on install
├── .extensionignore               # keeps dev-only folders out of installed copies (§5.4)
├── .gitignore                     # also becomes the installed copy's ignore file (§5.4)
├── README.md  CHANGELOG.md  LICENSE  THIRD_PARTY_NOTICES.md
├── commands/
│   ├── capture.md                 # event target + manual refresh
│   ├── report.md
│   └── check.md
├── scripts/python/
│   ├── capture.py  report.py  check.py        # entrypoints (§1.3)
│   ├── usage_bridge/
│   │   ├── __init__.py            # __version__
│   │   ├── tu_compat.py           # the only importer of the vendored module (§1.4)
│   │   ├── runtime.py             # payload → claude | cursor | manual | unknown
│   │   ├── paths.py               # P, W, R, author slug, machine id (§2.2)
│   │   ├── discovery.py           # this repository's Claude transcripts (§2.4)
│   │   ├── digest.py              # one pass per session + cache (§2.5)
│   │   ├── phases.py              # events → runs (§3.1)
│   │   ├── timeline.py            # active-feature timeline (§2.3)
│   │   ├── attribution.py         # cross-file dedup; run → feature bucket (§3.2)
│   │   ├── metrics.py             # totals, re-priming, verdict, compactions, completeness (§3.3–3.5)
│   │   ├── render.py              # per-author JSON, merged md, report views, write_if_changed (§4)
│   │   ├── config.py  yamlsub.py  # layered config, stdlib YAML subset (§5)
│   │   └── log.py                 # rotating log file under R
│   └── vendor/token_usage/        # upstream layout preserved (bundled pricing path = ../data/pricing.json)
│       ├── scripts/token_usage.py
│       ├── data/pricing.json
│       ├── LICENSE
│       └── VENDOR.json
├── tools/update-vendor.py
├── tests/
│   ├── builders.py                # synthetic transcript builders (§8.2)
│   ├── golden/
│   └── test_*.py
├── docs/
│   ├── limitations.md  release.md
│   └── superpowers/{specs,plans}/
└── .github/workflows/{ci.yml, release.yml}
```

### 1.2 Units

| Unit | Responsibility | Depends on |
|---|---|---|
| `runtime` | Classify the stdin payload (§2.1); `RuntimeAdapter` protocol (`discover()`, `digest()`), implemented for Claude only | — |
| `paths` | Project root P, work root W, runtime dir R, author slug, machine id (§2.2) | git (optional) |
| `discovery` | Main transcripts of this repository and their subagent files (§2.4) | `paths`, `tu_compat` |
| `digest` | One pass over a session's files → `SessionDigest`; per-session cache (§2.5) | `tu_compat` |
| `phases` | `SessionDigest` → `Run`s (§3.1) | installed extension ids |
| `timeline` | Append and read timeline entries (§2.3) | R |
| `attribution` | Cross-file dedup; run → feature / `project` / `unattributed` (§3.2) | `timeline`, feature dirs |
| `metrics` | Aggregates, re-priming, verdict, compactions, completeness (§3.3–3.5) | `tu_compat` pricing |
| `render` | Per-author JSON, merged md, report outputs, `write_if_changed` (§4) | — |
| `config`, `yamlsub` | Layered configuration (§5.1–5.2) | — |
| `log` | Rotating log under R (§5.3) | — |

Only `render.write_if_changed`, `timeline.append`, the digest cache, `log` and `last-capture.json` write to disk.
Everything between reading digests and rendering bytes is pure and unit-testable.

### 1.3 Entrypoints

`capture.py`, `report.py` and `check.py` stay tiny and use syntax that any Python 3 parses, because `{SCRIPT}` may
resolve to an old project `.venv` interpreter (F11). Each one:

1. sets `sys.dont_write_bytecode = True`;
2. checks `sys.version_info >= (3, 9)` — capture silently exits 0, report and check print one line and exit 1;
3. puts its own directory on `sys.path` and imports `usage_bridge`;
4. runs `main()` inside a catch-all.

Exit codes: capture always 0; report 0 (1 on a usage error); check 0 when healthy, 1 on any failure.

### 1.4 `tu_compat` API

Loads `vendor/token_usage/scripts/token_usage.py` via `importlib.util.spec_from_file_location` under a private module
name. Raises `VendorError` when the file is missing or its sha256 does not match `VENDOR.json` (checked once per
process).

| Function | Vendored counterpart | Notes |
|---|---|---|
| `iter_entries(path)` | `iter_jsonl` | tolerant line reader |
| `is_prompt(entry)`, `prompt_text(entry)` | `is_user_prompt`, `text_of` | |
| `command_name(text)` | `COMMAND_RE` | returns e.g. `/speckit-plan` |
| `normalize(usage)` | `normalize_usage` | → `{input, output, cache_read, cache_5m, cache_1h}` |
| `merge_max(into, flat)` | `max_flat` | streamed duplicates; private upstream helper |
| `agent_start(agent_file, first_ts, meta)` | `_resolve_agent_ts` | private upstream helper |
| `load_rates(overrides)` | `load_pricing` | personal overlay disabled by pointing `XDG_CONFIG_HOME` at a never-created path under R for the call; team overrides merged over bundled rates |
| `cost(by_model, rates)`, `unpriced(by_model, rates)` | `cost_usd`, `unpriced_models` | |
| `projects_root()` | `projects_dir` | honours `TOKEN_USAGE_PROJECTS_DIR` |
| `vendored_info()` | `VENDOR.json` | repo, ref, commit, file hashes |
| `oracle_segments(path)` | `parse_session` | tests only (§8.3) |

Every vendored call runs with `TOKEN_USAGE_LEDGER_DIR` pointing into R, so `~/.cache/token-usage` is never written.
Private helpers are covered by contract tests; if a vendor bump removes one, `tu_compat` re-implements it — all
adaptations to upstream changes live in this module.

## 2. Capture pipeline

Runs on every Claude `Stop` (manifest handler timeout 30 s) and in manual mode (the `capture` command, or `report`
refreshing before it renders).

### 2.1 Entry and runtime detection

1. Read stdin (the dispatcher caps it at 1 MiB) and decode it as UTF-8 with replacement.
2. `runtime.detect()`:
   - a JSON object with string `transcript_path` and `session_id` → **claude**;
   - an object with `conversation_id` or `generation_id` → **cursor**: log "Cursor capture is not supported in
     v0.1" and exit 0;
   - empty input, `{}`, or no stdin → **manual**;
   - anything else → log and exit 0.
3. Load the configuration (§5.1). `enabled: false` → exit 0.
4. Start the deadline clock: `min(capture.deadline_seconds, 15)` seconds (15 s = 50% of the 30 s handler timeout).

### 2.2 Paths and identity

- **P, project root:** the nearest ancestor of the process cwd that contains `.specify/` (the dispatcher already runs
  with cwd = P).
- **W, work root:** `git -C <payload cwd> rev-parse --show-toplevel` when that path is P or is listed by
  `git -C P worktree list --porcelain`; otherwise P. Manual mode uses W = P. (F19: in a worktree session the hook
  fires from the checkout where the session started, while `cwd` follows the worktree.)
- **R, runtime dir:** `<git -C W rev-parse --git-common-dir>/usage-bridge/` — one per clone, shared by every worktree,
  never committed. Outside git: `P/.specify/extensions/usage-bridge/.runtime/`.
- **Author:** `author.alias` (local config or env) → slug of `git config user.name` → slug of the OS user name. Slug =
  lower-case, every run of characters outside `[a-z0-9]` replaced by `-`, trimmed, at most 40 characters.
- **Machine:** the first 6 hex characters of the SHA-256 of the lower-cased host name.

### 2.3 Timeline append (hook mode only)

Before any heavy work, append one JSON line to `R/timeline.jsonl` with a single `write()`:

```json
{"v": 1, "ts": "2026-09-29T10:40:12.345Z", "session_id": "3f9a2c1e-…", "work_root": "D:/repo/.claude/worktrees/x",
 "feature_dir": "specs/001-login", "feature_source": "env", "branch": "001-login"}
```

- `feature_dir`: `SPECIFY_FEATURE_DIRECTORY` from the hook's environment → `W/.specify/feature.json`
  `feature_directory` → `null`; stored relative to W with `/` separators. `feature_source` is `env`,
  `feature.json` or `none`.
- `branch`: `git -C W branch --show-current`; `null` when detached or without git.
- The file is local state (R is never committed), so absolute paths are acceptable here.

### 2.4 Discovery

- **Projects roots:** the grandparent of the payload's `transcript_path` when present, `tu_compat.projects_root()`,
  and `$CLAUDE_CONFIG_DIR/projects` when that variable is set.
- **Candidate project dirs:** entries whose name equals the slug of P or of a worktree path, or starts with that slug
  followed by `-`. (Slug = the absolute path with every non-alphanumeric character replaced by `-`, the way Claude Code
  names its project folders.) Plus every directory in `transcripts.extra_dirs`.
- **Membership:** a main transcript belongs to the repository when the `cwd` of its entries lies inside P or one of its
  worktrees (case-insensitive comparison on Windows). This rejects prefix collisions such as `D--spec-kit` vs
  `D--spec-kit-usage-bridge`.
- **Files of a session:** `<dir>/<session>.jsonl` plus `<dir>/<session>/subagents/**/agent-*.jsonl` (recursive, F5)
  with their `.meta.json` files.

### 2.5 Session digests and cache

`digest.py` reads a session's files once, through `tu_compat`, into a `SessionDigest`:

- `session_id`, `first_ts`, `last_ts`, `last_main_ts`, the set of entry `cwd`s, `gitBranch` changes as
  `[(ts, branch)]`, the count of unreadable lines;
- ordered **events**: user command `(ts, name)`, plain prompt `(ts)`, Skill tool use `(ts, skill)`, compaction
  `(ts, trigger, pre_tokens, post_tokens)`;
- **requests**, one record per `requestId` at its first appearance: `(request_id, ts, model, input, output,
  cache_read, cache_5m, cache_1h, event_index)`. Streamed duplicates are merged per field with `merge_max`, as
  upstream does;
- **subagents**, per agent file: relative path, `agentType`, `spawnDepth`, first and last timestamp, start
  (`agent_start`), whether its last assistant entry has `stop_reason == "end_turn"`, and its requests.

**Cache:** one JSON file per session, `R/cache/<sha1 of the main transcript path>.json`, keyed by `(path, size,
mtime_ns)` of the main transcript and of every subagent file, the digest format version and the vendored sha256.
Digests hold tokens only — pricing is applied later, so a price change never invalidates the cache. Sessions whose key
matches are not re-read. **The payload's own session is digested first**, so the active feature is up to date even
when the deadline is reached.

### 2.6 Combine, compute, write

1. Load the digests of all the repository's sessions (cached or fresh).
2. **Cross-file dedup:** order sessions by `first_ts`; a `requestId` already seen in an earlier session is dropped
   from later ones (the count is logged).
3. `phases` → runs; `attribution` → buckets; `metrics`.
4. **Per-author file:** for every known feature directory (§3.2) **that exists in W** and has runs by this author,
   write `token-usage/<author>.<machine>.json` (§4.2) into the feature's output directory (`output.dir`, default the
   feature directory itself) with `write_if_changed`. Delete this author's own file for a feature that no longer has
   runs by them.
5. **Merged view:** for every such output directory with at least one source file, render `token-usage.md` from all
   `token-usage/*.json` in it (§4.1) and `write_if_changed`. Features that exist only in another checkout are written
   when a capture runs there.
6. Write `R/last-capture.json`:
   `{ts, mode, status: "ok"|"partial"|"error", duration_ms, sessions_parsed, sessions_cached, features_written,
   dropped_duplicates, error}`.
7. Manual mode prints one line, e.g. `Usage Bridge: 2 features updated — 001-login 17.1M tokens (est. $12.14)`.
   Hook mode prints nothing.

### 2.7 Failure behaviour

- Every stage is guarded: an exception is logged with its traceback, recorded in `last-capture.json`, and the process
  exits 0.
- **Deadline:** checked between sessions. Remaining cold sessions are skipped, outputs are written from what is known
  and marked `partial` (reason `deadline`). The cache keeps the progress; the next `Stop` continues.
- **Concurrency:** `R/lock` is created exclusively and counts as stale after 60 s. A second capture waits up to 5 s,
  then skips computing and logs it (its timeline line is already written).
- **Writes:** `write_if_changed` compares content ignoring CRLF/LF differences, writes a temp file in the same
  directory and `os.replace`s it. On a Windows sharing violation it retries once, then logs and skips.
- Nothing is written to stdout or stderr on the hook path.

## 3. Attribution and metrics

### 3.1 From events to runs

Events are processed in file order, per session.

| Event | Effect |
|---|---|
| User command naming a core phase — `/speckit-<p>`, `/speckit.<p>`, `$speckit-<p>` (an optional `<namespace>:` prefix is stripped) | new run of phase `p` |
| User command naming an extension command — `/speckit-<ext>-<cmd>`, `/speckit.<ext>.<cmd>` | new run labelled `<ext>.<cmd>`, where `<ext>` is the longest installed extension id (from `.specify/extensions/.registry`) prefixing the name; no match → the raw label, kind `extension` |
| User command in the built-in list below | transparent; `/compact` and `/clear` are recorded as session events |
| Any other user command (custom, plugin, `/init`, `/review`, …) | new run labelled `other` |
| Plain prompt | joins the current run; with no current run it starts an `other` run |
| Skill tool use of `speckit-<core phase>` | new run of that phase |
| Any other Skill tool use (hook skills, plugin skills, other extension skills) | stays in the current run; the skill name is added to `run.skills` |

- **Core phases:** `constitution`, `specify`, `clarify`, `plan`, `checklist`, `tasks`, `analyze`, `implement`,
  `taskstoissues`. The same normalisation (leading `/` or `$` removed, optional `<namespace>:` prefix stripped,
  `speckit.`/`speckit-` forms equivalent) applies to user commands and to Skill tool names.
- **Built-in (transparent) commands:** `/add-dir /agents /bug /clear /compact /config /context /cost /doctor /effort
  /exit /export /fast /help /hooks /ide /login /logout /mcp /memory /model /permissions /release-notes /resume /rewind
  /status /statusline /terminal-setup /theme /upgrade /usage /vim`. The list is fixed in code; an unknown command is
  "other".
- A request belongs to the run current at its first appearance; a subagent's requests belong to the run current at
  the agent's start.
- A run spans from its first event to its last request, subagents included. Runs left without requests after dedup
  are dropped.
- A session whose first user command is `/clear` is flagged `after_clear`. A new transcript file after `/clear` is
  simply a new session (F17); both representations are supported.

### 3.2 From runs to features

For each run:

1. **Timeline** — the first timeline entry with the same `session_id` and `ts ≥ run.end_ts` (the `Stop` that closed
   the run's last turn). If its `feature_dir` is set, the run belongs to that feature: `attributed_by: "timeline"`.
   `/speckit-specify` lands on the new feature because that `Stop` already sees the rewritten `feature.json`.
2. **Branch** — otherwise the `gitBranch` in effect at the run's last request is resolved against the known feature
   directories (directories under `W/specs/`, plus every `feature_dir` seen in the timeline):
   1. a known directory whose path relative to W equals `specs/<branch>` or `<branch>`;
   2. else a known directory whose name equals the branch's last `/`-segment;
   3. else, if that segment starts with a number (`\d{3,}`) or a timestamp (`\d{8}-\d{6}`), the unique known
      directory whose name starts with the same token followed by `-` or by the end of the name;
   4. no match, or more than one → unresolved.

   Resolved → `attributed_by: "branch"`.
3. Otherwise the run goes to the bucket `unattributed`.

`constitution` runs always go to the bucket `project`. The `project` and `unattributed` buckets are local-only:
`report --all` shows them; they are never written into a feature directory.

### 3.3 Metrics

- **Usage buckets:** `input` (uncached), `output`, `cache_read`, `cache_write_5m`, `cache_write_1h`. **Tokens** = the
  sum of all five.
- **Calls:** unique requests, main thread plus subagents.
- **Cost:** `tu_compat.cost()` over the run's per-model usage with the resolved rates; `null` when nothing is
  priceable; unpriced models are listed.
- **Subagents:** number of agent files with at least one request, plus their usage and cost (a share of the run's
  totals).
- **Models:** per-model calls, usage and cost. A session's **dominant model** is the model of most of its main-thread
  calls.
- **Feature totals** = the sum over all its runs: core phases, extension rows and `other` ("other work").

### 3.4 Re-priming and the splitting verdict

Sessions of a feature are ordered by `first_ts`, then `session_id`.

- **Re-priming(s)** = `input + cache_write_5m + cache_write_1h` of s's first main-thread request, with its cost. It is
  recorded for every session; the md shows it for every session after the feature's first.
- **Verdict(s)** — only when the feature has an earlier session p **by the same author** (the latest one that ended
  before s started; another developer can never continue someone else's session):
  - `carried` = p's final context = `input + cache_read + cache_write_5m + cache_write_1h` of p's last main-thread
    request;
  - `n` = the number of main-thread calls in s;
  - `read_rate` = the cache-read rate of s's dominant model; `write_rate` = its input rate × 2.0 when p used any
    1-hour cache writes, else × 1.25; `ttl` = 3,600 s when p used 1-hour writes, else 300 s;
  - `avoided` = `carried × n × read_rate` + (`carried × write_rate` when `s.first_ts − p.last_ts > ttl`);
  - `net` = `avoided − cost(re-priming(s))`, reported as "splitting saved ≈ $net" or "splitting cost ≈ $|net| more";
  - the feature verdict is the sum over the sessions that have one.
- Printed assumptions: the continued session would have kept p's context cached without compaction; s's re-reading of
  artifacts is not credited to continuing; rates are those of s's dominant model.
- Re-priming and verdicts are computed at capture time from the author's own sessions and stored in their file
  (§4.2), so rendering needs no pricing.

### 3.5 Compactions and completeness

- **Compaction** (F6): `{ts, trigger, pre_tokens, post_tokens, reload_tokens, reload_cost_usd}`, where reload =
  `input + cache_write_5m + cache_write_1h` of the first main-thread request after the boundary. The summarisation call
  itself is not in the transcript and is not costed.
- **Completeness** is `partial` when (a) the deadline skipped sessions of the feature, or (b) a subagent of one of its
  sessions is still running — its last entry is newer than the session's last main-thread entry and its last
  assistant entry's `stop_reason` is not `end_turn`. Otherwise `complete`. Late data arrives with the next
  `Stop`/`report`, in the run where the agent started (D15). Unpriced models do not change completeness; they get a
  cost footnote.

## 4. Output formats

### 4.1 `specs/<feature>/token-usage.md` (generated, committed)

Illustrative example (numbers are not derived from real rates):

```markdown
<!-- Generated by Usage Bridge — do not edit. On a merge conflict keep either side; the next capture regenerates this file. -->
# Token usage — 001-user-login

data as of 2026-10-01 14:20 UTC · token-usage main@f407827 · pricing: bundled (anna, jakub) · runtime: claude · complete · authors: anna, jakub

**17.1M tokens** — input 163k · output 103k · cache read 16.3M · cache write 486k · est. $12.14 · 3 sessions · 5 runs

| Phase | Sessions | Calls | Input | Output | Cache read | Cache write | Est. $ |
|---|--:|--:|--:|--:|--:|--:|--:|
| specify | 1 | 38 | 41k | 18k | 2.9M | 96k | 2.31 |
| plan | 1 | 52 | 60k | 31k | 5.1M | 140k | 3.90 |
| tasks | 1 | 27 | 22k | 12k | 1.8M | 88k | 1.62 |
| implement | 1 | 44 | 35k | 40k | 6.2M | 150k | 4.10 |
| other work | 1 | 9 | 5.0k | 2.0k | 310k | 12k | 0.21 |

## Runs

| Phase | Run | Session | Author | Start → end (UTC) | Calls | Input | Output | Cache read | Cache write | Est. $ | Models | Subagents |
|---|--:|---|---|---|--:|--:|--:|--:|--:|--:|---|--:|
| other work | 1 | 3f9a2c1e | jakub | 09-29 09:05 → 09:09 | 9 | 5.0k | 2.0k | 310k | 12k | 0.21 | claude-opus-5-5 | 0 |
| specify | 1 | 3f9a2c1e | jakub | 09-29 09:10 → 09:40 | 38 | 41k | 18k | 2.9M | 96k | 2.31 | claude-opus-5-5 | 0 |
| plan | 1 | 3f9a2c1e | jakub | 09-29 10:02 → 10:40 | 52 | 60k | 31k | 5.1M | 140k | 3.90 | claude-opus-5-5 | 2 |
| tasks | 1 | b71d04aa | anna | 09-30 08:15 → 08:44 | 27 | 22k | 12k | 1.8M | 88k | 1.62 | claude-sonnet-5-5 | 0 |
| implement | 1 | 9c2e11f0† | jakub | 10-01 13:00 → 14:20 | 44 | 35k | 40k | 6.2M | 150k | 4.10 | claude-opus-5-5 | 3 |

## Session splitting

| Session | Author | Starts with | Re-primed | Carried context avoided | Verdict |
|---|---|---|--:|--:|---|
| b71d04aa | anna | tasks | 54k ($0.20) | — | no earlier session by this author |
| 9c2e11f0 | jakub | implement | 31k ($0.19) | 180k × 38 calls ($5.09) | saved ≈ $4.90 |

Splitting saved ≈ $4.90 across 1 comparable session. Assumes the continued session would have kept the previous
context cached without compaction; the new session's re-reading of artifacts is not credited to continuing; rates of
the new session's main model.

Compactions: 1 (auto) · 967k → 24k · reload 44k ($0.28)

† attributed by git branch (no timeline entry).

> Estimated costs use API list prices from the pinned token-usage pricing table plus team overrides.
> Subscription plans are not billed per token.
```

Rendering rules:

- Rendered **only** from the per-author JSON files in `token-usage/`; the same set of files gives byte-identical
  output, whoever renders it.
- `data as of` = the latest `last_ts` across the sources — never wall-clock time. Times are UTC, `MM-DD HH:MM`.
  Authors, sessions and runs are sorted (runs by `start_ts`, then session id); run numbers are re-counted per phase
  across all authors.
- Numbers: below 1,000 the plain integer, below 10k one decimal (`4.1k`), below 1M whole thousands (`212k`),
  otherwise one decimal (`17.6M`). Costs `$0.00`; unknown cost `—`. Session ids show 8 characters. "Cache write" =
  5-minute + 1-hour writes; "Calls" include subagent calls.
- Pricing in the header: the label of each distinct `generator.pricing_sha256` with the authors using it, e.g.
  `pricing: bundled (anna, jakub)` or `pricing: bundled (anna) · bundled+overrides (jakub)`.
- Phase rows in SDD order (specify, clarify, plan, checklist, tasks, analyze, implement, taskstoissues), then
  extension rows alphabetically, then "other work". `constitution` never appears.
- Footnotes: branch-attributed runs (`†`), unpriced models, `partial` reasons.
- Written with LF line endings; the first line is the "generated, do not edit" comment shown above.

### 4.2 `specs/<feature>/token-usage/<author>.<machine>.json` (per-author source, committed)

```json
{
  "schema": "usage-bridge/feature-usage",
  "schema_version": 1,
  "feature": {"id": "001-user-login", "directory": "specs/001-user-login"},
  "author": {"name": "jakub", "machine": "a1b2c3"},
  "generator": {"usage_bridge": "0.1.0", "token_usage": "main@f407827", "pricing": "bundled",
                "pricing_sha256": "9c1f…"},
  "runtime": "claude",
  "completeness": "complete",
  "partial_reasons": [],
  "data_as_of": "2026-10-01T14:20:05Z",
  "unpriced_models": [],
  "sessions": [
    {
      "session_id": "9c2e11f0-…",
      "first_ts": "2026-10-01T13:00:02Z",
      "last_ts": "2026-10-01T14:20:05Z",
      "after_clear": false,
      "dominant_model": "claude-opus-5-5",
      "main_calls": 38,
      "final_context_tokens": 212044,
      "repriming": {"tokens": 31012, "cost_usd": 0.186},
      "splitting": {"previous_session_id": "3f9a2c1e-…", "carried_tokens": 180412, "calls": 38,
                    "gap_seconds": 181200, "avoided_cost_usd": 5.086, "net_usd": 4.9},
      "compactions": [{"ts": "…", "trigger": "auto", "pre_tokens": 967128, "post_tokens": 24252,
                       "reload_tokens": 43942, "reload_cost_usd": 0.276}],
      "runs": [
        {
          "phase": "implement", "kind": "core", "label": "/speckit-implement", "run": 1,
          "start_ts": "2026-10-01T13:00:02Z", "end_ts": "2026-10-01T14:20:05Z", "attributed_by": "branch",
          "calls": 44,
          "usage": {"input": 35012, "output": 40233, "cache_read": 6204511, "cache_write_5m": 150020, "cache_write_1h": 0},
          "cost_usd": 4.100125,
          "models": {"claude-opus-5-5": {"calls": 44, "usage": {"input": 35012, "…": 0}, "cost_usd": 4.100125}},
          "subagents": {"count": 3, "usage": {"input": 9001, "…": 0}, "cost_usd": 0.62},
          "skills": ["speckit-git-commit"]
        }
      ]
    }
  ]
}
```

- `kind` ∈ `core | extension | other`; `phase` is the canonical phase, the `<ext>.<cmd>` label or `other`; `label`
  keeps the raw invocation. `run` numbers are per phase within this author's data (the md re-counts across authors).
- Run `usage` includes subagents; `subagents` shows their share. Tokens are integers; costs are rounded to 6
  decimals; timestamps are ISO-8601 UTC with `Z`.
- `splitting` is `null` without an earlier session by the same author. `generator.pricing` is `bundled` or
  `bundled+overrides`; `generator.pricing_sha256` hashes the resolved rate table, so differing team rates are visible.
- `main_calls` counts main-thread requests only (the verdict's `n`); run `calls` include subagent requests (here 38
  main + 6 subagent calls).
- `runs[].prompt_preview` (at most 120 characters of the run's first plain prompt) exists only when
  `privacy.prompt_previews: true`.
- Sessions are sorted by `first_ts`; key order is stable; files are written with LF endings.

### 4.3 `report --json` (stdout only)

Schema `usage-bridge/feature-report`, `schema_version: 1`: `feature`, `authors`, `generators`, `completeness`,
`partial_reasons`, `data_as_of`, `totals {sessions, runs, calls, usage, tokens, cost_usd}`,
`phases [{phase, kind, sessions, calls, usage, tokens, cost_usd}]`, `runs` (as §4.2 plus `author` and
`session_id`), `splitting`, `compactions`, `unpriced_models`. It is merged from the same per-author files as the md.

### 4.4 `report --all` (stdout only)

A cross-feature rollup of the feature directories in W:

- one row per feature: sessions, calls, tokens, est. cost, phases present;
- average tokens and cost per phase across the features that have that phase;
- `project` (constitution runs) and `unattributed` — this machine's local data only, clearly labelled as such.

With `--json`: schema `usage-bridge/repo-report` v1 with `features`, `phase_averages`, `project`, `unattributed`.

## 5. Configuration and local state

### 5.1 Configuration

`config-template.yml` is copied on install to `.specify/extensions/usage-bridge/usage-bridge-config.yml` (committed,
shared by the team):

```yaml
enabled: true
output:
  dir: "{feature_dir}"          # where token-usage.md and token-usage/ are written; placeholders {feature_dir}, {feature_id}
transcripts:
  extra_dirs: []                # extra Claude project directories to scan (e.g. another clone)
pricing:
  overrides: {}                 # "<model prefix>": {input: 5.0, output: 25.0, cache_read: 0.5}  (USD per million tokens)
privacy:
  prompt_previews: false
capture:
  deadline_seconds: 15          # capped at 15 (50% of the 30 s event timeout)
log:
  level: info                   # error | warning | info | debug
```

- **Layers**, lowest to highest: built-in defaults ← `usage-bridge-config.yml` ← `usage-bridge-config.local.yml`
  (gitignored, per developer) ← environment variables.
- **Environment:** `SPECKIT_USAGE_BRIDGE_<KEY PATH>` in upper case with `_` separators, for scalar keys, e.g.
  `SPECKIT_USAGE_BRIDGE_ENABLED`, `SPECKIT_USAGE_BRIDGE_OUTPUT_DIR`, `SPECKIT_USAGE_BRIDGE_AUTHOR_ALIAS`,
  `SPECKIT_USAGE_BRIDGE_CAPTURE_DEADLINE_SECONDS`, `SPECKIT_USAGE_BRIDGE_LOG_LEVEL`.
  `SPECKIT_USAGE_BRIDGE_TRANSCRIPTS_EXTRA_DIRS` takes an `os.pathsep`-separated list; `pricing.overrides` is file-only.
- `author.alias` belongs in the local file; `check` warns when it is set in the committed one.
- **Pricing overrides** use the vendored rate fields — `input`, `output`, optional `cache_read` — keyed by model-id
  prefix and merged over the bundled table (longest-prefix matching as upstream). Cache-write rates follow the
  vendored multipliers (× 1.25 for 5-minute, × 2.0 for 1-hour writes); explicit write rates are not supported by the
  vendored formula.
- `output.dir` is resolved relative to W. A team that prefers uncommitted output points it at a path it gitignores
  itself.

### 5.2 `yamlsub` — the supported YAML subset

- block mappings by indentation (spaces only), `key: value`;
- scalars: `true`/`false`, `null`/`~`, integers, floats, single- or double-quoted strings, plain strings;
- block lists of scalars (`- item`), empty flow collections (`[]`, `{}`) and flow mappings of scalars
  (`{input: 5.0, output: 25.0}`);
- `#` comments outside quotes.

Anything else (anchors, multiple documents, block scalars `|`/`>`, nested flow collections) produces a logged warning
and the default value for the affected key. PyYAML is never imported.

### 5.3 Runtime directory R

`<git common dir>/usage-bridge/` (fallback `.specify/extensions/usage-bridge/.runtime/`), never committed:

| Path | Content |
|---|---|
| `timeline.jsonl` | §2.3, append-only |
| `cache/<sha1>.json` | session digests (§2.5); safe to delete — rebuilt on the next capture |
| `logs/usage-bridge.log` (+ `.1`, `.2`) | rotated at 1 MB |
| `last-capture.json` | §2.6 |
| `lock` | §2.7 |

`check` prints R's location.

### 5.4 Installed-copy hygiene

- `specify extension add` copies the repository's root `.gitignore` into `.specify/extensions/usage-bridge/`, where it
  applies to the installed folder. Besides the development entries it contains `*.local.yml`, `.runtime/` and
  `__pycache__/`, and a header comment explains this dual role.
- Entrypoints set `sys.dont_write_bytecode = True`, so running them leaves no untracked files in user projects.
- `.extensionignore` excludes `tests/`, `tools/`, `docs/`, `.github/`, `.superpowers/`, `.worktrees/` and `.claude/`.
  `LICENSE`, `THIRD_PARTY_NOTICES.md` and `vendor/token_usage/LICENSE` stay in every copy (MIT notice requirement).

## 6. Commands, hooks and manifest

### 6.1 `extension.yml`

```yaml
schema_version: "1.0"
extension:
  id: usage-bridge
  name: "Usage Bridge — token-usage for Spec Kit"
  version: "0.1.0"
  description: "Bridges token-usage into Spec Kit: automatic per-phase, per-feature token & cost audit of the SDD flow across sessions, from agent transcripts."
  author: "CrazyBaran"
  repository: "https://github.com/CrazyBaran/spec-kit-usage-bridge"
  homepage: "https://github.com/CrazyBaran/spec-kit-usage-bridge"
  license: "MIT"
requires:
  speckit_version: ">=1.0.12"
  tools:
    - { name: python, version: ">=3.9", required: true }
    - { name: claude, required: false }
    - { name: git, required: false }
provides:
  commands:
    - { name: speckit.usage-bridge.capture, file: commands/capture.md, description: "Refresh the token-usage audit now (also runs automatically after every turn)" }
    - { name: speckit.usage-bridge.report,  file: commands/report.md,  description: "Token usage audit per feature / phase / session" }
    - { name: speckit.usage-bridge.check,   file: commands/check.md,   description: "Check integration, hooks and environment" }
  config:
    - { name: usage-bridge-config.yml, template: config-template.yml, description: "Usage Bridge settings", required: false }
events:
  stop: { command: speckit.usage-bridge.capture, timeout: 30 }
hooks:
  before_specify: { command: speckit.usage-bridge.check, optional: false, description: "Usage Bridge capture sanity check" }
  after_implement: { command: speckit.usage-bridge.report, optional: true, prompt: "Show the token usage audit for this feature?" }
tags: [tokens, cost, observability, token-usage, claude-code]
```

### 6.2 Command files

`commands/capture.md`

```markdown
---
description: "Refresh the token-usage audit now (also runs automatically after every turn)"
scripts:
  py: scripts/python/capture.py
---
Run `{SCRIPT}` from the project root and relay its one-line summary. Do not compute or add numbers.
This command also runs automatically after every agent turn; use it only to force a refresh.
```

`commands/report.md`

```markdown
---
description: "Token usage audit per feature / phase / session"
argument-hint: "[feature-id | --all] [--json]"
scripts:
  py: scripts/python/report.py
---
Run `{SCRIPT} $ARGUMENTS` from the project root. It refreshes the audit, then prints a Markdown report.
1. Show the output verbatim, including the disclaimer.
2. Then add at most two sentences: the most expensive phase, and what the "Session splitting" section concludes.
   Never compute, estimate or round numbers yourself.
3. If it prints an error (for example an unknown feature), show it together with the features it lists.
```

`commands/check.md`

```markdown
---
description: "Check integration, hooks and environment"
scripts:
  py: scripts/python/check.py
---
Run `{SCRIPT}` from the project root.
- If it prints a single line starting with "Usage Bridge: ok", mention nothing else and continue with what you were
  doing.
- Otherwise show its output verbatim — it contains the fix commands — and then continue: this check warns, it never
  blocks the workflow.
```

`report.py` arguments: an optional feature (directory name or path relative to W; default = the active feature from
`SPECIFY_FEATURE_DIRECTORY`/`feature.json`, else the most recently active feature in the timeline), `--all`, `--json`.
It runs the capture pipeline in manual mode first (within the deadline), then renders.

### 6.3 `check`

| # | Check | Level | Remediation printed |
|---|---|---|---|
| 1 | Python ≥ 3.9 | FAIL | Install Python 3.9+ with `python3` or `python` on PATH (or in the project `.venv`), then run `specify extension add` again so `{SCRIPT}` picks it up |
| 2 | Claude installed per `.specify/integration.json` | FAIL | `specify integration install claude`, or `specify extension disable usage-bridge` if the project does not use Claude Code. Cursor-only projects get a WARN: capture is not supported in v0.1 |
| 3 | `.claude/settings.json` has a native `Stop` entry whose command runs `.specify/events.py speckit.usage-bridge.capture` | FAIL | Runtime events are disabled or were removed: re-apply the Claude integration with `--integration-options="--events true"` (the integration test pins the exact command line) |
| 4 | `.specify/events.py` exists | FAIL | as 3 |
| 5 | git available | WARN | branch fallback and worktree discovery are off |
| 6 | Claude projects directory readable and transcripts found for this repository | WARN | none yet → run one agent turn, then check again; directory missing → set `TOKEN_USAGE_PROJECTS_DIR` or `CLAUDE_CONFIG_DIR` |
| 7 | R writable | FAIL | the path and the OS error |
| 8 | Last capture | WARN | last capture failed → time, error and log path; transcripts more than a day newer than the last capture → captures don't seem to run, check the `Stop` hook |
| 9 | Configuration | WARN | parse warnings; `author.alias` set in the committed file |

- Output: healthy → `Usage Bridge: ok (last capture 12 min ago)`; otherwise one `FAIL|WARN <check>: <remediation>` line
  per finding. `--verbose` lists every check; `--json` prints `{ok, checks: [{id, level, status, message,
  remediation}]}`.
- Exit 1 when any FAIL. The same script serves the mandatory `before_specify` hook, manual runs and team setup
  scripts (D22; README snippets for bash and PowerShell).

## 7. Vendoring, versioning and release

### 7.1 Vendored files

`scripts/python/vendor/token_usage/` holds `scripts/token_usage.py`, `data/pricing.json` and `LICENSE` byte-for-byte
from upstream, plus:

```json
{
  "repo": "https://github.com/Wicked-Sick-Ltd/token-usage",
  "ref": "main",
  "commit": "f4078277e79c007993e0cb595bb95f924a2a8777",
  "upstream_version": "0.6.1+unreleased-0.7",
  "files": {
    "scripts/token_usage.py": "sha256:…",
    "data/pricing.json": "sha256:…",
    "LICENSE": "sha256:…"
  }
}
```

### 7.2 `tools/update-vendor.py`

- `python tools/update-vendor.py <tag>` — tags are the default (D23); `--commit <sha>` is an explicit override.
- Downloads the upstream archive for the ref (stdlib `urllib` + `zipfile`), refuses to run if any vendored file's
  sha256 differs from `VENDOR.json`, replaces only the three vendored files, rewrites `VENDOR.json`, prints the
  upstream `CHANGELOG.md` between the old and new refs for the PR description, and reminds to run the contract tests.
- A bump is accepted only if the contract tests, including the oracle reconciliation (§8.3), pass.

### 7.3 Versioning and changelog

As brief §5.7: patch = vendor bump without behaviour change; minor = report content or numbers change; major = output
file or schema change. Every `CHANGELOG.md` entry names the vendored token-usage version and commit. On breakage:
keep the old pin, adapt only in `tu_compat.py`, and propose an upstream issue (posted only with explicit OK).

### 7.4 Release and distribution

Triggered by a tag `vX.Y.Z` (created only with explicit OK); `release.yml`:

1. runs the full CI;
2. builds `usage-bridge-vX.Y.Z.zip` with a single top-level folder `usage-bridge/` containing the repository minus
   `.extensionignore` patterns (F14);
3. generates `catalog.json` — `schema_version "1.0"`, `catalog_url` = the latest-release URL below, and an
   `extensions.usage-bridge` entry with `id`, `name`, `description`, `author`, `version`, `download_url` (this
   release's zip asset), `repository`, `homepage`, `documentation`, `changelog`, `license`, `requires`, `provides`,
   `tags`, `created_at`, `updated_at`;
4. creates the GitHub release with both assets and the CHANGELOG section as notes.

Developers, once per project:

```bash
specify extension catalog add --name usage-bridge --install-allowed https://github.com/CrazyBaran/spec-kit-usage-bridge/releases/latest/download/catalog.json
specify extension add usage-bridge
```

Updates: `specify extension update usage-bridge` (config is backed up and restored; native hooks point at the
dispatcher and survive updates; per-feature files are rebuilt on the next `Stop`). Fallback without a catalog:
`specify extension add usage-bridge --from <release zip URL>`. `docs/release.md` documents the full flow
(token-usage → this extension → developers).

### 7.5 CI (`ci.yml`)

- `ruff` lint;
- vendored sha256 check against `VENDOR.json`;
- tests on {ubuntu-latest, windows-latest} × {Python 3.9, latest}: unit, contract (incl. oracle), golden;
- integration tests on {ubuntu-latest, windows-latest} with Spec Kit v1.0.12 run through uv:
  `uvx --from git+https://github.com/github/spec-kit.git@v1.0.12 specify …` — the developer's global `specify`
  install is never modified.

## 8. Testing

### 8.1 Principles

TDD with pytest (development dependency only; the runtime stays stdlib-only). Every test is **hermetic**: an autouse
fixture points `HOME`/`USERPROFILE`, `TOKEN_USAGE_PROJECTS_DIR`, `TOKEN_USAGE_LEDGER_DIR`, `XDG_CONFIG_HOME`,
`CLAUDE_CONFIG_DIR` and the global git config (`GIT_CONFIG_GLOBAL`) at temporary locations, and runtime state lives
in a temporary repository's `.git/usage-bridge/`.

### 8.2 Fixtures

Synthetic JSONL built by `tests/builders.py` — `user()`, `command()`, `assistant()`, `usage()`, `skill_use()`,
`compact_boundary()`, `subagent()` (with `.meta.json`) — shaped like the real entries in F1–F8. No real transcript is
ever committed. Scenarios:

- **From brief §5.9:** specify → plan in one session; phases split across sessions; resumed/forked session
  duplicating `requestId`s across files; `/speckit-specify` creating the branch mid-run; subagent rollup (flat and
  nested `workflows/`); `/compact` (manual and auto); `/clear` (new file and in-file); sticky plain prompts after a
  command; two features in one session; non-Spec-Kit work; malformed and truncated JSONL lines; Windows paths; a
  project directory with spaces; a project without the git extension (`feature.json` only); feature switched
  mid-session.
- **From the findings:** every invocation form maps to the same phase; hyphenated extension ids resolved via the
  registry; `/model` mid-phase stays transparent; a hook skill (`speckit-git-commit`) folds into the phase while a
  core-phase Skill starts one; `constitution` → `project`; worktree session (payload `cwd` ≠ P); each branch-resolver
  rule and an ambiguous match; two authors merged in either order render byte-identical md; background subagent →
  `partial`; deadline reached → `partial` and exit 0; lock contention; CRLF-insensitive comparison; verdict with and
  without an expired cache TTL; unpriced model footnote.

### 8.3 Test layers

- **Unit tests** per module.
- **Contract tests** on `tu_compat`: API shapes, and the **oracle reconciliation** — for every fixture, our digest with
  the phase rules switched off yields exactly `parse_session`'s per-segment usage. Runs in CI and on every vendor bump.
- **Golden files** (`tests/golden/`) for md and JSON of representative scenarios, refreshed with
  `pytest --update-golden`.
- **I/O safety:** capture prints nothing and exits 0 on garbage, empty, oversized and non-UTF-8 stdin; a crash
  mid-write leaves the original file intact; unchanged content is not rewritten.
- **Performance:** 200 synthetic sessions — cold capture < 5 s, warm < 1.5 s (with a CI margin for slower Windows
  runners).
- **Integration** (Spec Kit v1.0.12 via uv, both OSes): `specify init --integration claude` in a temporary directory →
  `specify extension add <repo> --dev` → `Stop` entry present in `.claude/settings.json` →
  `specify extension info usage-bridge` lists the commands and events → a sample payload piped into the generated
  dispatcher writes the expected files → `check` fails on a project without the Claude integration and on one with
  events disabled → `specify extension remove usage-bridge` removes the entry and the commands; plus installing from
  the release zip.

## 9. Acceptance checklist

| Brief §7 item | Evidence |
|---|---|
| `specify extension add <repo> --dev` and the release zip install into a fresh `specify init --integration claude` project; `Stop` handler present | integration test (§8.3) |
| `specify extension info usage-bridge` shows commands, events and informational tools | integration test |
| `specify extension remove usage-bridge` removes the handler and commands | integration test |
| Real run: `/speckit-specify` + `/speckit-plan` in session 1, `/speckit-tasks` in session 2 → 3 phases, 2 sessions, re-priming for session 2; totals reconcile with vendored `token_usage.py json` for both transcripts after dedup | manual run with the user in a scratch Spec Kit project, in the **desktop Code tab and the CLI** (F20), plus a real `/clear` and a `--fork-session` |
| A resumed session is not double-counted | fixtures + the real `--fork-session` run |
| Capture silent, exit 0, < 5 s; errors only in the log | I/O-safety and performance tests + `last-capture.json` of the real run |
| `check` flags a project without the Claude integration and one with events disabled | integration test |
| CI green on ubuntu + windows, Python 3.9 and latest; vendored sha256 check green | `ci.yml` |
| README, CHANGELOG, THIRD_PARTY_NOTICES, `docs/release.md`, `docs/limitations.md` | §10 |

## 10. Documentation deliverables

- **README.md:** what it is and why; install (catalog and `--from`); configuration; how numbers are computed (runs,
  attribution, re-priming, verdict); limitations (link); neutral relation table to token-analyzer, Cost Tracker and
  token-budget (D27); prominent credit — token-usage does the transcript parsing, segmenting and pricing, Usage Bridge
  adds Spec Kit capture, attribution and per-feature reports (D28); "not affiliated" line; setup snippets for `check`
  (D22).
- **CHANGELOG.md:** 0.1.0 entry naming the vendored token-usage commit.
- **THIRD_PARTY_NOTICES.md:** token-usage, MIT, "Copyright (c) 2026 Craig Fletcher", full licence text.
- **docs/limitations.md:** the list below plus the upstream candidates.
- **docs/release.md:** the release and update flow (§7).

## Out of scope for v0.1

Cursor runtime implementation (seam only), Cowork runtime, MCP server, dashboards/HTML, budgets and alerts, finance
exports, run-vs-run comparison and quality scoring, Jira/Confluence export, community catalog submission, automated
vendor bumps (Renovate / scheduled Actions), branch-name regex override, the vendored `insights` CLI, currency
conversion, macOS CI, cross-session carry-over attribution, committed project-level (constitution) reports,
`session_end`/`SubagentStop` capture.

## Roadmap candidates (not commitments)

Cursor capture through the seam; Cost Tracker interop (D26); a regex override for exotic branch names; bump to the
token-usage v0.7.0 tag (D23); community catalog submission (D21); upstream contributions (D24); `insights` in
`report`; subagent assignment via `.meta.json` `toolUseId`; macOS CI.

## Limitations and assumptions (→ `docs/limitations.md`)

1. Claude Code transcripts are an undocumented format; the fields used were verified on versions 2.1.177–2.1.284.
2. Hook parity of the desktop Code tab and IDE extensions with the CLI is not documented; the acceptance run checks it.
3. `/clear` starting a new transcript is inferred from the docs, not observed; both representations are handled.
4. Compaction summarisation calls are not in transcripts and are not costed.
5. Costs are estimates at API list prices; subscription plans are not billed per token; fast mode, long context,
   data residency and web search are not modelled; cache-write rates follow the upstream multipliers.
6. Timeline attribution needs captures to run. Before install, after missed turns, or with
   `SPECIFY_FEATURE_NO_PERSIST`, attribution falls back to the branch; names the resolver cannot map stay
   unattributed.
7. "Other work" includes anything done in the repository while a feature is active, including unrelated chats.
8. Committed files name their authors (D5) — check your organisation's employee-monitoring rules (GDPR, works
   council).
9. The splitting verdict is a model with the assumptions printed under it (§3.4).
10. A feature that exists only in another worktree is written when a capture runs in a checkout that contains it.
11. The `{SCRIPT}` interpreter is resolved at install time (F11); when `.claude/skills` is committed with a
    machine-specific interpreter path, other developers need `python3`/`python` on PATH and to re-run
    `specify extension add`.
12. macOS is expected to work but is not tested in CI.
13. For a request duplicated across files, the earliest session keeps it.
14. A very large first capture can be `partial` until the cache is warm.
15. One person on two machines yields two author files by design; renaming git `user.name` starts a new author file.

**Upstream candidates** (D24, not posted without explicit OK): limit Skill-tool segments to Cowork or make them
optional (C2); a request-level API (C6); cross-file `requestId` dedup; transparency of built-in commands; Windows CI.

## Notes for the implementation plan

- **Branches:** this spec on `docs/v0.1-design-spec`; the plan on `docs/v0.1-implementation-plan` (stacked on it);
  implementation in an isolated worktree on `feat/v0.1.0` (stacked on the plan branch). Each branch is pushed; no
  PRs, merges or tags without asking.
- **TDD** for every task, one commit per task; code review between tasks.
- **Subagent models (cheapest viable):** Haiku for tasks whose code and tests the plan spells out (`yamlsub`,
  `config`, `log`, render formatting, docs, CI YAML, `update-vendor`); Sonnet for judgment-heavy tasks (`digest`,
  `phases`, `attribution`, `metrics` edge cases, discovery with worktrees, the Spec Kit integration test) and for code
  reviews. The main session verifies claims before accepting a task.
- **Order:** vendor `f407827` and the oracle contract test first, then digest → phases → attribution → metrics →
  render → capture → report → check → packaging/CI → docs.
