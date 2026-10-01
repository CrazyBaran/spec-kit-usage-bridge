"""Bounded, disposable vendor reader used by all Cursor capture modes."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def ledger_evidence(path):
    """Minimal facts supplementing vendor buckets, read within the worker deadline."""
    generations, parents, children, branches = [], {}, {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if not record.get("generation_id"):
            continue
        generation = str(record["generation_id"])
        if generation not in generations:
            generations.append(generation)
        if record.get("branch"):
            branches.append([record.get("ts"), record["branch"]])
        hook = record.get("hook")
        child_key = (generation, record.get("subagent_id") or "unknown")
        if hook == "subagentStart":
            children[child_key] = {"model": record.get("subagent_model") or "unknown", "done": False}
            continue
        if hook not in {"stop", "afterAgentResponse", "subagentStop"}:
            continue
        tokens = record.get("tokens") or {}
        if not isinstance(tokens, dict):
            tokens = {}
        values = [tokens.get(key) for key in ("input_tokens", "output_tokens", "cache_read_tokens",
                                              "cache_write_tokens")]
        zero = all(isinstance(value, int) and not isinstance(value, bool) and value == 0 for value in values)
        if hook == "subagentStop":
            child = children.setdefault(child_key, {"model": "unknown", "done": False})
            if not child["done"]:  # The vendor accepts only the first stop for each child.
                child.update(model=record.get("model") or child["model"], done=True, zero=zero)
        else:
            parent = parents.setdefault(generation, {"model": "unknown", "zero": True})
            parent["model"] = record.get("model") or parent["model"]
            # Require consistent explicit evidence; a missing completion never proves zero.
            parent["zero"] = parent["zero"] and zero
    evidence = {}
    for generation, parent in parents.items():
        evidence.setdefault(generation, {}).setdefault(parent["model"], []).append(parent["zero"])
    for (generation, _), child in children.items():
        if child["done"]:
            evidence.setdefault(generation, {}).setdefault(child["model"], []).append(child["zero"])
    zeros = {generation: sorted(model for model, contributors in models.items() if all(contributors))
             for generation, models in evidence.items()}
    return {str(index): zeros.get(generation, []) for index, generation in enumerate(generations)}, branches


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
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            roots = data.get("workspace_roots") or [data.get("cwd")]
            owned = any(isinstance(root, str) and is_inside(root, request["checkouts"]) for root in roots)
            source = tu_compat.cursor_export(path) if owned else None
        except (OSError, ValueError, AttributeError, TypeError, SystemExit):
            source = None  # One invalid configured export must not suppress healthy sources.
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
