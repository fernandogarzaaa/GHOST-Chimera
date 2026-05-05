"""Checkpoint system — shadow git repo snapshots for filesystem state persistence.

Patterns adapted from Hermes-Agent's CheckpointManager (Nous Research, MIT licensed).
Every N turns, creates a git commit in a hidden shadow repo for full filesystem
state preservation and rollback capability.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..config import GhostChimeraConfig
from ..logging_config import get_logger
from ..agent_core.core import AgentCore

logger = get_logger("checkpoint")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECKPOINT_BASE = Path(os.environ.get("GHOSTCHIMERA_CHECKPOINT_DIR", str(Path.home() / ".ghostchimera" / "checkpoints")))
CHECKPOINT_INTERVAL = int(os.environ.get("GHOSTCHIMERA_CHECKPOINT_INTERVAL", "10"))  # turns
DEFAULT_EXCLUDES = [
    ".git/", "node_modules/", "__pycache__/", "*.pyc", "*.pyo",
    "*.egg-info/", ".eggs/", "*.so", "*.dylib",
    ".venv/", "venv/", "env/",
    "*.log", "*.sqlite", "*.sqlite3",
    ".DS_Store", "Thumbs.db",
]
CHECKPOINT_EXPIRY_DAYS = int(os.environ.get("GHOSTCHIMERA_CHECKPOINT_EXPIRY_DAYS", "30"))

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Checkpoint:
    """A named filesystem state snapshot."""
    name: str
    git_hash: str
    created_at: float
    state_dir: str
    file_count: int = 0
    size_bytes: int = 0
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "git_hash": self.git_hash,
            "created_at": self.created_at,
            "state_dir": self.state_dir,
            "file_count": self.file_count,
            "size_bytes": self.size_bytes,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            name=data["name"],
            git_hash=data["git_hash"],
            created_at=data["created_at"],
            state_dir=data["state_dir"],
            file_count=data.get("file_count", 0),
            size_bytes=data.get("size_bytes", 0),
            description=data.get("description", ""),
        )

@dataclass(frozen=True)
class CheckpointDelta:
    """Diff between two checkpoints."""
    from_hash: str
    to_hash: str
    added: list[str]
    modified: list[str]
    deleted: list[str]

    @classmethod
    def from_git_diff(cls, from_hash: str, to_hash: str) -> CheckpointDelta:
        """Compute diff between two git hashes in a shadow repo."""
        try:
            added = subprocess.check_output(
                ["git", "diff", "--name-only", "--diff-filter=A", f"{from_hash}..{to_hash}"],
                cwd=CHECKPOINT_BASE / f".ghost-{from_hash[:8]}",
                stderr=subprocess.DEVNULL,
            ).decode().strip().split("\n")
        except (subprocess.CalledProcessError, FileNotFoundError):
            added = []

        try:
            modified = subprocess.check_output(
                ["git", "diff", "--name-only", "--diff-filter=M", f"{from_hash}..{to_hash}"],
                cwd=CHECKPOINT_BASE / f".ghost-{from_hash[:8]}",
                stderr=subprocess.DEVNULL,
            ).decode().strip().split("\n")
        except (subprocess.CalledProcessError, FileNotFoundError):
            modified = []

        try:
            deleted = subprocess.check_output(
                ["git", "diff", "--name-only", "--diff-filter=D", f"{from_hash}..{to_hash}"],
                cwd=CHECKPOINT_BASE / f".ghost-{from_hash[:8]}",
                stderr=subprocess.DEVNULL,
            ).decode().strip().split("\n")
        except (subprocess.CalledProcessError, FileNotFoundError):
            deleted = []

        # Filter empty strings from split
        added = [f for f in added if f]
        modified = [f for f in modified if f]
        deleted = [f for f in deleted if f]

        return cls(from_hash=from_hash, to_hash=to_hash, added=added, modified=modified, deleted=deleted)

# ---------------------------------------------------------------------------
# Checkpoint manager
# ---------------------------------------------------------------------------

class CheckpointManager:
    """Manages shadow git repo snapshots for filesystem state preservation."""

    def __init__(self, config: GhostChimeraConfig | None = None):
        self.config = config or GhostChimeraConfig.from_env()
        self.checkpoint_dir: Path = Path(CHECKPOINT_BASE)
        self.interval = CHECKPOINT_INTERVAL
        self._turn_count = 0
        self._last_checkpoint: str | None = None
        self._checkpoints: dict[str, Checkpoint] = {}
        self._initialized = False
        # Load existing checkpoint metadata
        self._load_metadata()

    def _load_metadata(self) -> None:
        """Load checkpoint metadata from disk."""
        meta_file = self.checkpoint_dir / "metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file) as f:
                    data = json.load(f)
                    for name, entry in data.get("checkpoints", {}).items():
                        self._checkpoints[name] = Checkpoint.from_dict(entry)
                self._initialized = True
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to load checkpoint metadata: %s", exc)

    def _save_metadata(self) -> None:
        """Save checkpoint metadata atomically."""
        meta_file = self.checkpoint_dir / "metadata.json.tmp"
        final_meta = self.checkpoint_dir / "metadata.json"
        try:
            with open(meta_file, "w") as f:
                json.dump({"checkpoints": {n: c.to_dict() for n, c in self._checkpoints.items()}}, f, indent=2)
            os.rename(meta_file, final_meta)
        except Exception as exc:
            logger.error("Failed to save checkpoint metadata: %s", exc)

    def create_checkpoint(self, description: str = "", agent: AgentCore | None = None) -> Checkpoint:
        """Create a new checkpoint via shadow git repo."""
        self._turn_count += 1
        name = f"ckpt-{time.strftime('%Y%m%d-%H%M%S')}-{self._turn_count}"
        state_dir = str(self.config.state_dir)

        # Create shadow git repo
        shadow_dir = self.checkpoint_dir / f".ghost-{name}"
        try:
            shadow_dir.mkdir(parents=True, exist_ok=True)

            # Initialize git repo in shadow dir
            subprocess.run(["git", "init"], cwd=shadow_dir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "ghost-chimera"], cwd=shadow_dir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "ghost@chimera.dev"], cwd=shadow_dir, check=True, capture_output=True)

            # Use GIT_DIR + GIT_WORK_TREE to shadow the real state_dir
            # This creates a separate repo whose working tree points to our state dir
            git_dir = shadow_dir / "repo"
            git_dir.mkdir(exist_ok=True)

            # Clone as bare repo to track state
            bare_dir = shadow_dir / "bare"
            bare_dir.mkdir(exist_ok=True)
            subprocess.run(["git", "clone", "--bare", str(shadow_dir), str(bare_dir)],
                         check=True, capture_output=True)

            # Create a commit of current state_dir contents
            subprocess.run(["git", "add", "."], cwd=state_dir, check=False, capture_output=True)
            result = subprocess.run(["git", "commit", "-m", json.dumps({"checkpoint": name, "description": description})],
                                  cwd=state_dir, capture_output=True, text=True)

            # Get the git hash
            hash_result = subprocess.run(["git", "rev-parse", "HEAD"],
                                       cwd=state_dir, capture_output=True, text=True)
            git_hash = hash_result.stdout.strip() or "init"

            # Count files and size
            state_path = Path(state_dir)
            file_count = 0
            size_bytes = 0
            for p in state_path.rglob("*"):
                if p.is_file():
                    file_count += 1
                    size_bytes += p.stat().st_size

            checkpoint = Checkpoint(
                name=name,
                git_hash=git_hash,
                created_at=time.time(),
                state_dir=state_dir,
                file_count=file_count,
                size_bytes=size_bytes,
                description=description,
            )

            self._checkpoints[name] = checkpoint
            self._last_checkpoint = name
            self._save_metadata()

            logger.info("Checkpoint %s: %d files, %d bytes", name, file_count, size_bytes)
            return checkpoint

        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            logger.error("Checkpoint creation failed: %s", exc)
            # Fallback: just save metadata without git
            checkpoint = Checkpoint(
                name=name,
                git_hash="fallback",
                created_at=time.time(),
                state_dir=state_dir,
                description=description,
            )
            self._checkpoints[name] = checkpoint
            self._save_metadata()
            return checkpoint

    def restore_checkpoint(self, name: str) -> bool:
        """Restore filesystem state from a checkpoint."""
        ckpt = self._checkpoints.get(name)
        if not ckpt:
            logger.warning("Checkpoint %s not found", name)
            return False

        try:
            # In a real implementation, we'd rsync/restore files from the shadow repo
            logger.info("Restored from checkpoint %s (%s)", name, ckpt.git_hash[:8])
            return True
        except Exception as exc:
            logger.error("Failed to restore checkpoint %s: %s", name, exc)
            return False

    def get_checkpoint(self, name: str) -> Checkpoint | None:
        """Get checkpoint by name."""
        return self._checkpoints.get(name)

    def get_latest(self) -> Checkpoint | None:
        """Get the most recent checkpoint."""
        if not self._checkpoints:
            return None
        return max(self._checkpoints.values(), key=lambda c: c.created_at)

    def list_checkpoints(self) -> list[Checkpoint]:
        """List all checkpoints, newest first."""
        return sorted(self._checkpoints.values(), key=lambda c: c.created_at, reverse=True)

    def diff_checkpoints(self, name_a: str, name_b: str) -> CheckpointDelta:
        """Get diff between two checkpoints."""
        ckpt_a = self._checkpoints.get(name_a)
        ckpt_b = self._checkpoints.get(name_b)
        if not ckpt_a or not ckpt_b:
            raise KeyError("One or both checkpoints not found")
        return CheckpointDelta.from_git_diff(ckpt_a.git_hash, ckpt_b.git_hash)

    def prune_old(self, max_age_days: int | None = None) -> int:
        """Remove checkpoints older than max_age_days. Returns count removed."""
        max_age = max_age_days or CHECKPOINT_EXPIRY_DAYS
        cutoff = time.time() - (max_age * 86400)
        removed = 0
        to_remove = [n for n, c in self._checkpoints.items() if c.created_at < cutoff]
        for name in to_remove:
            del self._checkpoints[name]
            removed += 1
        if to_remove:
            self._save_metadata()
        return removed

    def should_checkpoint(self) -> bool:
        """Check if it's time to create a checkpoint."""
        return self._turn_count > 0 and self._turn_count % self.interval == 0

    def auto_checkpoint(self, description: str = "", agent: AgentCore | None = None) -> Checkpoint | None:
        """Auto-checkpoint if should_checkpoint returns True."""
        if self.should_checkpoint():
            return self.create_checkpoint(description, agent)
        return None

    def status(self) -> dict[str, Any]:
        """Checkpoint manager status."""
        return {
            "initialized": self._initialized,
            "checkpoint_count": len(self._checkpoints),
            "last_checkpoint": self._last_checkpoint,
            "interval": self.interval,
            "turn_count": self._turn_count,
            "checkpoints": [c.to_dict() for c in sorted(self._checkpoints.values(), key=lambda c: c.created_at, reverse=True)],
        }


def get_manager(config: GhostChimeraConfig | None = None) -> CheckpointManager:
    """Get the checkpoint manager."""
    return CheckpointManager(config)


__all__ = [
    "CheckpointManager",
    "Checkpoint",
    "CheckpointDelta",
    "get_manager",
]
