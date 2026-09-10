"""Policy + Stealth Evaluator (spec sections 11, 20-22).

Default is silence. The evaluator is conservative and deterministic:
no LLM calls. Scores relevance/confidence/timing/benefit/cost/risk/
privacy/autonomy/frequency into NONE | STORE | PREPARE | INJECT | ACT.
Autonomy levels gate side effects: L0 observe, L1 prepare, L2 inject,
L3 act (explicit authorization required).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class AutonomyLevel(IntEnum):
    OBSERVE = 0
    PREPARE = 1
    INJECT = 2
    ACT = 3


class Decision(StrEnum):
    NONE = "none"
    STORE = "store"
    PREPARE = "prepare"
    INJECT = "inject"
    ACT = "act"
    ASK = "ask"


@dataclass(frozen=True)
class EvaluationSignals:
    relevance: float = 0.0
    confidence: float = 0.0
    user_benefit: float = 0.0
    cost: float = 0.0  # 0 cheap .. 1 expensive
    risk: float = 0.0  # 0 safe .. 1 dangerous
    external_side_effect: bool = False
    privacy_ok: bool = True
    intervention_count_1h: int = 0


@dataclass
class GhostPolicy:
    """Central Ghost configuration (spec section 36)."""

    enabled: bool = True
    autonomy: AutonomyLevel = AutonomyLevel.PREPARE
    minimum_confidence: float = 0.80
    max_interventions_per_hour: int = 5
    local_first: bool = True
    allowed_hosts: set[str] = field(default_factory=set)
    blocked_privacy_classes: set[str] = field(default_factory=lambda: {"secret"})

    @classmethod
    def conservative_default(cls) -> GhostPolicy:
        return cls()

    @classmethod
    def strict_observe(cls) -> GhostPolicy:
        return cls(autonomy=AutonomyLevel.OBSERVE, minimum_confidence=0.95, max_interventions_per_hour=10000)

    def allows(self, decision: Decision) -> bool:
        if not self.enabled:
            return decision == Decision.NONE
        if decision == Decision.NONE or decision == Decision.STORE:
            return True
        if decision == Decision.PREPARE:
            return self.autonomy >= AutonomyLevel.PREPARE
        if decision == Decision.INJECT:
            return self.autonomy >= AutonomyLevel.INJECT
        if decision in (Decision.ACT, Decision.ASK):
            return self.autonomy >= AutonomyLevel.ACT
        return False


class StealthEvaluator:
    """Deterministic gate between prediction and intervention."""

    def __init__(self, policy: GhostPolicy | None = None) -> None:
        self.policy = policy or GhostPolicy.conservative_default()

    def evaluate(self, signals: EvaluationSignals) -> tuple[Decision, dict[str, Any]]:
        trace: dict[str, Any] = {
            "relevance": signals.relevance,
            "confidence": signals.confidence,
            "risk": signals.risk,
            "privacy_ok": signals.privacy_ok,
        }
        if not self.policy.enabled:
            return Decision.NONE, {**trace, "reason": "ghost disabled"}
        if not signals.privacy_ok:
            return Decision.NONE, {**trace, "reason": "privacy denied"}
        if signals.intervention_count_1h >= self.policy.max_interventions_per_hour:
            return Decision.NONE, {**trace, "reason": "frequency cap"}
        if signals.confidence < 0.31:
            return Decision.NONE, {**trace, "reason": "confidence too low"}

        if signals.external_side_effect and signals.risk >= 0.4:
            decision = Decision.ASK if signals.confidence >= 0.7 else Decision.STORE
            if not self.policy.allows(decision):
                return Decision.STORE, {**trace, "reason": "autonomy gate"}
            return decision, {**trace, "reason": "external side effect needs approval"}

        score = (
            0.35 * signals.relevance
            + 0.35 * signals.confidence
            + 0.20 * signals.user_benefit
            - 0.25 * signals.risk
            - 0.15 * signals.cost
        )
        trace["score"] = round(score, 3)
        if signals.confidence >= self.policy.minimum_confidence and score >= 0.55:
            candidate = Decision.PREPARE
            if score >= 0.75 and signals.confidence >= 0.9:
                candidate = Decision.INJECT
        elif score >= 0.35:
            candidate = Decision.STORE
        else:
            return Decision.NONE, {**trace, "reason": "score below threshold"}

        while candidate != Decision.NONE and not self.policy.allows(candidate):
            candidate = _downgrade(candidate)
        return candidate, {**trace, "reason": f"downgraded to {candidate} by autonomy"}


def _downgrade(decision: Decision) -> Decision:
    order = [Decision.ACT, Decision.INJECT, Decision.PREPARE, Decision.STORE, Decision.NONE]
    try:
        return order[order.index(decision) + 1]
    except (ValueError, IndexError):
        return Decision.NONE


__all__ = ["AutonomyLevel", "Decision", "EvaluationSignals", "GhostPolicy", "StealthEvaluator"]
