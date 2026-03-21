"""In-memory log capture for Celery task execution.

Used to capture verbose optimizer debug output during a task and store it
in the database on failure so it can be inspected via the admin page.

Safe to use in Celery prefork workers (one task per process at a time).
"""

from __future__ import annotations

import io
import logging
from contextlib import contextmanager
from typing import Generator

from tailor_tom.config import settings

# Loggers whose level is temporarily lowered to DEBUG during capture.
_LOGGERS_TO_DEBUG = [
    "tailor_tom.optimizer.v3",
    "tailor_tom.optimizer",
    "tailor_tom",
    "worker.tasks",
]

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_MAX_LOG_BYTES = 200_000  # 200 KB cap


class _LogCapture:
    """Wraps the StringIO buffer; allows reading current value mid-context."""

    def __init__(self, buf: io.StringIO) -> None:
        self._buf = buf

    def getvalue(self) -> str:
        return self._buf.getvalue()


@contextmanager
def capture_task_logs() -> Generator[_LogCapture, None, None]:
    """Context manager that captures all log output during optimizer task execution.

    Temporarily:
    - Lowers log level to DEBUG for optimizer and task loggers
    - Sets settings.optimizer_debug_enabled = True so debug_log() gates pass
    - Attaches a StreamHandler to the root logger that writes to a StringIO buffer

    Yields a _LogCapture object whose .getvalue() returns current captured text.

    On exit, all log levels and settings are restored and the handler is removed.
    """
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    # Save state
    old_debug_enabled = getattr(settings, "optimizer_debug_enabled", False)
    lowered_loggers: list[tuple[logging.Logger, int]] = []

    try:
        # Enable debug_log() gates
        settings.optimizer_debug_enabled = True

        # Lower levels on specific loggers so DEBUG records flow through
        for name in _LOGGERS_TO_DEBUG:
            lgr = logging.getLogger(name)
            lowered_loggers.append((lgr, lgr.level))
            lgr.setLevel(logging.DEBUG)

        # Attach handler to root so all loggers feed into it
        root = logging.getLogger()
        root.addHandler(handler)

        yield _LogCapture(buf)

    finally:
        # Remove handler first to stop capturing
        logging.getLogger().removeHandler(handler)

        # Restore log levels
        for lgr, old_level in lowered_loggers:
            lgr.setLevel(old_level)

        # Restore debug flag
        settings.optimizer_debug_enabled = old_debug_enabled

        handler.close()
        buf.close()
