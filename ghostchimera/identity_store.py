"""Persistent agent identity for Ghost Chimera.

The agent's identity (stable id, name, capabilities, owner, and a public-key
slot reserved for future signing) lives in the state dir as JSON and is
loaded on startup, so the identity survives restarts. Writes are atomic
(tmp file + rename). A corrupted identity file is quarantined aside and a
fresh identity is created instead of crashing.
"""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .logging_config import get_logger

logger = get_logger("identity_store")

DEFAULT_IDENTITY_NAME = "ghost-chimera"
_ID_PREFIX = "ghost-"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _new_identity_id() -> str:
    return f"{_ID_PREFIX}{uuid.uuid4().hex[:12]}"


@dataclass
class AgentIdentity:
    """A persistent, restart-surviving agent identity record."""

    id: str
    name: str = DEFAULT_IDENTITY_NAME
    created_at: str = ""
    capabilities: list[str] = field(default_factory=list)
    owner: str = ""
    public_key: str = ""  # reserved slot for future identity signing
    rotated_at: str | None = None
    previous_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> AgentIdentity:
        """Build an identity from parsed JSON, raising ValueError if invalid."""
        if not isinstance(data, dict):
            raise ValueError("identity payload must be a JSON object")
        identity_id = data.get("id")
        if not isinstance(identity_id, str) or not identity_id:
            raise ValueError("identity 'id' must be a non-empty string")
        name = data.get("name", DEFAULT_IDENTITY_NAME)
        if not isinstance(name, str) or not name:
            raise ValueError("identity 'name' must be a non-empty string")
        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(isinstance(c, str) for c in capabilities):
            raise ValueError("identity 'capabilities' must be a list of strings")
        owner = data.get("owner", "")
        if not isinstance(owner, str):
            raise ValueError("identity 'owner' must be a string")
        public_key = data.get("public_key", "")
        if not isinstance(public_key, str):
            raise ValueError("identity 'public_key' must be a string")
        rotated_at = data.get("rotated_at")
        if rotated_at is not None and not isinstance(rotated_at, str):
            raise ValueError("identity 'rotated_at' must be a string or null")
        previous_ids = data.get("previous_ids", [])
        if not isinstance(previous_ids, list) or not all(isinstance(p, str) for p in previous_ids):
            raise ValueError("identity 'previous_ids' must be a list of strings")
        created_at = data.get("created_at", "")
        if not isinstance(created_at, str):
            raise ValueError("identity 'created_at' must be a string")
        return cls(
            id=identity_id,
            name=name,
            created_at=created_at,
            capabilities=list(capabilities),
            owner=owner,
            public_key=public_key,
            rotated_at=rotated_at,
            previous_ids=list(previous_ids),
        )


class IdentityStore:
    """File-backed identity store rooted at the Ghost state dir.

    Layout: ``<state_dir>/identity/identity.json``. Mirrors the
    TrustRuntimeStore persistence pattern (JSON files, atomic writes).
    """

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.identity_dir = self.state_dir / "identity"
        self.identity_path = self.identity_dir / "identity.json"
        self.identity_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> AgentIdentity | None:
        """Return the stored identity, or None when no valid identity exists.

        A corrupted file is quarantined aside (never deleted silently) and
        treated as missing so callers can re-initialize instead of crashing.
        """
        if not self.identity_path.exists():
            return None
        try:
            raw = self.identity_path.read_text(encoding="utf-8")
            return AgentIdentity.from_dict(json.loads(raw))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            quarantined = self._quarantine()
            logger.warning("Identity file %s unreadable (%s); quarantined to %s",
                           self.identity_path, exc, quarantined)
            return None

    def save(self, identity: AgentIdentity) -> AgentIdentity:
        """Persist the identity atomically (tmp file + rename)."""
        if not isinstance(identity, AgentIdentity):
            raise TypeError("identity must be an AgentIdentity")
        # Re-validate through from_dict so only well-formed records are stored.
        AgentIdentity.from_dict(identity.to_dict())
        tmp = self.identity_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(identity.to_dict(), indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, self.identity_path)
        return identity

    def load_or_create(self, name: str | None = None) -> AgentIdentity:
        """Return the stored identity, creating and persisting one if needed."""
        existing = self.load()
        if existing is not None:
            return existing
        identity = AgentIdentity(
            id=_new_identity_id(),
            name=name or DEFAULT_IDENTITY_NAME,
            created_at=_now(),
        )
        return self.save(identity)

    def rotate(self) -> AgentIdentity:
        """Issue a new identity id, keeping name/capabilities/owner.

        The previous id is recorded in ``previous_ids`` so audit trails stay
        linkable across rotations.
        """
        current = self.load_or_create()
        rotated = replace(
            current,
            id=_new_identity_id(),
            rotated_at=_now(),
            previous_ids=[*current.previous_ids, current.id],
        )
        return self.save(rotated)

    def rename(self, name: str) -> AgentIdentity:
        """Change the human-readable name, keeping the stable id."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        current = self.load_or_create()
        return self.save(replace(current, name=name.strip()))

    def _quarantine(self) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self.identity_path.with_name(f"identity.json.corrupt-{stamp}")
        try:
            os.replace(self.identity_path, target)
        except OSError:
            # Best effort: if the rename fails, remove the unreadable file so
            # a fresh identity can be written in its place.
            with contextlib.suppress(OSError):
                self.identity_path.unlink()
            return self.identity_path
        return target


__all__ = ["AgentIdentity", "IdentityStore", "DEFAULT_IDENTITY_NAME"]
