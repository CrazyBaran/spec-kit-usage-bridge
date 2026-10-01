# Usage Bridge v0.2: Codex and Cursor support

Date: 2026-10-01
Status: Written spec approved by the user on 2026-10-01; implementation-plan review pending.
Target release: v0.2.0

## 1. Intent and agreed scope

Spec Kit users working in Claude Code, Codex or Cursor should receive one per-feature,
per-phase audit across sessions and authors. Preserve the existing Claude behavior and
the current report locations. Add support using the best available data: measured tokens
where available, partial measured usage when coverage is incomplete, and activity when
tokens are unavailable. Do not estimate missing token counts.

The user approved a local Codex adapter, reuse of the vendored Cursor adapter, and an
unchanged vendor. They approved the shared-pipeline architecture and an initial Codex
scope limited to locally available sessions. That approval permits this written spec;
implementation follows written-spec and implementation-plan review.

Success means a Codex-only or Cursor-only project can install, check, capture and report
without needing Claude. A mixed project produces a combined report that identifies
each runtime and discloses gaps instead of treating missing usage as zero.

Out of scope: retrieving cloud-only Codex history, upstream contribution or vendor
patching, live app-server subscription, billing reconciliation, guessed token counts,
dashboards, budgets, and unrelated v0.1 refactoring. Automatic capture is supported
where the installed integration actually supplies usable events; manual refresh is
available for every runtime.

## 2. Existing constraints

- Python 3.9+ and Spec Kit 1.0.12+ remain the baseline.
- The extension is distributed as files, not as a Python package.
- Capture retains its 15-second overall deadline, silent hook behavior and zero hook
  exit status. Logs and diagnostics explain failures without blocking an agent turn.
- Keep feature-specific output containment, runtime locking, atomic output replacement,
  author/machine separation, alias reconciliation and deterministic report generation.
- Preserve the pinned token-usage commit and hashes. All vendor calls pass through
  `tu_compat.py`; new adapters do not mutate its private adapter registry.
- Existing settings remain valid. Default privacy continues to exclude prompt previews
  and local paths from committed reports.

## 3. Architecture and adapter contract

Introduce `usage_bridge/adapters/` with a shared contract and separate Claude, Codex
and Cursor implementations. The existing Claude discovery and digest functions remain
the implementation behind the Claude adapter, preserving their reconciliation tests.

An adapter provides:

1. Discovery of project-owned source descriptors across the current checkout and its
   worktrees. Descriptors include runtime, native session ID, source kind and cache
   fingerprint. They contain local paths only in runtime state.
2. Payload handling for recognized native events: normalized runtime/session identity,
   workspace evidence, timestamp, phase invocation and optional measured usage.
3. Parsing to a normalized session: ordered phase/activity events, usage observations,
   model identity, branches, child-session relationships, measurement quality,
   attribution confidence, capabilities and diagnostic reasons.

Usage observations may describe a real request, a cumulative-counter increment or a
segment aggregate. Preserve that distinction. A segment aggregate is never presented
as a measured API call. Normalize usage before entering the shared phase, attribution,
pricing, metrics and reporting pipeline.

Use `(runtime, native_session_id)` as logical session identity and runtime-qualified
observation identity for deduplication, timelines and caches. Per-machine report merging
uses `(machine, runtime, native_session_id)`, retaining the existing alias revision rules.
Identical native IDs from different runtimes must remain separate. Runtime-specific
evidence governs deduplication; equal token values alone do not prove duplicate usage.

Manual capture and report refresh discover all enabled runtimes. A native event first
records its runtime's evidence and prioritizes its active session, then refreshes other
enabled sources within the same deadline. A partial scan retains previously captured
sessions; it does not delete data merely because discovery failed or timed out.

## 4. Codex adapter

### Discovery and ownership

Read local rollout JSONL under `$CODEX_HOME/sessions` and `$CODEX_HOME/archived_sessions`,
defaulting to `~/.codex`. Missing directories are normal. Configured extra directories
may supply additional rollout files. Use session metadata and turn context workspace
paths for checkout ownership; filename proximity or a branch name alone is insufficient.
Unknown ownership excludes a session and produces a local diagnostic.

Index session metadata and source fingerprints in the runtime directory. Read metadata
before parsing whole unrelated files. Discovery and parsing check the shared deadline
between files and records. Cache keys include runtime, adapter version, source stamps
and privacy mode. Copied or archived versions of one session are reconciled by identity
and event history, not counted as distinct sessions.

