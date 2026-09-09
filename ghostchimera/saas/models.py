"""Tenant-aware SaaS data contracts.

These models are deliberately small and dependency-free so the local runtime can
import them without requiring a database driver or web framework.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from time import time
from typing import Any
from uuid import uuid4


class Role(StrEnum):
    """Organization role with increasing operational authority."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"
    OWNER = "owner"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


def now_ts() -> float:
    return float(time())


@dataclass(frozen=True)
class Organization:
    name: str
    org_id: str = field(default_factory=lambda: new_id("org"))
    created_at: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UserAccount:
    email: str
    display_name: str = ""
    user_id: str = field(default_factory=lambda: new_id("usr"))
    oidc_subject: str = ""
    created_at: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Membership:
    org_id: str
    user_id: str
    role: Role
    membership_id: str = field(default_factory=lambda: new_id("mem"))
    created_at: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["role"] = self.role.value
        return payload


@dataclass(frozen=True)
class Workspace:
    org_id: str
    name: str
    workspace_id: str = field(default_factory=lambda: new_id("wsp"))
    created_at: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GhostProfile:
    org_id: str
    workspace_id: str
    name: str
    path_profile: str
    approval_level: str = "supervised"
    ghost_id: str = field(default_factory=lambda: new_id("gst"))
    created_at: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TenantSecretRef:
    org_id: str
    workspace_id: str
    provider: str
    label: str
    configured: bool = True
    secret_id: str = field(default_factory=lambda: new_id("sec"))
    created_at: float = field(default_factory=now_ts)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "secret_id": self.secret_id,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
            "provider": self.provider,
            "label": self.label,
            "configured": self.configured,
            "secret_value": "[redacted]",
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SaasRun:
    org_id: str
    workspace_id: str
    actor_user_id: str
    objective: str
    status: str = "queued"
    run_id: str = field(default_factory=lambda: new_id("run"))
    approval_required: bool = True
    created_at: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SaasApproval:
    org_id: str
    workspace_id: str
    run_id: str
    requested_by: str
    risk_level: str
    status: str = "pending"
    reason: str = ""
    approval_id: str = field(default_factory=lambda: new_id("apv"))
    created_at: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerLease:
    org_id: str
    workspace_id: str
    run_id: str
    worker_id: str
    lease_until: float
    lease_id: str = field(default_factory=lambda: new_id("lease"))
    created_at: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditEvent:
    org_id: str
    actor_user_id: str
    action: str
    target_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: new_id("aud"))
    created_at: float = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = redact_mapping(self.metadata)
        return payload


SECRET_MARKERS = ("token", "secret", "password", "api_key", "apikey", "authorization", "credential")


def redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in mapping.items():
        lowered = key.lower()
        if any(marker in lowered for marker in SECRET_MARKERS):
            redacted[key] = "[redacted]"
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        else:
            redacted[key] = value
    return redacted
