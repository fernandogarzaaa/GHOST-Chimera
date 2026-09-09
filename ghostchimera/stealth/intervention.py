"""Intervention model: explicit lifecycle + outcome feedback (spec sections 12, 23).

CREATED -> QUEUED -> PREPARING -> READY -> INJECTED/EXECUTED ->
CONSUMED -> OUTCOME. Outcomes feed back into workflow confidence.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class InterventionState(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    PREPARING = "preparing"
    READY = "ready"
    INJECTED = "injected"
    EXECUTED = "executed"
    CONSUMED = "consumed"
    OUTCOME = "outcome"
    EXPIRED = "expired"


class InterventionOutcome(StrEnum):
    PENDING = "pending"
    USEFUL = "useful"
    IGNORED = "ignored"
    REJECTED = "rejected"
    MODIFIED = "modified"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    EXPIRED = "expired"


_ALLOWED_TRANSITIONS: dict[InterventionState, set[InterventionState]] = {
    InterventionState.CREATED: {InterventionState.QUEUED, InterventionState.EXPIRED},
    InterventionState.QUEUED: {InterventionState.PREPARING, InterventionState.EXPIRED},
    InterventionState.PREPARING: {InterventionState.READY, InterventionState.EXPIRED},
    InterventionState.READY: {
        InterventionState.INJECTED,
        InterventionState.EXECUTED,
        InterventionState.EXPIRED,
    },
    InterventionState.INJECTED: {InterventionState.CONSUMED, InterventionState.EXPIRED},
    InterventionState.EXECUTED: {InterventionState.CONSUMED, InterventionState.EXPIRED},
    InterventionState.CONSUMED: {InterventionState.OUTCOME},
    InterventionState.OUTCOME: set(),
    InterventionState.EXPIRED: set(),
}


@dataclass
class Intervention:
    id: str = field(default_factory=lambda: f"int-{uuid.uuid4().hex[:12]}")
    trigger_event_id: str = ""
    workflow: str = ""
    confidence: float = 0.0
    state: InterventionState = InterventionState.CREATED
    context: dict[str, Any] = field(default_factory=dict)
    outcome: InterventionOutcome = InterventionOutcome.PENDING
    reason: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    history: list[dict[str, Any]] = field(default_factory=list)

    def transition(self, target: InterventionState, *, note: str = "") -> None:
        allowed = _ALLOWED_TRANSITIONS[self.state]
        if target not in allowed:
            raise ValueError(f"Illegal intervention transition {self.state} -> {target}")
        self.state = target
        self.updated_at = time.time()
        self.history.append({"state": str(target), "at": self.updated_at, "note": note})

    def record_outcome(self, outcome: InterventionOutcome, *, note: str = "") -> None:
        if self.state == InterventionState.CONSUMED:
            self.transition(InterventionState.OUTCOME, note=note)
        elif self.state != InterventionState.OUTCOME:
            raise ValueError(f"Cannot record outcome while intervention is {self.state}")
        self.outcome = outcome
        self.updated_at = time.time()

    def explain(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "why": self.reason,
            "trigger_event": self.trigger_event_id,
            "workflow": self.workflow,
            "confidence": self.confidence,
            "state": str(self.state),
            "outcome": str(self.outcome),
            "provenance": dict(self.provenance),
            "history": list(self.history),
        }


__all__ = ["Intervention", "InterventionOutcome", "InterventionState"]
