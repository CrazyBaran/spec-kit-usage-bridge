"""Usage Bridge checkpoint entrypoint; parseable by any Python 3."""
import os
import sys

sys.dont_write_bytecode = True


def _run():
    if sys.version_info < (3, 9):  # noqa: UP036 - entrypoint must run on unsupported Python too
        print('Usage Bridge: Python 3.9+ is required; install a supported Python and reinstall usage-bridge.')
        return 1
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from usage_bridge.checkpoint import checkpoint_entry
    except Exception as exc:
        print('Usage Bridge: cannot load checkpoint ({}); reinstall usage-bridge.'.format(exc))
        return 1
    return checkpoint_entry()


if __name__ == '__main__':
    sys.exit(_run())
