"""Workflow maturity and dynamic autonomy governance."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .eve_model import WorkflowMaturity
from .stealth_policy import Decision


@dataclass(frozen=True)
class MaturityThresholds:
    candidate_proposals: int = 2
    validating_assists: int = 3
    confirmed_successes: int = 5
    autonomous_successes: int = 10
    degraded_failures: int = 3
    suspended_failures: int = 5
    minimum_useful_rate: float = 0.6
    autonomous_useful_rate: float = 0.8


@dataclass
class WorkflowMaturityState:
    name: str
    maturity: WorkflowMaturity = WorkflowMaturity.OBSERVED
    observations: int = 0
    proposals: int = 0
    assists: int = 0
    approvals: int = 0
    rejections: int = 0
    successes: int = 0
    failures: int = 0
    support: int = 0
    confidence: float = 0.0
    updated_at: float = field(default_factory=time.time)

    @property
    def attempts(self) -> int:
        return self.successes + self.failures

    @property
    def useful_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.successes / self.attempts

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow": self.name,
            "maturity": self.maturity.value,
            "observations": self.observations,
            "proposals": self.proposals,
            "assists": self.assists,
            "approvals": self.approvals,
            "rejections": self.rejections,
            "successes": self.successes,
            "failures": self.failures,
            "support": self.support,
            "confidence": self.confidence,
            "useful_rate": round(self.useful_rate, 3),
            "updated_at": self.updated_at,
        }


class WorkflowMaturityTracker:
    """Advance workflows through the maturity lifecycle from measurable evidence."""

    def __init__(self, thresholds: MaturityThresholds | None = None) -> None:
        self.thresholds = thresholds or MaturityThresholds()
        self._states: dict[str, WorkflowMaturityState] = {}

    def state(self, workflow: str) -> WorkflowMaturityState:
        current = self._states.get(workflow)
        if current is None:
            current = WorkflowMaturityState(name=workflow)
            self._states[workflow] = current
        return current

    def observe(self, workflow: str, *, support: int = 0, confidence: float = 0.0) -> WorkflowMaturity:
        current = self.state(workflow)
        current.observations += 1
        current.support = max(current.support, max(0, support))
        current.confidence = max(0.0, min(1.0, confidence))
        current.updated_at = time.time()
        self._promote_from_evidence(current)
        return current.maturity

    def note_proposal(self, workflow: str, *, support: int = 0, confidence: float = 0.0) -> WorkflowMaturity:
        current = self.state(workflow)
        current.proposals += 1
        current.support = max(current.support, max(0, support))
        current.confidence = max(0.0, min(1.0, confidence))
        current.updated_at = time.time()
        if current.maturity == WorkflowMaturity.OBSERVED and (
            current.proposals >= self.thresholds.candidate_proposals
            or current.support >= self.thresholds.candidate_proposals
        ):
            current.maturity = WorkflowMaturity.CANDIDATE
        self._promote_from_evidence(current)
        return current.maturity

    def note_assistance(self, workflow: str) -> WorkflowMaturity:
        current = self.state(workflow)
        current.assists += 1
        current.updated_at = time.time()
        if current.maturity == WorkflowMaturity.CANDIDATE and current.assists >= self.thresholds.validating_assists:
            current.maturity = WorkflowMaturity.VALIDATING
        elif current.maturity == WorkflowMaturity.CONFIRMED or (
            current.maturity == WorkflowMaturity.APPROVED and current.assists >= self.thresholds.validating_assists
        ):
            current.maturity = WorkflowMaturity.ASSISTED
        return current.maturity

    def note_approval(self, workflow: str) -> WorkflowMaturity:
        current = self.state(workflow)
        current.approvals += 1
        current.updated_at = time.time()
        if current.maturity in {
            WorkflowMaturity.VALIDATING,
            WorkflowMaturity.CONFIRMED,
            WorkflowMaturity.ASSISTED,
            WorkflowMaturity.DEGRADED,
        }:
            current.maturity = WorkflowMaturity.APPROVED
        return current.maturity

    def note_rejection(self, workflow: str) -> WorkflowMaturity:
        current = self.state(workflow)
        current.rejections += 1
        current.updated_at = time.time()
        current.maturity = WorkflowMaturity.SUSPENDED
        return current.maturity

    def note_success(self, workflow: str) -> WorkflowMaturity:
        current = self.state(workflow)
        current.successes += 1
        current.updated_at = time.time()
        self._promote_from_evidence(current)
        return current.maturity

    def note_failure(self, workflow: str) -> WorkflowMaturity:
        current = self.state(workflow)
        current.failures += 1
        current.updated_at = time.time()
        if current.failures >= self.thresholds.suspended_failures:
            current.maturity = WorkflowMaturity.SUSPENDED
        elif current.failures >= self.thresholds.degraded_failures:
            current.maturity = WorkflowMaturity.DEGRADED
        return current.maturity

    def reinstate(self, workflow: str) -> WorkflowMaturity:
        current = self.state(workflow)
        current.updated_at = time.time()
        if current.maturity in {WorkflowMaturity.SUSPENDED, WorkflowMaturity.DEGRADED}:
            current.maturity = WorkflowMaturity.VALIDATING
        return current.maturity

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {name: current.to_dict() for name, current in self._states.items()}

    def _promote_from_evidence(self, current: WorkflowMaturityState) -> None:
        if current.maturity in {WorkflowMaturity.SUSPENDED, WorkflowMaturity.DEGRADED}:
            return
        if (
            current.maturity
            in {
                WorkflowMaturity.OBSERVED,
                WorkflowMaturity.CANDIDATE,
                WorkflowMaturity.VALIDATING,
            }
            and current.successes >= self.thresholds.confirmed_successes
            and current.useful_rate >= self.thresholds.minimum_useful_rate
        ):
            current.maturity = WorkflowMaturity.CONFIRMED
        if (
            current.maturity
            in {
                WorkflowMaturity.CONFIRMED,
                WorkflowMaturity.ASSISTED,
                WorkflowMaturity.APPROVED,
            }
            and current.successes >= self.thresholds.autonomous_successes
            and current.useful_rate >= self.thresholds.autonomous_useful_rate
        ):
            current.maturity = WorkflowMaturity.AUTONOMOUS


@dataclass(frozen=True)
class GovernedDecision:
    decision: Decision
    workflow: str
    maturity: WorkflowMaturity
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "maturity": self.maturity.value,
            "governed_decision": self.decision.value,
            "reason": self.reason,
        }


class WorkflowAutonomyGovernor:
    """Constrain loop decisions by learned workflow maturity before global policy applies."""

    def __init__(self, tracker: WorkflowMaturityTracker | None = None) -> None:
        self.tracker = tracker or WorkflowMaturityTracker()

    def govern(self, decision: Decision, workflow: str) -> GovernedDecision:
        maturity = self.tracker.state(workflow).maturity
        if maturity == WorkflowMaturity.SUSPENDED:
            return GovernedDecision(Decision.NONE, workflow, maturity, "suspended workflow is silent")

        if decision in (Decision.NONE, Decision.STORE):
            return GovernedDecision(decision, workflow, maturity, "observation remains enabled")

        if maturity in {WorkflowMaturity.APPROVED, WorkflowMaturity.AUTONOMOUS}:
            return GovernedDecision(decision, workflow, maturity, "approved workflow retains policy decision")

        if maturity == WorkflowMaturity.DEGRADED:
            return GovernedDecision(Decision.STORE, workflow, maturity, "degraded workflow is observation-only")

        if maturity in {WorkflowMaturity.OBSERVED, WorkflowMaturity.CANDIDATE}:
            if decision in (Decision.ACT, Decision.INJECT, Decision.ASK):
                return GovernedDecision(
                    Decision.PREPARE, workflow, maturity, "immature workflow is limited to preparation"
                )
            return GovernedDecision(decision, workflow, maturity, "immature workflow retains low-risk decision")

        if decision == Decision.ACT:
            return GovernedDecision(Decision.INJECT, workflow, maturity, "unapproved workflow cannot act autonomously")
        if decision == Decision.ASK:
            return GovernedDecision(
                Decision.STORE, workflow, maturity, "unapproved workflow cannot request autonomous action"
            )
        return GovernedDecision(decision, workflow, maturity, "validating workflow retains assisted decision")


__all__ = [
    "GovernedDecision",
    "MaturityThresholds",
    "WorkflowAutonomyGovernor",
    "WorkflowMaturityState",
    "WorkflowMaturityTracker",
]
