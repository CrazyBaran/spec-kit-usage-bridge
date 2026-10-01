# Limitations and assumptions

1. Claude Code transcripts are an undocumented format; the fields Usage Bridge reads were verified on versions 2.1.177–2.1.284.
2. Hook parity between the desktop Code tab and IDE extensions and the CLI is not documented; the acceptance run checks it.
3. `/clear` starting a new transcript is inferred from the Claude Code documentation, not observed. Both same-file and new-file representations are handled.
4. Compaction summarisation calls are absent from transcripts and are not costed.
5. Costs are estimates at API list prices. Subscription plans are not billed per token; fast mode, long context, data residency and web search are not modelled. Cache-write rates follow the upstream multipliers.
6. Timeline attribution requires a capture matching the closing request. Legacy timeline entries lack this evidence. Before installation, after missed turns, or with `SPECIFY_FEATURE_NO_PERSIST`, attribution falls back to the branch. Names the resolver cannot map remain unattributed.
7. “Other work” includes anything done in the repository while a feature is active, including unrelated chats.
8. Committed reports identify authors. Check your organisation’s employee-monitoring rules, including GDPR and works council requirements.
9. The session-splitting verdict is a model; its assumptions are printed under the verdict in the report.
10. A feature that exists only in another worktree is written when capture runs in a checkout that contains it.
11. The `{SCRIPT}` interpreter is resolved at install time. If `.claude/skills` is committed with a machine-specific interpreter path, other developers need `python3` or `python` on PATH and must rerun `specify extension add`.
12. macOS is expected to work but is not tested in CI.
13. If a request is duplicated across transcript files, the earliest session keeps it.
14. A very large first capture can be marked `partial` until the cache is warm.
15. One person using two machines gets two author files by design; changing git `user.name` or `author.alias` starts a new author file. Merged reports count overlapping sessions on the same machine once using the newest snapshot and preserve all source files. New captures carry a session revision so pricing/configuration changes supersede older aliases even when transcript timestamps are unchanged. Legacy snapshots fall back to transcript timestamps and deterministic tie-breakers.

## Upstream candidates

### v0.2 runtime coverage

Codex reads only local `CODEX_HOME/sessions`, `archived_sessions`, and configured
extra directories. Cloud-only history is unavailable until it exists locally.
Cumulative counters are reconciled conservatively; resets, malformed buckets and
uncertain inherited history reduce coverage. Cache reads are removed from input
before summing; reasoning tokens remain part of output. Codex counter observations
and Cursor segments are not API request counts, so calls, repriming and session
splitting verdicts are unavailable for these runtimes.

Cursor sources prefer bridge-owned hook ledgers, then explicit owned exports,
then available local SQLite state. Source availability varies by version and OS.
Activity without usage has null token buckets, never fabricated zero usage.
Unknown models retain usage with unavailable complete cost. The known-cost and
measured-token subtotals exclude unavailable coverage. Costs remain API-equivalent
estimates. The bundled OpenAI table supports its named models; other models require
explicit pricing overrides. Codex is implemented outside the unchanged vendor.

Prompt previews default off. Cursor ledgers keep command/phase evidence and minimal
identity metadata under the Git runtime directory. Disabling previews removes text
from bridge-owned ledgers and caches on refresh; original agent files remain intact.
Local-source failure or an interrupted scan retains prior report snapshots.

These are candidates for discussion with token-usage upstream and are not commitments: limit Skill-tool segments to Cowork or make them optional; expose a request-level API; deduplicate `requestId` across files; make built-in command transparency configurable; improve Windows CI. Upstream issues are not posted without explicit approval.

## v0.2.1 invocation checkpoints

Conflicting Codex session copies make checkpoint selection unavailable, including
selection by an explicit timestamp. Resolve the local history conflict first.
The diagnostic leaves bindings and feature reports unchanged; workflow mode warns
without blocking specification work. Consistent copied/archived prefixes remain supported.

Explicit bindings override stale branch attribution only for the selected observed
invocation. They neither resolve ambiguous token intervals nor recover cloud-only
history. Later core/extension phases require another explicit checkpoint, and
helper skills retain their surrounding phase. Unknown identity is diagnosed,
never guessed. Private bindings do not travel between machines. Other authors'
committed source files cannot be repaired by a local checkpoint.
