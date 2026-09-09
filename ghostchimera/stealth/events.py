"""Normalized Ghost event schema.

Every external signal (email, calendar, github, files, agent sessions,
user feedback, ghost interventions) becomes an ``Event`` before any
consumer sees it. Events are idempotent (dedup by ``event_id``),
traceable (correlation/session ids + provenance), and replayable.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def new_event_id(prefix: str = "evt") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# Well-known event types (spec section 5). Producers may use custom
# ``domain.action`` types; consumers match on prefix or exact string.
WELL_KNOWN_EVENT_TYPES = frozenset(
    {
        "email.received",
        "email.sent",
        "calendar.event_created",
        "calendar.event_updated",
        "calendar.event_starting",
        "github.issue_created",
        "github.issue_updated",
        "github.pull_request_opened",
        "github.pull_request_merged",
        "github.commit",
        "file.created",
        "file.modified",
        "note.created",
        "note.modified",
        "agent.session_started",
        "agent.prompt_submitted",
        "agent.tool_called",
        "agent.response_completed",
        "agent.session_ended",
        "user.correction",
        "user.approval",
        "user.rejection",
        "ghost.intervention_created",
        "ghost.intervention_consumed",
        "ghost.intervention_ignored",
        "ghost.intervention_success",
        "ghost.intervention_failure",
        "memory.promoted",
        "memory.expired",
        "context.assembled",
        "workspace.updated",
    }
)


@dataclass(frozen=True)
class Event:
    """A normalized, immutable Ghost event."""

    event_id: str
    event_type: str
    timestamp: float
    source: str
    actor: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    session_id: str = ""
    privacy_classification: str = "internal"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "source": self.source,
            "actor": self.actor,
            "payload": dict(self.payload),
            "provenance": dict(self.provenance),
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "privacy_classification": self.privacy_classification,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            timestamp=float(data.get("timestamp", 0.0)),
            source=str(data.get("source", "unknown")),
            actor=str(data.get("actor", "")),
            payload=dict(data.get("payload") or {}),
            provenance=dict(data.get("provenance") or {}),
            correlation_id=str(data.get("correlation_id", "")),
            session_id=str(data.get("session_id", "")),
            privacy_classification=str(data.get("privacy_classification", "internal")),
            confidence=float(data.get("confidence", 1.0)),
        )


def new_event(
    event_type: str,
    *,
    source: str,
    actor: str = "",
    payload: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    correlation_id: str = "",
    session_id: str = "",
    privacy_classification: str = "internal",
    confidence: float = 1.0,
    event_id: str | None = None,
    timestamp: float | None = None,
) -> Event:
    """Build a normalized event with sane defaults."""
    return Event(
        event_id=event_id or new_event_id(),
        event_type=event_type.strip().lower(),
        timestamp=timestamp if timestamp is not None else time.time(),
        source=source,
        actor=actor,
        payload=dict(payload or {}),
        provenance=dict(provenance or {}),
        correlation_id=correlation_id,
        session_id=session_id,
        privacy_classification=privacy_classification,
        confidence=max(0.0, min(1.0, confidence)),
    )


def normalize_event(event: Event) -> Event:
    """Cheap deterministic filter stage: strip/normalize + clamp confidence."""
    event_type = event.event_type.strip().lower()
    if event_type == event.event_type and 0.0 <= event.confidence <= 1.0:
        return event
    return Event(
        event_id=event.event_id,
        event_type=event_type,
        timestamp=event.timestamp,
        source=event.source,
        actor=event.actor,
        payload=event.payload,
        provenance=event.provenance,
        correlation_id=event.correlation_id,
        session_id=event.session_id,
        privacy_classification=event.privacy_classification,
        confidence=max(0.0, min(1.0, event.confidence)),
    )