### Parsing and accounting

Recognize session metadata, turn context, user messages, token-count events and explicit
compaction or parent-thread metadata. Model changes apply from the corresponding turn
context onward; absent or ambiguous model identity remains unknown.

Reconcile cumulative token counters within a session history. An unchanged snapshot
adds no usage. For monotonic compatible snapshots, subtract the accepted previous
snapshot by bucket to obtain an increment. Never add `last_token_usage` on top of a
cumulative increment. The latest-increment fields are supporting evidence, not a second
source of spend. A first snapshot may be used as a session total, but is assigned to a
phase only when the observed history establishes that phase for the counted interval.

Counter decreases, missing prefixes, incompatible field changes and compaction-related
synthetic totals must not produce negative usage or silently create new spend. Retain
the last trustworthy bucket totals, mark coverage partial, and expose a diagnostic. A
documented restart with complete preceding history can establish a new counter epoch;
otherwise do not infer the missing interval. Prefer explicit input/output buckets over
a standalone `total_tokens` value that may reflect context-window normalization.

Treat cached input as a subset of input and reasoning output as a subset of output
for supported schemas, so neither is added twice. Convert inclusive input to the
shared uncached-input bucket. Validate these relationships against sanitized source
fixtures; incompatible values stay partial rather than being silently clamped. Preserve
reasoning as informational metadata when present. A cache-write value without supported
duration semantics remains disclosed as unsupported and prevents a complete cost estimate.

Recognize actual Spec Kit commands and skill invocations in user-event evidence. Normal
prompts continue the active phase. Do not infer phases by searching assistant prose.
If an increment spans an uncertain phase boundary, keep it in an unassigned-phase run
and mark phase attribution partial instead of assigning it wholly to the later phase.

### Resumes, forks and children

Resuming the same session continues its counter history. Forked sessions may replay a
parent prefix: exclude that prefix only when event identity/history evidence proves
it is inherited. If inherited usage cannot be separated, report the child activity and
disclose excluded ambiguous token coverage rather than counting both histories fully.

Attach child usage to the parent's active phase at the recorded child start when the
relationship and start evidence exist. Count a child's independent measured usage once;
do not count it again as a top-level session contribution. Unresolved relationships
remain separate with partial attribution. Do not assume parent counters include or
exclude child usage without evidence from the supported source schema.

## 5. Cursor adapter

Use the pinned vendor's `CursorAdapter` through public compatibility wrappers in
`tu_compat.py` for supported hook ledgers, read-only SQLite sources and explicit JSON
exports. Translate its parsed segments into normalized segment observations and phase
events; do not manufacture request-level timestamps or IDs.

Use one authoritative source per conversation: project runtime hook ledger first,
then explicitly configured export, then the local SQLite source. Do not add overlapping
sources. A sparse ledger may therefore yield partial/activity-only coverage; disclose
this instead of merging uncertain token records from the database. Explicit exports are
selected through runtime-specific extra directories and must contain project ownership
evidence. Read each configured worktree and deduplicate conversation IDs.

For native Cursor events, add a small Usage Bridge ledger writer using the vendored
ledger record shape. It records recognized prompt-submit and completion events, stable
conversation/generation IDs, workspace evidence and supplied usage. It stores only a
recognized phase invocation when previews are disabled; ordinary prompt/task text and
labels derived from that text are omitted. When previews are enabled, cap them at the
existing preview limit. Ledgers live under the project runtime directory, not in the
user's global token-usage ledger. Append events under the shared lock before parsing.

Adapter wrappers direct vendor discovery to the bridge ledger and configured Cursor
data root, restoring scoped environment overrides after each call. Do not require the
token-usage plugin to be installed. Preserve upstream `exact`, `partial` and
`activity_only` classifications and warnings; never upgrade SQLite/export measurements
to exact. Duplicate generation/completion records must not add repeated usage.

## 6. Capture, commands, configuration and checks

Retain the three existing commands and arguments. Add no new CLI selector in v0.2;
runtime configuration controls discovery and existing report filters select features.
Runtime defaults are all three supported agents, with missing optional data treated as
normal. Add these optional settings:

