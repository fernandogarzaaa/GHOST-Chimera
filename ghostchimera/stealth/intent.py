"""EVE Intent Engine + Friction Detector (spec sections 9, 10).

Intent: continuous probabilistic hypotheses about user goals.
Friction: measurable behavioral signals (not psychological diagnoses).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from .eve_model import FrictionState, IntentHypothesis
from .events import Event
from .experience import ExperienceGraph
from .workflow_learner import WorkflowHypothesis, WorkflowLearner


@dataclass
class IntentEngine:
    """Maintains probabilistic intent hypotheses (spec section 10)."""

    min_confidence: float = 0.3
    max_alternatives: int = 3
    decay_rate: float = 0.99
    _hypotheses: list[IntentHypothesis] = field(default_factory=list)
    _last_update: float = field(default_factory=time.time)
    _recent_event_types: deque[str] = field(default_factory=lambda: deque(maxlen=20))

    def update(
        self, event: Event, experience_graph: ExperienceGraph, workflow_learner: WorkflowLearner
    ) -> list[IntentHypothesis]:
        """Update intent hypotheses based on new event."""
        now = time.time()
        self._decay(now)
        self._recent_event_types.append(event.event_type)

        recent_events = self._get_recent_event_types(experience_graph, limit=20)
        workflow_hyp = workflow_learner.match(recent_events)

        # Generate new hypotheses from event
        new_hypotheses = self._generate_hypotheses(event, workflow_hyp)

        # Merge with existing, keeping top alternatives
        self._merge_hypotheses(new_hypotheses)

        # Prune low confidence
        self._hypotheses = [h for h in self._hypotheses if h.confidence >= self.min_confidence]
        self._hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        self._hypotheses = self._hypotheses[: self.max_alternatives + 1]  # primary + alternatives

        self._last_update = now
        return self._hypotheses

    def _decay(self, now: float) -> None:
        dt = now - self._last_update
        if dt <= 0:
            return
        for h in self._hypotheses:
            h.confidence *= self.decay_rate**dt

    def _get_recent_event_types(self, graph: ExperienceGraph, limit: int = 20) -> list[str]:
        return list(self._recent_event_types)[-limit:]

    def _generate_hypotheses(self, event: Event, workflow_hyp: WorkflowHypothesis | None) -> list[IntentHypothesis]:
        hypotheses = []

        # From workflow hypothesis
        if workflow_hyp and workflow_hyp.confidence > 0.5:
            hypotheses.append(
                IntentHypothesis(
                    goal=f"Continue {workflow_hyp.name}",
                    confidence=workflow_hyp.confidence * 0.8,
                    evidence=[f"workflow:{workflow_hyp.name}", f"support:{workflow_hyp.support}"],
                )
            )

        # From event type patterns
        event_intents = self._event_type_to_intent(event.event_type)
        for intent, conf in event_intents:
            hypotheses.append(
                IntentHypothesis(
                    goal=intent,
                    confidence=conf,
                    evidence=[f"event:{event.event_type}"],
                )
            )

        # From payload keywords
        payload_intents = self._payload_to_intent(event.payload)
        for intent, conf in payload_intents:
            hypotheses.append(
                IntentHypothesis(
                    goal=intent,
                    confidence=conf,
                    evidence=[f"payload:{k}" for k in event.payload],
                )
            )

        return hypotheses

    def _event_type_to_intent(self, event_type: str) -> list[tuple[str, float]]:
        """Map event types to likely intents."""
        mapping = {
            "browser.navigation": [("Browse web", 0.7), ("Research", 0.5)],
            "email.received": [("Check email", 0.8), ("Respond to messages", 0.6)],
            "email.sent": [("Send email", 0.9)],
            "file.created": [("Create document", 0.7), ("Start task", 0.5)],
            "file.modified": [("Edit document", 0.8), ("Continue work", 0.6)],
            "github.issue_created": [("Report issue", 0.9), ("Track task", 0.7)],
            "github.pull_request_opened": [("Submit code review", 0.9)],
            "calendar.event_starting": [("Attend meeting", 0.9), ("Prepare for meeting", 0.7)],
            "application.opened": [("Start application", 0.6)],
            "window.focused": [("Switch context", 0.5)],
            "agent.session_started": [("Use AI assistant", 0.8)],
            "agent.tool_called": [("Execute task via AI", 0.7)],
        }
        return mapping.get(event_type, [])

    def _payload_to_intent(self, payload: dict[str, Any]) -> list[tuple[str, float]]:
        """Extract intent hints from payload."""
        intents = []
        text = str(payload).lower()

        keywords = {
            "invoice": ("Find invoice", 0.7),
            "deploy": ("Deploy application", 0.8),
            "bug": ("Fix bug", 0.7),
            "review": ("Code review", 0.7),
            "meeting": ("Prepare meeting", 0.6),
            "search": ("Search for information", 0.5),
            "error": ("Debug error", 0.7),
            "test": ("Run tests", 0.6),
            "commit": ("Commit changes", 0.7),
            "merge": ("Merge branch", 0.7),
        }

        for kw, (intent, conf) in keywords.items():
            if kw in text:
                intents.append((intent, conf))

        return intents

    def _merge_hypotheses(self, new_hypotheses: list[IntentHypothesis]) -> None:
        for new_h in new_hypotheses:
            # Check if similar to existing
            merged = False
            for existing in self._hypotheses:
                if self._similar_intent(new_h.goal, existing.goal):
                    # Boost confidence
                    existing.confidence = min(0.99, existing.confidence + new_h.confidence * 0.3)
                    existing.evidence.extend(new_h.evidence)
                    merged = True
                    break
            if not merged:
                self._hypotheses.append(new_h)

    def _similar_intent(self, a: str, b: str) -> bool:
        a_words = set(a.lower().split())
        b_words = set(b.lower().split())
        if not a_words or not b_words:
            return False
        overlap = len(a_words & b_words)
        return overlap / max(len(a_words), len(b_words)) > 0.5

    def get_primary(self) -> IntentHypothesis | None:
        return self._hypotheses[0] if self._hypotheses else None

    def get_alternatives(self) -> list[IntentHypothesis]:
        return self._hypotheses[1:] if len(self._hypotheses) > 1 else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self._hypotheses[0].__dict__ if self._hypotheses else None,
            "alternatives": [h.__dict__ for h in self._hypotheses[1:]],
        }


class FrictionDetector:
    """Detects measurable behavioral friction (spec section 9)."""

    def __init__(self):
        self._event_history: list[Event] = []
        self._action_counts: dict[str, int] = defaultdict(int)
        self._error_count = 0
        self._reversal_count = 0
        self._navigation_count = 0
        self._last_event_time: float = 0
        self._session_start: float = time.time()
        self._navigation_stack: list[str] = []

    def observe(self, event: Event, predicted_actions: list[str] | None = None) -> FrictionState:
        """Update friction state with new event."""
        now = time.time()
        self._event_history.append(event)
        if len(self._event_history) > 200:
            self._event_history = self._event_history[-200:]

        self._action_counts[event.event_type] += 1
        if "error" in str(event.payload).lower() or event.event_type.endswith((".failed", ".error")):
            self._error_count += 1
        event_type = event.event_type.lower()
        if "navigat" in event_type or "back" in event_type:
            self._navigation_count += 1
            self._navigation_stack.append(event.event_type)
            if len(self._navigation_stack) > 50:
                self._navigation_stack = self._navigation_stack[-50:]
            if "back" in event_type or "reverse" in event_type:
                self._reversal_count += 1
        self._compute_friction(now, predicted_actions)
        self._last_event_time = now
        return self.get_state()

    def _compute_friction(self, now: float, predicted_actions: list[str] | None = None) -> None:
        state = FrictionState()

        total_actions = sum(self._action_counts.values())
        if total_actions > 0:
            max_repeats = max(self._action_counts.values())
            state.repetition = min(1.0, max_repeats / max(1, total_actions * 0.3))

        state.retry_rate = self._calculate_retry_rate()

        state.reversal_rate = self._calculate_reversal_rate()

        state.error_frequency = min(1.0, self._error_count / max(1, total_actions))

        state.navigation_complexity = min(1.0, len(self._navigation_stack) / 10)

        if self._last_event_time > 0:
            idle = now - self._last_event_time
            state.waiting_time = min(1.0, idle / 30.0)

        state.task_deviation = self._calculate_task_deviation(predicted_actions)

        state.hesitation = min(1.0, state.repetition * 0.5 + state.waiting_time * 0.5)

        state.score = (
            0.25 * state.repetition
            + 0.20 * state.retry_rate
            + 0.15 * state.reversal_rate
            + 0.15 * state.error_frequency
            + 0.10 * state.navigation_complexity
            + 0.10 * state.waiting_time
            + 0.05 * state.task_deviation
        )

        if state.repetition > 0.5:
            state.signals.append("Repeated actions detected")
        if state.retry_rate > 0.3:
            state.signals.append("High retry rate")
        if state.reversal_rate > 0.3:
            state.signals.append("Navigation reversals")
        if state.error_frequency > 0.2:
            state.signals.append("Frequent errors")
        if state.waiting_time > 0.5:
            state.signals.append("Long pauses before actions")
        if state.task_deviation > 0.3:
            state.signals.append("Actions deviating from predicted workflow")

        self._last_state = state

    def _calculate_retry_rate(self) -> float:
        if len(self._event_history) < 2:
            return 0.0
        retries = 0
        transitions = 0
        for i in range(1, len(self._event_history)):
            prev = self._event_history[i - 1]
            curr = self._event_history[i]
            if prev.event_type == curr.event_type:
                # Check if previous was an error
                if "error" in str(prev.payload).lower() or prev.event_type.endswith(".failed"):
                    retries += 1
                transitions += 1
        return retries / max(1, transitions)

    def _calculate_reversal_rate(self) -> float:
        return self._reversal_count / max(1, self._navigation_count)

    def _calculate_task_deviation(self, predicted_actions: list[str] | None = None) -> float:
        if not predicted_actions or not self._event_history:
            return 0.0
        expected = {
            action.split("event:", 1)[1] if action.startswith("event:") else action for action in predicted_actions
        }
        expected.discard("none")
        if not expected:
            return 0.0
        current = self._event_history[-1].event_type
        return 0.0 if current in expected else 0.5

    def get_state(self) -> FrictionState:
        return getattr(self, "_last_state", FrictionState())

    def record_error(self) -> None:
        self._error_count += 1

    def record_reversal(self) -> None:
        self._navigation_count += 1
        self._reversal_count += 1

    def to_dict(self) -> dict[str, Any]:
        state = self.get_state()
        return {
            "score": state.score,
            "hesitation": state.hesitation,
            "repetition": state.repetition,
            "retry_rate": state.retry_rate,
            "reversal_rate": state.reversal_rate,
            "error_frequency": state.error_frequency,
            "navigation_complexity": state.navigation_complexity,
            "waiting_time": state.waiting_time,
            "uncertainty": state.uncertainty,
            "task_deviation": state.task_deviation,
            "signals": state.signals,
        }


__all__ = ["IntentEngine", "FrictionDetector"]
