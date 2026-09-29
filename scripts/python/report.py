"""Usage Bridge — report entrypoint (see commands/report.md). Keep this file parseable by any Python 3."""
import os
import sys

sys.dont_write_bytecode = True

PYTHON_FIX = ("Install Python 3.9+ with python3 or python on PATH (or in the project .venv), "
              "then run specify extension add usage-bridge again.")


def _run():
    if sys.version_info < (3, 9):
        print("Usage Bridge: Python %d.%d is too old. %s" % (sys.version_info[0], sys.version_info[1], PYTHON_FIX))
        return 1
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from usage_bridge import cli
    except Exception as exc:
        print("Usage Bridge: cannot load the extension (%s: %s). Reinstall it with specify extension add "
              "usage-bridge." % (type(exc).__name__, exc))
        return 1
    return cli.report_entry()


if __name__ == "__main__":
    sys.exit(_run())