```yaml
runtimes:
  enabled: [claude, codex, cursor]
  codex:
    extra_dirs: []
  cursor:
    extra_dirs: []
    data_dir: ""
```

The existing `transcripts.extra_dirs` remains Claude-only. `CODEX_HOME` chooses Codex's
base root. Cursor `data_dir`, if nonempty, overrides the vendor's platform-default root.
New fields use existing base/local configuration precedence; add corresponding
environment overrides for scalar/list fields using the project's naming convention.
Unknown runtime names warn and are ignored. An explicitly empty enabled list disables
source discovery and produces an actionable diagnostic without erasing saved reports.

Recognize payloads using event discriminator and source metadata, not `session_id`
alone. Codex and Claude payloads can overlap structurally: use an explicit integration
hint when available, otherwise verify transcript format. Ambiguous or malformed native
payloads log a no-op; they never trigger a full scan as if they were a manual invocation.

Use Spec Kit's dispatcher and native integration registrations. Request prompt-submit
events for reliable phase evidence and stop events for refresh; duplicate delivery is
idempotent. Do not directly install unmanaged hooks into user configuration. Verify
actual dispatch and payload contracts against the baseline integration and supported
agent before claiming automatic capture. Installed hook configuration alone does not
prove an agent executes it.

Checks report each installed, enabled runtime separately: source availability, capture
mode, measurement limitations, and hook/dispatcher health. No Claude requirement applies
to Codex-only or Cursor-only projects. Missing optional runtime sources warn; unsupported
event capability reports manual capture as the available mode. Broken configuration for
an advertised automatic integration fails its integration check. Python, output/runtime
writability and vendor-integrity requirements remain mandatory. No supported enabled
integration fails the integration check.

Document installation and event-enablement steps per runtime, including the supported
version/platform evidence from integration tests. Cloud-only sessions and unsupported
agent event configurations receive explicit manual/local-history limitations.

## 7. Measurement, cost and metrics semantics

Separate measurement quality from attribution confidence and scan completeness:

- `exact`: all recognized billable usage observations in the supported source interval
  have validated measured buckets. This describes source coverage, not billing accuracy.
- `partial`: some measured usage exists, but observed gaps, ambiguous counters or
  unsupported buckets prevent complete coverage. Include machine-readable reasons.
- `activity_only`: phase/session activity exists without trustworthy measured usage.

Attribution confidence independently records exact evidence, branch fallback, partial
phase assignment or unattributed work. An exact session token total can therefore have
partial phase attribution. Deadline status is another independent completeness field.

Activity-only token fields and costs are null in JSON and unavailable in Markdown.
Measured zero is represented as zero. Partial records retain known measured buckets
and identify missing buckets; aggregate output includes measurement session counts and
states that measured subtotals exclude unavailable coverage. Overall quality is the
least complete included quality; exact plus activity-only remains activity-only at
the overall level while exposing the exact measured subtotal separately.

Pricing is runtime/model-aware. Keep existing Claude pricing through the vendor.
Add a small bridge-owned OpenAI rate table with source URLs, retrieval date and a file
hash, reviewed against official prices during implementation. Unknown models remain
unpriced; reuse the existing validated team overrides. Never price Codex through an
Anthropic fallback. Show a full estimated cost only when all needed measured buckets
and rates are known. Otherwise expose a labeled known-cost subtotal and leave the
complete cost null. Subscription usage remains an API-price equivalent estimate.

Capabilities explicitly govern request counts, subagent accounting, compaction and
session-splitting metrics. Preserve Claude metrics. For Codex/Cursor, leave re-priming,
splitting verdicts and request counts unavailable unless the adapter has the evidence
required by those formulas. Display turns, activities or segments with their actual
unit rather than relabeling them as API calls. Do not compare session-splitting costs
across different runtimes or model accounting schemes.

## 8. Report schema and v0.1 compatibility

Write schema version 2 for feature sources, feature reports and repository reports.
Readers accept versions 1 and 2. Interpret a v1 session as Claude with the existing
measured token semantics; preserve its pre-existing partial-capture reasons rather
than upgrading completeness. Normalize it in memory before merging with v2 sources.
Reject unsupported future versions with a diagnostic instead of treating them as v2.

