# Cursor source provenance

Synthetic hook payloads in `tests/test_cursor_adapter.py` and
`tests/test_cursor_ledger.py` follow the pinned upstream token-usage Cursor adapter:
commit f4078277e79c007993e0cb595bb95f924a2a8777, hook ledger generation records.
They contain no personal prompts. Measurements are classified by the vendored parser;
these fixtures do not establish native hook delivery on every Cursor version.
