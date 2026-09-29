"""Durable sessions for always-on agents.

A durable session persists the full conversation transcript, the lifecycle
state, and the context-compaction continuity record to disk after every
mutation. When the daemon restarts it resumes exactly where it left off:
messages, compaction count, and the iterative compaction summary are all
restored.
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

logger = get_logger("always_on.sessions")

SESSION_DIRNAME = "sessions"
MAX_MESSAGES_PER_SESSION = 5000


def _now() -> float:
    return time.time()


@dataclass
class DurableSession:
    """A persistable agent session."""

    session_id: str
    agent_id: str
    created_at: float
    updated_at: float
    lifecycle_state: str = "sleeping"
    messages: list[dict[str, Any]] = field(default_factory=list)
    compaction_count: int = 0
    compaction_state: dict[str, Any] = field(default_factory=dict)
    wake_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lifecycle_state": self.lifecycle_state,
            "messages": [dict(m) for m in self.messages],
            "compaction_count": self.compaction_count,
            "compaction_state": dict(self.compaction_state),
            "wake_history": [dict(w) for w in self.wake_history],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DurableSession:
        messages = data.get("messages") or []
        if not isinstance(messages, list):
            raise ValueError("session messages must be a list")
        for message in messages:
            if not isinstance(message, dict) or "role" not in message:
                raise ValueError("each session message must be a dict with a 'role'")
        return cls(
            session_id=str(data["session_id"]),
            agent_id=str(data["agent_id"]),
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
            lifecycle_state=str(data.get("lifecycle_state") or "sleeping"),
            messages=[dict(m) for m in messages],
            compaction_count=int(data.get("compaction_count") or 0),
            compaction_state=dict(data.get("compaction_state") or {}),
            wake_history=[dict(w) for w in (data.get("wake_history") or [])],
            metadata=dict(data.get("metadata") or {}),
        )


class SessionStore:
    """Atomic, thread-safe persistence for durable sessions.

    Sessions live under ``<state_dir>/always_on/sessions/<session_id>.json``.
    """

    def __init__(self, state_dir: str | Path | None = None) -> None:
        base = Path(state_dir or GhostChimeraConfig.from_env().state_dir).expanduser()
        self.state_dir = base
        self._dir = base / "always_on" / SESSION_DIRNAME
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, agent_id: str, *, metadata: dict[str, Any] | None = None) -> DurableSession:
        """Create a new durable session for an agent."""
        now = _now()
        session = DurableSession(
            session_id=f"session-{uuid.uuid4().hex[:12]}",
            agent_id=agent_id,
            created_at=now,
            updated_at=now,
            lifecycle_state="sleeping",
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._write(session)
        logger.info("Created durable session %s for agent %s", session.session_id, agent_id)
        return session

    def get(self, session_id: str) -> DurableSession | None:
        """Load a session by id, or None when unknown/unreadable."""
        with self._lock:
            return self._read(session_id)

    def get_or_create_for_agent(self, agent_id: str) -> DurableSession:
        """Return the agent's newest session, creating one when absent."""
        with self._lock:
            sessions = self.list_for_agent(agent_id)
            if sessions:
                return sessions[-1]
            return self.create(agent_id)

    def list_for_agent(self, agent_id: str) -> list[DurableSession]:
        """All sessions for one agent, oldest first."""
        with self._lock:
            return [s for s in self.list_all() if s.agent_id == agent_id]

    def list_all(self) -> list[DurableSession]:
        """All sessions, oldest first."""
        with self._lock:
            sessions: list[DurableSession] = []
            if self._dir.exists():
                for path in sorted(self._dir.glob("*.json")):
                    session = self._read(path.stem)
                    if session is not None:
                        sessions.append(session)
            # Total order: timestamps can tie on coarse clocks (Windows), so the
            # unique id breaks ties deterministically.
            return sorted(sessions, key=lambda s: (s.created_at, s.session_id))

    def save(self, session: DurableSession) -> DurableSession:
        """Persist a full session snapshot (marks updated_at)."""
        with self._lock:
            session.updated_at = _now()
            self._write(session)
            return session

    def append_message(self, session_id: str, message: dict[str, Any]) -> DurableSession:
        """Append one message to a session and persist it."""
        if not isinstance(message, dict) or "role" not in message:
            raise ValueError("message must be a dict containing 'role'")
        with self._lock:
            session = self._read(session_id)
            if session is None:
                raise KeyError(f"Unknown session '{session_id}'")
            session.messages.append(dict(message))
            if len(session.messages) > MAX_MESSAGES_PER_SESSION:
                # Hard safety bound: drop oldest non-system messages first.
                overflow = len(session.messages) - MAX_MESSAGES_PER_SESSION
                kept = [m for m in session.messages if m.get("role") == "system"]
                rest = [m for m in session.messages if m.get("role") != "system"]
                session.messages = kept + rest[overflow:]
            session.updated_at = _now()
            self._write(session)
            return session

    def set_state(self, session_id: str, lifecycle_state: str) -> DurableSession:
        """Persist a lifecycle state transition for a session."""
        with self._lock:
            session = self._read(session_id)
            if session is None:
                raise KeyError(f"Unknown session '{session_id}'")
            session.lifecycle_state = lifecycle_state
            session.updated_at = _now()
            self._write(session)
            return session

    def record_wake(
        self,
        session_id: str,
        wake: dict[str, Any],
        *,
        compaction_state: dict[str, Any] | None = None,
        compaction_count: int | None = None,
    ) -> DurableSession:
        """Append a completed wake request to the session history."""
        with self._lock:
            session = self._read(session_id)
            if session is None:
                raise KeyError(f"Unknown session '{session_id}'")
            session.wake_history.append(dict(wake))
            if compaction_state is not None:
                session.compaction_state = dict(compaction_state)
            if compaction_count is not None:
                session.compaction_count = int(compaction_count)
            session.updated_at = _now()
            self._write(session)
            return session

    # ------------------------------------------------------------------
    # IO
    # ------------------------------------------------------------------

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def _write(self, session: DurableSession) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._dir / f".{session.session_id}.tmp"
        tmp.write_text(json.dumps(session.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path(session.session_id))

    def _read(self, session_id: str) -> DurableSession | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable session %s: %s", session_id, exc)
            return None
        try:
            return DurableSession.from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Ignoring malformed session %s: %s", session_id, exc)
            return None


__all__ = ["DurableSession", "SessionStore", "MAX_MESSAGES_PER_SESSION"]