Add runtime, measurement, reasons, attribution confidence and capabilities to session
records, with run-level quality where it differs. Feature/repository summaries include
runtime breakdowns, measurement counts, measured subtotals and unavailable coverage.
Remove the hard-coded Claude report heading. Keep the existing per-author/machine file
names, feature locations and privacy rules; runtime is a session dimension inside each
author file. When refreshing one runtime, retain the same author's other runtime records.

The first successful v0.2 write upgrades only that author's refreshed file atomically.
Other authors' v1 files remain readable. Preserve historical data when local transcript
history is unavailable. Invalidate incompatible digest caches; read legacy timeline
records as Claude. Existing v0.1 writers cannot understand mixed v2 files: document that
all contributors must upgrade before writing mixed-runtime feature audits and that
downgrading is unsupported. Do not silently round-trip v2 data through a v1 writer.

## 9. Errors, performance and privacy

One corrupt/unreadable source affects its own runtime/session; continue available work
within the deadline. Report source warnings locally with privacy-safe reason codes in
committed reports. An unavailable source is not proof that historical usage vanished.
Use source fingerprints and an indexed scan to avoid rereading whole local histories.
SQLite access is read-only; check deadlines around bounded query/parse operations.
Set short busy/query interruption limits where supported. If a source cannot be read
safely within the remaining budget, retain its prior snapshot and mark the scan partial.

Never commit raw hook payloads, transcripts, credentials, account IDs or absolute paths.
Previews remain opt-in for every adapter, including intermediate bridge-created ledgers.
Existing native session IDs, model names, author identifiers and timestamps remain
report metadata. Disabling previews invalidates/rebuilds affected local digests and
bridge ledgers without changing original agent files; newly rendered reports omit previews.

## 10. Validation and release criteria

Use sanitized fixtures with explicit provenance and source-format versions. No test
requires access to a developer's personal history. Validate:

- Claude oracle reconciliation and existing report, privacy, alias, deadline and output
  containment regressions.
- Codex monotonic counters, repeated snapshots, missing usage, model changes, invalid
  buckets, counter resets, compaction normalization, copied/archived sessions, resumes,
  fork prefixes and parent/child double-count prevention.
- Cursor ledger/source precedence, duplicate generations, read-only database behavior,
  activity-only/partial/exact results, ambiguous ownership and preview suppression.
- Identical native session IDs across runtimes, partial adapter failure, unchanged
  deterministic outputs, and retention of other runtimes during incremental capture.
- Mixed v1/v2 sources, unknown schema versions, author alias transitions, null versus
  measured zero, known-cost subtotals and unsupported-metric suppression.
- Baseline Spec Kit install/update/remove and command rendering for all integrations;
  real event dispatch smoke tests on supported agents. Test Windows local source paths
  and portable parsing; document platform coverage actually verified.
- Many unrelated Codex rollouts and a large Cursor corpus within the shared capture
  deadline. An interrupted scan must retain prior snapshots and refresh the active session
  first when budget permits.

Before release, bump extension/Python/catalog metadata to v0.2.0, update README,
configuration template, command descriptions, changelog, limitations and release notes.
Verify packaged adapter modules, schema migration and bridge pricing data are included.
Release preparation is in scope; publishing or an upstream PR requires a separate request.

## 11. Evidence and implementation boundaries

- [Pinned vendor manifest](../../../scripts/python/vendor/token_usage/VENDOR.json):
  commit `f4078277e79c007993e0cb595bb95f924a2a8777`, Claude/Cursor adapter registry.
  The vendor's ledger writer captures prompt text, motivating the local privacy filter.
