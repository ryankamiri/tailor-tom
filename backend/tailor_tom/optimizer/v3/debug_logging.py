"""V3 debug logging gated by settings.optimizer_debug_enabled."""

import logging
from typing import Any

from tailor_tom.config import settings


def debug_enabled() -> bool:
    """True if optimizer debug logging is enabled (settings gate)."""
    return bool(getattr(settings, "optimizer_debug_enabled", False))


def debug_log(logger: logging.Logger, event: str, **kwargs: Any) -> None:
    """Emit a single debug log line only when optimizer_debug_enabled is True.
    When the gate is on, ensures the logger's level allows DEBUG so messages are not dropped in dev."""
    if not debug_enabled():
        return
    parts = [f"DEBUG {event}"]
    for k, v in kwargs.items():
        parts.append(f"{k}={v!r}" if isinstance(v, (str, int, float, bool)) else f"{k}=<{type(v).__name__}>")
    msg = " ".join(parts)
    # Ensure DEBUG is visible when gate is on (e.g. dev runs with root logger at INFO)
    old_level = logger.level
    if logger.getEffectiveLevel() > logging.DEBUG:
        logger.setLevel(logging.DEBUG)
    try:
        logger.debug(msg)
    finally:
        if old_level != logger.level:
            logger.setLevel(old_level)
