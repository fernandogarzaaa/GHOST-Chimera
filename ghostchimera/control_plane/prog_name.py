"""The command name the user actually typed, for hints and usage lines.

The package installs two console scripts, ``ghost`` and ``ghostchimera``.
Hints should echo whichever one the user invoked instead of always saying
``ghostchimera``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_KNOWN = ("ghost", "ghostchimera")


def prog_name(argv0: str | None = None) -> str:
    """Return ``ghost`` or ``ghostchimera`` (the basename of ``sys.argv[0]``).

    Anything else (``python -m ghostchimera``, ``__main__.py``, a test runner)
    falls back to ``ghost``, the short name the README uses.
    """
    raw = argv0 if argv0 is not None else (sys.argv[0] if sys.argv else "")
    name = Path(str(raw or "")).name
    lowered = name.lower()
    for suffix in ("-script.py", ".exe", ".py"):
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            lowered = name.lower()
    return name if name in _KNOWN else "ghost"
