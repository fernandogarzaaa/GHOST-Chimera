"""Config file I/O for Ghost Chimera setup wizard.

Stores user-selected configuration in ~/.ghostchimera/config.json.
This is separate from GhostChimeraConfig (which reads env vars) and
is the canonical config written by the setup wizard.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path.home() / ".ghostchimera"
CONFIG_FILE = DEFAULT_STATE_DIR / "config.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config from disk, returning empty dict if not found."""
    if path is None:
        path = CONFIG_FILE
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    """Write config to disk, creating parent dirs if needed."""
    if path is None:
        path = CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2, sort_keys=True)


def ensure_state_dir(path: Path | None = None) -> Path:
    """Ensure the state directory exists."""
    if path is None:
        path = DEFAULT_STATE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_default_config() -> dict[str, Any]:
    """Return the default empty config structure."""
    return {
        "model": {
            "provider": "",
            "model": "",
            "base_url": "",
        },
        "gateway": {
            "port": 8080,
            "bind": "127.0.0.1",
            "auth": "token",
        },
        "safety": {
            "allow_shell": False,
            "allow_network": False,
            "allow_file_read": False,
            "allow_file_write": False,
        },
        "autonomy": {
            "level": "supervised",
            "max_tool_rounds": None,
            "max_parallel_tasks": None,
            "local_model_profile": "",
            "require_approval_for_high_impact": True,
        },
    }


def config_to_env_vars(config: dict[str, Any]) -> dict[str, str]:
    """Convert config dict to env var names/values for backwards compatibility."""
    env: dict[str, str] = {}
    model = config.get("model", {})
    provider = model.get("provider", "")

    if provider == "openai":
        env["GHOSTCHIMERA_MODEL_PROVIDER"] = "openai"
        if model.get("model"):
            env["OPENAI_MODEL"] = model["model"]
        if model.get("base_url"):
            env["OPENAI_BASE_URL"] = model["base_url"]
    elif provider == "openrouter":
        env["GHOSTCHIMERA_MODEL_PROVIDER"] = "openrouter"
        env["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"
        if model.get("model"):
            env["OPENROUTER_MODEL"] = model["model"]
    elif provider == "anthropic":
        env["GHOSTCHIMERA_MODEL_PROVIDER"] = "anthropic"
        if model.get("model"):
            env["ANTHROPIC_MODEL"] = model["model"]
    elif provider == "custom":
        env["GHOSTCHIMERA_MODEL_PROVIDER"] = "custom"
        if model.get("base_url"):
            env["OPENAI_BASE_URL"] = model["base_url"]
        if model.get("model"):
            env["CUSTOM_MODEL"] = model["model"]
    elif provider == "local":
        env["GHOSTCHIMERA_MODEL_PROVIDER"] = "minimind"
        env["MINIMIND_MODEL_PROFILE"] = model.get("model", "tiny")

    safety = config.get("safety", {})
    env["GHOSTCHIMERA_ALLOW_SHELL"] = "1" if safety.get("allow_shell") else "0"
    env["GHOSTCHIMERA_ALLOW_NETWORK"] = "1" if safety.get("allow_network") else "0"
    env["GHOSTCHIMERA_ALLOW_FILE_READ"] = "1" if safety.get("allow_file_read") else "0"
    env["GHOSTCHIMERA_ALLOW_FILE_WRITE"] = "1" if safety.get("allow_file_write") else "0"

    autonomy = config.get("autonomy", {})
    if autonomy.get("level"):
        env["GHOSTCHIMERA_AUTONOMY_LEVEL"] = str(autonomy["level"])
    if autonomy.get("local_model_profile"):
        env["GHOSTCHIMERA_LOCAL_MODEL_PROFILE"] = str(autonomy["local_model_profile"])

    return env


def get_autonomy_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return persisted autonomy config merged with defaults."""

    base = get_default_config()["autonomy"]
    active = (config or load_config()).get("autonomy", {})
    if not isinstance(active, dict):
        active = {}
    return {**base, **active}
