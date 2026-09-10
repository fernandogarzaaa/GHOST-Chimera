"""EVE Agent Experience Model (spec sections 4, 5, 6, 7, 8, 16, 24).

First-class primitives: Experience, Intent, Prediction, Observation, Trajectory, Outcome, Intervention.
Supports uncertainty at every level. No premature collapse.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PerceptionLevel(StrEnum):
    """Hierarchical perception (spec section 6)."""

    EVENT = "event"  # Level 0: Cheapest, raw normalized events
    STRUCTURED = "structured"  # Level 1: DOM, A11y, UIA, MCP, APIs
    BROWSER = "browser"  # Level 1b: Browser DevTools, CDP
    ACCESSIBILITY = "accessibility"  # Level 1c: Accessibility tree
    VISION = "vision"  # Level 2: Screenshots, OCR, vision models (last resort)


class InterventionMode(StrEnum):
    """Graduated intervention modes (spec section 12)."""

    WITNESS = "witness"  # Mode 0: Observe and learn only
    COMPANION = "companion"  # Mode 1: Contextual assistance
    PREPARE = "prepare"  # Mode 2: Prepare next action, wait for approval
    COPILOT = "copilot"  # Mode 3: Ask before consequential actions
    GHOST = "ghost"  # Mode 4: Autonomous within policy


class WorkflowMaturity(StrEnum):
    """Workflow lifecycle (spec section 19)."""

    OBSERVED = "observed"
    CANDIDATE = "candidate"
    VALIDATING = "validating"
    CONFIRMED = "confirmed"
    ASSISTED = "assisted"
    APPROVED = "approved"
    AUTONOMOUS = "autonomous"
    DEGRADED = "degraded"
    SUSPENDED = "suspended"


class ExperienceEventType(StrEnum):
    """Internal experience stream events (spec section 16)."""

    ENVIRONMENT_CHANGED = "environment_changed"
    TASK_STARTED = "task_started"
    TASK_PROGRESSED = "task_progressed"
    TASK_BLOCKED = "task_blocked"
    TASK_COMPLETED = "task_completed"
    FRICTION_DETECTED = "friction_detected"
    INTENT_CHANGED = "intent_changed"
    PREDICTION_GENERATED = "prediction_generated"
    INTERVENTION_PROPOSED = "intervention_proposed"
    INTERVENTION_EXECUTED = "intervention_executed"
    OUTCOME_OBSERVED = "outcome_observed"
    EXPERIENCE_VALIDATED = "experience_validated"


@dataclass
class EnvironmentState:
    """What EVE currently believes the user is operating in (spec section 5)."""

    active_application: str | None = None
    active_window: str | None = None
    active_url: str | None = None
    visible_elements: list[dict[str, Any]] = field(default_factory=list)
    accessibility_tree: dict[str, Any] | None = None
    browser_context: dict[str, Any] | None = None
    clipboard_state: dict[str, Any] | None = None
    input_state: dict[str, Any] | None = None
    screen_state: dict[str, Any] | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class IntentHypothesis:
    """Probabilistic intent with alternatives (spec section 10)."""

    goal: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    alternatives: list[IntentHypothesis] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def primary(self) -> bool:
        return self.confidence >= 0.5 and (
            not self.alternatives or self.confidence > max(a.confidence for a in self.alternatives)
        )


@dataclass
class FrictionState:
    """Measurable behavioral friction (spec section 9)."""

    score: float = 0.0
    hesitation: float = 0.0
    repetition: float = 0.0
    retry_rate: float = 0.0
    reversal_rate: float = 0.0
    error_frequency: float = 0.0
    navigation_complexity: float = 0.0
    waiting_time: float = 0.0
    uncertainty: float = 0.0
    task_deviation: float = 0.0
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "hesitation": self.hesitation,
            "repetition": self.repetition,
            "retry_rate": self.retry_rate,
            "reversal_rate": self.reversal_rate,
            "error_frequency": self.error_frequency,
            "navigation_complexity": self.navigation_complexity,
            "waiting_time": self.waiting_time,
            "uncertainty": self.uncertainty,
            "task_deviation": self.task_deviation,
            "signals": self.signals,
        }


@dataclass
class Prediction:
    """What EVE predicts next (spec section 11)."""

    predicted_action: str | None = None
    predicted_state: dict[str, Any] | None = None
    probability: float = 0.0
    expected_friction: float = 0.0
    opportunity: dict[str, Any] | None = None
    basis: str = ""


@dataclass
class Intervention:
    """Graduated intervention with provenance (spec sections 12, 34)."""

    id: str = field(default_factory=lambda: f"int-{uuid.uuid4().hex[:12]}")
    mode: InterventionMode = InterventionMode.WITNESS
    reason: str = ""
    expected_benefit: str = ""
    evidence: list[str] = field(default_factory=list)
    predicted_outcome: Prediction | None = None
    confidence: float = 0.0
    requires_approval: bool = False
    expires_at: float | None = None
    created_at: float = field(default_factory=time.time)
    trigger_event_id: str = ""


@dataclass
class OutcomeState:
    """Result of an intervention (spec section 20)."""

    task_completion: bool = False
    time_to_completion: float | None = None
    steps_avoided: int = 0
    errors_avoided: int = 0
    retries_avoided: int = 0
    friction_reduction: float = 0.0
    user_interruption: bool = False
    user_override: bool = False
    user_rejection: bool = False
    prediction_accuracy: float = 0.0
    intervention_usefulness: float = 0.0
    experience_quality: float = 0.0


@dataclass
class TrajectoryState:
    """Sequence understanding (spec section 8)."""

    actions: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    retries: int = 0
    reversals: int = 0
    repeated_actions: list[dict[str, Any]] = field(default_factory=list)
    navigation_depth: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    interruptions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Evidence:
    """Provenance for EVE conclusions (spec section 23)."""

    source_event_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.0


@dataclass
class ExperienceState:
    """Complete experiential state (spec section 4)."""

    experience_id: str = field(default_factory=lambda: f"exp-{uuid.uuid4().hex[:12]}")
    session_id: str = ""
    timestamp_start: float = field(default_factory=time.time)
    timestamp_last_updated: float = field(default_factory=time.time)
    environment: EnvironmentState = field(default_factory=EnvironmentState)
    task: str = ""
    intent: IntentHypothesis | None = None
    perception: dict[str, Any] = field(default_factory=dict)
    trajectory: TrajectoryState = field(default_factory=TrajectoryState)
    friction: FrictionState = field(default_factory=FrictionState)
    prediction: Prediction | None = None
    intervention: Intervention | None = None
    outcome: OutcomeState | None = None
    confidence: float = 0.0
    provenance: Evidence = field(default_factory=Evidence)
    privacy: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperienceEvent:
    """Internal experience stream event (spec section 16)."""

    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:12]}")
    event_type: ExperienceEventType = ExperienceEventType.ENVIRONMENT_CHANGED
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""
    experience_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "experience_id": self.experience_id,
            "payload": self.payload,
            "provenance": self.provenance,
        }


class ExperienceStream:
    """Append-only experience event stream per session (spec section 16)."""

    def __init__(self, session_id: str, experience_id: str, max_events: int = 500):
        self.session_id = session_id
        self.experience_id = experience_id
        self.max_events = max_events
        self._events: list[ExperienceEvent] = []

    def append(self, event: ExperienceEvent) -> None:
        self._events.append(event)
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]

    def recent(self, limit: int = 50) -> list[ExperienceEvent]:
        return self._events[-limit:]

    def by_type(self, event_type: ExperienceEventType, limit: int = 20) -> list[ExperienceEvent]:
        return [e for e in reversed(self._events) if e.event_type == event_type][:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "experience_id": self.experience_id,
            "events": [e.to_dict() for e in self._events],
        }


__all__ = [
    "PerceptionLevel",
    "InterventionMode",
    "WorkflowMaturity",
    "ExperienceEventType",
    "EnvironmentState",
    "IntentHypothesis",
    "FrictionState",
    "Prediction",
    "Intervention",
    "OutcomeState",
    "TrajectoryState",
    "Evidence",
    "ExperienceState",
    "ExperienceEvent",
    "ExperienceStream",
]
