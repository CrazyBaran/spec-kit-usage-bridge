"""The rotating log file under the runtime dir — the only place capture reports problems."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOGGER_NAME = "usage_bridge"
LOG_REL = Path("logs") / "usage-bridge.log"
_LEVELS = {"error": logging.ERROR, "warning": logging.WARNING, "info": logging.INFO, "debug": logging.DEBUG}


class _SilentRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - stdlib override
        """Logging is best-effort; stderr is forbidden on the hook path."""


def get_logger(runtime: Path, level: str) -> logging.Logger:
    """A file-only logger writing to ``runtime/logs/usage-bridge.log`` (1 MB, two backups)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.propagate = False
    logger.setLevel(_LEVELS.get(level, logging.INFO))
    path = (Path(runtime) / LOG_REL).resolve()
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == path:
            return logger
        logger.removeHandler(handler)
        handler.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _SilentRotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8",
                                                   delay=True)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger
