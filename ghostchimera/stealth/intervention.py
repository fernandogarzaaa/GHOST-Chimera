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

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Intervention:
        """Rebuild an intervention from a ``StealthStore.load_interventions`` row."""
        try:
            state = InterventionState(str(row.get("state") or "created"))
        except ValueError:
            state = InterventionState.CREATED
        try:
            outcome = InterventionOutcome(str(row.get("outcome") or "pending"))
        except ValueError:
            outcome = InterventionOutcome.PENDING
        provenance = row.get("provenance")
        updated = float(row.get("updated_at") or time.time())
        return cls(
            id=str(row["id"]),
            trigger_event_id=str(row.get("trigger_event_id") or ""),
            workflow=str(row.get("workflow") or ""),
            confidence=float(row.get("confidence") or 0.0),
            state=state,
            outcome=outcome,
            reason=str(row.get("reason") or ""),
            provenance=dict(provenance) if isinstance(provenance, dict) else {},
            created_at=float(row.get("created_at") or updated),
            updated_at=updated,
            history=[{"state": str(state), "at": updated, "note": "restored from journal"}],
        )

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
