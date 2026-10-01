"""Bounded, disposable vendor reader used by all Cursor capture modes."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def ledger_evidence(path):
    """Minimal facts supplementing vendor buckets, read within the worker deadline."""
    generations, zeros, branches = [], {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        generation = str(record.get("generation_id") or "unknown")
        if generation not in generations:
            generations.append(generation)
        if record.get("branch"):
            branches.append([record.get("ts"), record["branch"]])
        tokens = record.get("tokens")
        if not isinstance(tokens, dict):
            continue
        values = [tokens.get(key) for key in ("input_tokens", "output_tokens", "cache_read_tokens",
                                              "cache_write_tokens")]
        if all(isinstance(value, int) and not isinstance(value, bool) and value == 0 for value in values):
            zeros.setdefault(generation, set()).add(record.get("model") or "unknown")
    return {str(index): sorted(zeros.get(generation, ())) for index, generation in enumerate(generations)}, branches


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from usage_bridge import tu_compat

    request = json.load(sys.stdin)
    if request["operation"] == "discover":
        sources = tu_compat.cursor_sessions(Path(request["project"]), Path(request["ledger"]),
                                           Path(request["data"]) if request["data"] else None)
        result = [{key: str(getattr(source, key)) if getattr(source, key) is not None else None
                   for key in tu_compat.module().CursorSession.__slots__} for source in sources]
    elif request["operation"] == "export":
        from usage_bridge.paths import is_inside

        path = Path(request["path"])
        data = json.loads(path.read_text(encoding="utf-8"))
        roots = data.get("workspace_roots") or [data.get("cwd")]
        owned = any(isinstance(root, str) and is_inside(root, request["checkouts"]) for root in roots)
        source = tu_compat.cursor_export(path) if owned else None
        result = ({key: str(getattr(source, key)) if getattr(source, key) is not None else None
                   for key in tu_compat.module().CursorSession.__slots__} if source else None)
    else:
        source = tu_compat.module().CursorSession(**request["source"])
        result = tu_compat.cursor_parse(source)
        if source.ledger_path:
            result["_measured_zero"], result["_branches"] = ledger_evidence(source.ledger_path)
    sys.stdout.write(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
