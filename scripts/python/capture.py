"""Usage Bridge — capture entrypoint (see commands/capture.md).

Runs on every Claude Stop through .specify/events.py, so it must never fail: an old Python or a
broken install exits 0 silently. Keep this file parseable by any Python 3.
"""
import os
import sys

sys.dont_write_bytecode = True


def _run():
    if sys.version_info < (3, 9):
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from usage_bridge import cli
    except Exception:
        return 0
    return cli.capture_entry()


if __name__ == "__main__":
    sys.exit(_run())
