"""Single resolver for Ghost Chimera's on-disk state locations.

Every module that needs a default state path asks here instead of
hard-coding ``~/.ghostchimera`` or a CWD-relative file, so
``GHOSTCHIMERA_STATE_DIR`` (Docker, judges, tests) relocates *all* state:
audit log, memory DB, checkpoints, plugins, skills, security events, ...

Resolution is lazy (evaluated on each call, never at import time):

1. ``GHOSTCHIMERA_STATE_DIR`` when set and non-empty;
2. ``~/.ghostchimera``.

Per-file overrides that already exist (``GHOSTCHIMERA_MEMORY_DB``,
``GHOSTCHIMERA_AUDIT_FILE``, ...) keep winning for their one file.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_DIR_ENV = "GHOSTCHIMERA_STATE_DIR"
DEFAULT_STATE_DIRNAME = ".ghostchimera"


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def state_dir() -> Path:
    """The state directory (not created; see :func:`ensure_state_dir`)."""
    return _env_path(STATE_DIR_ENV) or (Path.home() / DEFAULT_STATE_DIRNAME)


def ensure_state_dir() -> Path:
    """Create the state directory owner-only (0700) and return it."""
    from .state_io import ensure_private_dir

    return ensure_private_dir(state_dir())


def state_path(*parts: str) -> Path:
    """A path inside the state directory."""
    return state_dir().joinpath(*parts)


def _file_override(env_var: str, *default_parts: str) -> Path:
    return _env_path(env_var) or state_path(*default_parts)


def memory_db_path() -> Path:
    """Episodic memory SQLite DB (``GHOSTCHIMERA_MEMORY_DB`` overrides)."""
    return _file_override("GHOSTCHIMERA_MEMORY_DB", "memory.sqlite3")


LEGACY_CWD_MEMORY_DB = ".ghostchimera-memory.sqlite3"


def personal_memory_db(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Memory DB for personal ingestion / MiniMind / beta-vision.

    Explicit path wins; otherwise the state-dir DB. Older releases defaulted
    to ``./.ghostchimera-memory.sqlite3`` in the *current directory*; if
    such a file exists here and the state-dir DB does not, keep using it
    so existing data is not orphaned (no new CWD files are ever created).
    """
    if explicit and str(explicit).strip():
        return Path(str(explicit).strip()).expanduser()
    canonical = memory_db_path()
    legacy = Path(LEGACY_CWD_MEMORY_DB)
    if not canonical.exists() and legacy.is_file():
        return legacy
    return canonical


def temporal_graph_db_path() -> Path:
    return _file_override("GHOSTCHIMERA_TEMPORAL_GRAPH_DB", "temporal_graph.sqlite3")


def audit_file_path() -> Path:
    return _file_override("GHOSTCHIMERA_AUDIT_FILE", "audit.json")


def agent_memory_file_path() -> Path:
    """Legacy AgentCore JSON memory (``GHOSTCHIMERA_MEMORY_FILE`` overrides)."""
    return _file_override("GHOSTCHIMERA_MEMORY_FILE", "memory.json")


def security_events_file_path() -> Path:
    return _file_override("GHOSTCHIMERA_SECURITY_EVENTS_FILE", "security_events.json")


def checkpoints_dir() -> Path:
    return _file_override("GHOSTCHIMERA_CHECKPOINT_DIR", "checkpoints")


def plugins_dir() -> Path:
    return _file_override("GHOSTCHIMERA_PLUGINS_DIR", "plugins")


def skills_dir() -> Path:
    return _file_override("GHOSTCHIMERA_SKILLS_DIR", "skills")


__all__ = [
    "STATE_DIR_ENV",
    "agent_memory_file_path",
    "audit_file_path",
    "checkpoints_dir",
    "ensure_state_dir",
    "memory_db_path",
    "personal_memory_db",
    "plugins_dir",
    "security_events_file_path",
    "skills_dir",
    "state_dir",
    "state_path",
    "temporal_graph_db_path",
]
