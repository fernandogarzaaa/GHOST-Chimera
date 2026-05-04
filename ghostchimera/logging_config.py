"""Structured logging configuration for Ghost Chimera."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

_GHOSTCHIMERA_LOG = logging.getLogger("ghostchimera")
_INITIALIZED = False


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``ghostchimera`` root."""
    return logging.getLogger(f"ghostchimera.{name}")


def _configure() -> None:
    """Set up console and file handlers using the resolved config."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    log_level = os.environ.get("GHOSTCHIMERA_LOG_LEVEL", "WARNING").upper()
    state_dir = Path(os.environ.get("GHOSTCHIMERA_STATE_DIR", "~/.ghostchimera")).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    log_file = state_dir / "ghostchimera.log"
    fmt_type = os.environ.get("GHOSTCHIMERA_LOG_FORMAT", "text").lower()

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.WARNING))

    formatter: logging.Formatter
    if fmt_type == "json":

        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                return json.dumps(
                    {
                        "level": record.levelname,
                        "logger": record.name,
                        "msg": record.getMessage(),
                        "ts": self.formatTime(record),
                    }
                )

        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(levelname)s:%(name)s:%(message)s",
        )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    # File handler
    fh = logging.FileHandler(str(log_file))
    fh.setFormatter(formatter)
    root.addHandler(fh)


def ensure_configured() -> None:
    """Ensure logging is configured (no-op if already done)."""
    _configure()
