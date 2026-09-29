"""Persistent agent identity for always-on agents.

Every always-on agent owns a stable identity record that survives daemon
restarts. The identity is the anchor that durable sessions, wake requests,
and console status rows all reference.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...config import GhostChimeraConfig
from ...logging_config import get_logger

logger = get_logger("always_on.identity")

IDENTITY_DIRNAME = "identities"


@dataclass(frozen=True)
class AgentIdentity:
    """Stable identity record for one always-on agent."""

    agent_id: str
    name: str
    created_at: float
    last_seen: float
    lifecycle_state: str = "sleeping"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "lifecycle_state": self.lifecycle_state,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentIdentity:
        return cls(
            agent_id=str(data["agent_id"]),
            name=str(data.get("name") or data["agent_id"]),
            created_at=float(data.get("created_at") or 0.0),
            last_seen=float(data.get("last_seen") or 0.0),
            lifecycle_state=str(data.get("lifecycle_state") or "sleeping"),
            metadata=dict(data.get("metadata") or {}),
        )


class IdentityStore:
    """Atomic, thread-safe persistence for agent identities.

    Identities live under ``<state_dir>/always_on/identities/<agent_id>.json``.
    Every mutation writes through a temp file plus ``os.replace`` so a crash
    never leaves a half-written record.
    """

    def __init__(self, state_dir: str | Path | None = None) -> None:
        base = Path(state_dir or GhostChimeraConfig.from_env().state_dir).expanduser()
        self.state_dir = base
        self._dir = base / "always_on" / IDENTITY_DIRNAME
        self._lock = threading.RLock()
        self._cache: dict[str, AgentIdentity] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, name: str, *, metadata: dict[str, Any] | None = None) -> AgentIdentity:
        """Create a new identity with a fresh stable id."""
        agent_id = f"ghost-{uuid.uuid4().hex[:12]}"
        now = time.time()
        identity = AgentIdentity(
            agent_id=agent_id,
            name=name.strip() or agent_id,
            created_at=now,
            last_seen=now,
            lifecycle_state="sleeping",
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._write(identity)
            self._cache[agent_id] = identity
        logger.info("Created agent identity %s (%s)", agent_id, identity.name)
        return identity

    def get(self, agent_id: str) -> AgentIdentity | None:
        """Return the identity, preferring the in-memory cache."""
        with self._lock:
            cached = self._cache.get(agent_id)
            if cached is not None:
                return cached
            identity = self._read(agent_id)
            if identity is not None:
                self._cache[agent_id] = identity
            return identity

    def get_or_create_primary(self, name: str = "ghost-primary") -> AgentIdentity:
        """Return the daemon's primary identity, creating it on first run."""
        with self._lock:
            for identity in self.list():
                if identity.name == name:
                    return identity
            return self.create(name)

    def list(self) -> list[AgentIdentity]:
        """List all persisted identities, oldest first."""
        with self._lock:
            identities: dict[str, AgentIdentity] = {}
            if self._dir.exists():
                for path in sorted(self._dir.glob("*.json")):
                    identity = self._read(path.stem)
                    if identity is not None:
                        identities[identity.agent_id] = identity
            for agent_id, identity in self._cache.items():
                identities.setdefault(agent_id, identity)
            return sorted(identities.values(), key=lambda item: item.created_at)

    def touch(self, agent_id: str, *, lifecycle_state: str | None = None) -> AgentIdentity | None:
        """Refresh last_seen (and optionally the lifecycle state)."""
        with self._lock:
            identity = self.get(agent_id)
            if identity is None:
                return None
            updated = AgentIdentity(
                agent_id=identity.agent_id,
                name=identity.name,
                created_at=identity.created_at,
                last_seen=time.time(),
                lifecycle_state=lifecycle_state or identity.lifecycle_state,
                metadata=dict(identity.metadata),
            )
            self._write(updated)
            self._cache[agent_id] = updated
            return updated

    def set_state(self, agent_id: str, lifecycle_state: str) -> AgentIdentity | None:
        """Persist a lifecycle state transition for an agent."""
        return self.touch(agent_id, lifecycle_state=lifecycle_state)

    # ------------------------------------------------------------------
    # IO
    # ------------------------------------------------------------------

    def _path(self, agent_id: str) -> Path:
        return self._dir / f"{agent_id}.json"

    def _write(self, identity: AgentIdentity) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._dir / f".{identity.agent_id}.tmp"
        tmp.write_text(json.dumps(identity.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path(identity.agent_id))

    def _read(self, agent_id: str) -> AgentIdentity | None:
        path = self._path(agent_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable identity %s: %s", agent_id, exc)
            return None
        try:
            return AgentIdentity.from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Ignoring malformed identity %s: %s", agent_id, exc)
            return None


__all__ = ["AgentIdentity", "IdentityStore"]
