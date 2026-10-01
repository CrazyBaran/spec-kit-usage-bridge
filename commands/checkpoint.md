---
description: "Preview or bind one observed phase invocation to its feature"
scripts:
  py: scripts/python/checkpoint.py
---
Run `{SCRIPT}` from the project root with the explicit feature directory and canonical observed phase.

- For the `after_specify` workflow checkpoint, use the feature directory resolved by that invocation:
  `--feature "FEATURE_DIRECTORY" --phase specify --workflow --latest --apply`.
- For later core or extension commands, checkpoint each invocation separately with its own feature and phase,
  e.g. `--feature "specs/FEATURE-B" --phase clarify --latest --apply` or
  `--feature "specs/FEATURE-C" --phase superspec.brainstorm --latest --apply`.
- Supply verified `--runtime claude|codex|cursor --session-id SESSION_ID`. Codex may omit these when its shell
  supplies `CODEX_THREAD_ID`. Claude/Cursor require explicit native session IDs. If identity is unavailable,
  show the warning and continue specification work. Never guess from the newest transcript or feature.json.
- Manual use previews by default. Show the selected session, phase, invocation timestamp and destination before
  applying a historical repair. Repeated phases require `--invocation-ts TIMESTAMP` or an explicit `--latest`.
  Example historical preview: `--runtime codex --session-id SESSION_ID --feature "specs/FEATURE-B"
  --phase specify --invocation-ts 2026-10-01T08:00:02.000Z`. Add `--apply` to persist that selection.
- A helper brainstorming skill keeps the surrounding phase; do not invent an extension invocation for it.
- A binding affects one invocation only. Switching features requires another explicit checkpoint. Repairing an
  earlier phase is separate from checkpointing ongoing work; neither implies automatic capture of later phases.
- Bindings live in private runtime state. Reports use existing measured usage; missing or ambiguous counts remain
  unavailable. Raw transcripts and other contributors' source files are never rewritten. A failed refresh after
  saving can be retried using capture. Show operational warnings without blocking the workflow (`--workflow`).
