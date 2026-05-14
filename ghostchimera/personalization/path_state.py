"""Persisted active Ghost path selection."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..control_plane.config import load_config, save_config
from .path_synthesizer import synthesize_path

DEFAULT_PROFILE_ID = "autonomous-engineer"
DEFAULT_PREFERENCES = {"training_mode": "rag-first", "approval_level": "supervised"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_active_ghost_path(
    *,
    config: dict[str, Any] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Return the selected Ghost path, defaulting to Autonomous Engineer."""

    data = config if config is not None else load_config(config_path)
    path_config = data.get("ghost_path", {}) if isinstance(data, dict) else {}
    if not isinstance(path_config, dict):
        path_config = {}
    profile_id = str(path_config.get("profile_id") or DEFAULT_PROFILE_ID)
    preferences = path_config.get("preferences") or dict(DEFAULT_PREFERENCES)
    if not isinstance(preferences, dict):
        preferences = dict(DEFAULT_PREFERENCES)
    synthesis = synthesize_path(profile_id, preferences=preferences)
    return {
        "ok": True,
        "profile_id": profile_id,
        "preferences": preferences,
        "synthesis": synthesis,
        "updated_at": str(path_config.get("updated_at") or ""),
    }


def set_active_ghost_path(
    profile_id: str,
    *,
    preferences: dict[str, Any] | None = None,
    config_path: Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the selected Ghost path and return its synthesized config."""

    active_preferences = preferences or dict(DEFAULT_PREFERENCES)
    synthesis = synthesize_path(profile_id, preferences=active_preferences)
    data = config if config is not None else load_config(config_path)
    if not isinstance(data, dict):
        data = {}
    path_config = {
        "profile_id": profile_id,
        "preferences": active_preferences,
        "synthesis": synthesis,
        "updated_at": _now(),
    }
    data["ghost_path"] = path_config
    if config is None:
        save_config(data, config_path)
    return {"ok": True, **path_config}
