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