- [Spec Kit v1.0.12 Codex integration](https://raw.githubusercontent.com/github/spec-kit/v1.0.12/src/specify_cli/integrations/codex/__init__.py):
  skills registration and canonical event mappings. Its mappings are integration
  declarations; actual runtime delivery still requires smoke-test validation.
- [OpenAI Codex app-server documentation](https://learn.chatgpt.com/docs/app-server):
  thread-scoped token usage updates. This spec uses local rollout parsing, not a live client.
- [OpenAI token-accounting notes](https://github.com/openai/symphony/blob/main/elixir/docs/token_accounting.md):
  distinction between cumulative totals, latest increments and event-specific usage.
- Read-only inspection of a local Codex rollout on 2026-10-01 confirmed session metadata,
  turn context and token-count fields. No personal transcript content is embedded here.

Local rollout formats and Cursor stores are evolving implementation details. Supporting
a known fixture schema does not promise exhaustive usage across every agent version.
The adapters must surface unsupported data rather than silently claiming full coverage.

## 12. v0.2.1 amendment: continuing sessions with stale feature attribution

Added at the user's request on 2026-10-01. This amendment extends the v0.2.0 baseline
above; its checkpoint command supersedes section 6's restriction on new CLI selectors
for v0.2.1. The patch target is v0.2.1. Original v0.2.0 requirements remain applicable
unless explicitly extended here.

### Problem and intended outcome

A session may start on feature A, create feature B during `specify`, and retain A in
its transcript branch metadata. Native capture may also be unavailable. Continuing
that session with `speckit clarify` or a Superspec command must support recording usage
against B using explicit invocation evidence. An `after_specify` checkpoint alone is
insufficient: it neither repairs earlier history automatically nor establishes which
feature a later invocation belongs to.

### Requirements

1. Provide an explicit checkpoint that binds one observed phase invocation to an
   existing feature directory inside the selected checkout. Its identity includes
   runtime, native session ID, checkout, canonical phase and invocation start timestamp.
   Apply this binding before timeline and branch fallback. Do not require the feature
   directory name to equal the Git branch name.
2. Support later core phases, including `clarify`, and recognized extension command
   phases, including `superspec.brainstorm`, with the same binding mechanism. Extension
   phase names follow the existing command classifier rather than a Superspec-only
   allowlist. Project-level `constitution` retains its existing semantics.
3. Bind the phase actually observed in the source. A Superspec command may open an
   extension phase; a helper brainstorming skill that folds into an existing phase
   must not create a synthetic `superspec.brainstorm` phase or reclassify its usage.
4. Resolve the feature explicitly for each invocation. A binding for `specify` must
   not become a session-wide default for `clarify`, Superspec commands, or later work.
   Switching features in the same session requires a new explicit binding; never
   infer it from the previous binding, the newest transcript, or shared active-feature
   state. Bindings must not leak between runtimes, sessions or checkouts.
5. Permit the user to checkpoint a later invocation in an already affected session
   without rerunning `specify` or repairing the earlier invocation first. Supply the
   feature and verified runtime/session identity explicitly; Codex may use the shell's
   `CODEX_THREAD_ID`. Missing or ambiguous identity produces an actionable diagnostic
   without guessing. Workflow diagnostics must not block specification work.
6. Keep historical repair separate from ongoing workflow capture. Manual checkpoint
   use previews the selected invocation and destination by default; `--apply` is
   required to persist it. Repeated matching phases require an invocation timestamp
   unless the caller explicitly requests `--latest`. Repairing one invocation must
   not rewrite unrelated earlier or later runs, raw transcripts, or other authors'
   source files.
7. Persist bindings in private Git runtime state under the capture lock. Repeated
   checkpoint/native captures are idempotent. The invocation start remains the anchor
   when delayed usage changes its end timestamp. Preserve measured totals and missing
   counts; a feature binding cannot resolve ambiguous token intervals or manufacture
   usage.
8. Keep `after_specify` as an initial workflow checkpoint and document the explicit
   checkpoint route for later core and extension phases. Do not claim that later
   phases capture automatically merely because a hook is registered or `specify`
   was bound. Claude, Codex and Cursor share the binding contract while retaining
   their existing source capabilities and native delivery limitations.

### Acceptance criteria

- A Codex session whose branch metadata still identifies A can bind an observed
  `clarify` invocation to B without binding or rerunning its earlier `specify` run.
- An observed `superspec.brainstorm` command can be bound to B. A helper brainstorming
  skill inside `clarify` remains part of `clarify` and cannot be selected as a separate
  extension invocation.
- After binding an invocation to B, switching to C and explicitly binding a later
  invocation leaves B's assignment unchanged. An unbound invocation does not inherit B
  or C; existing evidence-based attribution or unattributed status remains in effect.
- Repeated `clarify` or Superspec invocations reject ambiguous selection. Selecting
  one by timestamp changes only that invocation; an explicit latest selector chooses
  only the latest matching invocation.
- Preview changes neither bindings nor feature reports. Applying twice and refreshing
  after delayed counters retain the assignment without duplicating measured usage.
- Equivalent invocation isolation is verified for Claude and Cursor fixtures, with
  unavailable measurements remaining unavailable and native delivery claims limited
  to verified runtime behavior.
