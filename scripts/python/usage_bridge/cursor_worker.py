"""Bounded, disposable vendor reader used by all Cursor capture modes."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from usage_bridge import tu_compat

    request = json.load(sys.stdin)
    if request["operation"] == "discover":
        sources = tu_compat.cursor_sessions(Path(request["project"]), Path(request["ledger"]),
                                           Path(request["data"]) if request["data"] else None)
        result = [{key: str(getattr(source, key)) if getattr(source, key) is not None else None
                   for key in tu_compat.module().CursorSession.__slots__} for source in sources]
    else:
        source = tu_compat.module().CursorSession(**request["source"])
        result = tu_compat.cursor_parse(source)
    sys.stdout.write(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
