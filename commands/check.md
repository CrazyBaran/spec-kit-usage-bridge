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
