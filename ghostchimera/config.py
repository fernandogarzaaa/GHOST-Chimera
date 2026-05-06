"""Runtime configuration for Ghost Chimera."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .safety_layer.gating import ExecutionPolicy


@dataclass(frozen=True)
class GhostChimeraConfig:
    """Resolved runtime configuration with safe defaults."""

    state_dir: Path
    memory_db: Path
    audit_file: Path
    policy: ExecutionPolicy
    local_model_path: str
    local_model_profile: str
    local_model_gpu_layers: int
    autonomy_level: str

    @classmethod
    def from_env(cls) -> GhostChimeraConfig:
        state_dir = _expand_path(os.environ.get("GHOSTCHIMERA_STATE_DIR", "~/.ghostchimera"))
        memory_db = _expand_path(os.environ.get("GHOSTCHIMERA_MEMORY_DB", str(state_dir / "memory.sqlite3")))
        audit_file = _expand_path(os.environ.get("GHOSTCHIMERA_AUDIT_FILE", str(state_dir / "audit.json")))
        return cls(
            state_dir=state_dir,
            memory_db=memory_db,
            audit_file=audit_file,
            policy=ExecutionPolicy.from_env(),
            local_model_path=os.environ.get("GHOSTCHIMERA_LOCAL_MODEL_PATH", ""),
            local_model_profile=os.environ.get("GHOSTCHIMERA_LOCAL_MODEL_PROFILE", "tiny"),
            local_model_gpu_layers=int(os.environ.get("GHOSTCHIMERA_LOCAL_MODEL_GPU_LAYERS", "0")),
            autonomy_level=os.environ.get("GHOSTCHIMERA_AUTONOMY_LEVEL", "supervised"),
        )

    def ensure_state_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.memory_db.parent.mkdir(parents=True, exist_ok=True)
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_dir": str(self.state_dir),
            "memory_db": str(self.memory_db),
            "audit_file": str(self.audit_file),
            "policy": {
                "ghost_mode": self.policy.ghost_mode,
                "allow_shell": self.policy.allow_shell,
                "allow_network": self.policy.allow_network,
                "allow_file_read": self.policy.allow_file_read,
                "allow_file_write": self.policy.allow_file_write,
                "allowed_roots": list(self.policy.allowed_roots),
                "shell_timeout_seconds": self.policy.shell_timeout_seconds,
                "output_limit_bytes": self.policy.output_limit_bytes,
                "production": self.policy.production_guardrails.to_dict(),
            },
            "local_model": {
                "path": self.local_model_path,
                "profile": self.local_model_profile,
                "gpu_layers": self.local_model_gpu_layers,
            },
            "autonomy_level": self.autonomy_level,
        }


def _expand_path(value: str) -> Path:
    try:
        return Path(value).expanduser()
    except RuntimeError:
        if value.startswith("~/"):
            return Path.cwd() / value[2:]
        if value == "~":
            return Path.cwd()
        return Path(value)
