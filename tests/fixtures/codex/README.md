# Codex source provenance

Synthetic records in `tests/codex_builders.py` follow the public Codex rollout shapes
observed on 2026-10-01: `session_meta`, `turn_context`, `event_msg/user_message`,
and `event_msg/token_count` with cumulative and latest usage. No personal transcript
text is retained. Counter semantics are checked against OpenAI's token accounting notes:
https://github.com/openai/symphony/blob/main/elixir/docs/token_accounting.md

Fixtures deliberately include incomplete/invalid variants; those must downgrade
coverage, not be interpreted as a supported exact source format.
