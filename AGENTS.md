# Repository instructions

## Commit attribution

For every new commit Codex creates in this repository:

- Keep the human's configured Git author and committer identity. Do not replace it
  with a Codex identity or change Git identity settings unless explicitly requested.
- Append this trailer exactly once, separated from the commit body by a blank line:

  ```text
  Co-authored-by: Codex <codex@openai.com>
  ```

- Before pushing, inspect the new commits and verify that each includes the trailer.
- Preserve the trailer in any new squash commit Codex creates for its changes.
- Do not rewrite existing or merged commits just to change attribution unless
  explicitly requested.

This rule applies to Codex-created commits, including documentation-only changes.
It does not require adding Codex attribution to commits made independently by humans.
