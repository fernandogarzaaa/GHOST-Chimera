"""EVE Attention Engine (spec section 7).

Decides whether an incoming event warrants perception processing.
Goal: EVE receives attention-worthy state transitions, not an infinite video stream.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .eve_model import PerceptionLevel
from .events import Event


@dataclass
class AttentionSignal:
    """Result of attention evaluation."""

    should_attend: bool
    level: PerceptionLevel
    reason: str
    confidence: float
    urgency: float  # 0..1, how quickly we need to respond


@dataclass
class AttentionContext:
    """Current context for attention decisions."""

    last_event_time: float = 0.0
    last_event_type: str = ""
    last_application: str = ""
    last_url: str = ""
    active_task: str = ""
    event_count_1m: int = 0
    event_count_1h: int = 0
    recent_transitions: list[str] = field(default_factory=list)
    friction_score: float = 0.0
    last_perception_time: float = 0.0
    last_perception_level: PerceptionLevel = PerceptionLevel.EVENT


class AttentionEngine:
    """Determines if and how EVE should perceive an event."""

    # Event types that always warrant attention
    HIGH_VALUE_TYPES = frozenset(
        {
            "browser.navigation",
            "application.opened",
            "application.closed",
            "window.focused",
            "file.created",
            "file.modified",
            "dialog.appeared",
            "notification.received",
            "email.received",
            "calendar.event_starting",
            "github.issue_created",
            "github.pull_request_opened",
            "agent.session_started",
            "agent.prompt_submitted",
            "agent.tool_called",
            "user.correction",
            "user.approval",
            "user.rejection",
            "ghost.intervention_created",
        }
    )

    # Event types that are usually noise
    LOW_VALUE_TYPES = frozenset(
        {
            "mouse.move",
            "mouse.scroll",
            "keyboard.input",
            "clipboard.changed",
        }
    )

    def __init__(self):
        self.context = AttentionContext()
        self._event_timestamps: list[float] = []

    def evaluate(self, event: Event) -> AttentionSignal:
        """Decide if this event deserves EVE's attention and at what perception level."""
        now = time.time()
        app_changed = self._application_changed(event)
        url_changed = self._url_changed(event)
        self._update_context(event, now)

        # Always attend to high-value transitions
        if event.event_type in self.HIGH_VALUE_TYPES:
            return AttentionSignal(
                should_attend=True,
                level=self._determine_level(event),
                reason=f"High-value transition: {event.event_type}",
                confidence=0.9,
                urgency=0.8,
            )

        # Ignore low-value noise unless friction is high
        if event.event_type in self.LOW_VALUE_TYPES:
            if self.context.friction_score > 0.7:
                return AttentionSignal(
                    should_attend=True,
                    level=PerceptionLevel.EVENT,
                    reason="High friction, sampling noise",
                    confidence=0.4,
                    urgency=0.2,
                )
            return AttentionSignal(
                should_attend=False,
                level=PerceptionLevel.EVENT,
                reason="Low-value event, no friction",
                confidence=0.9,
                urgency=0.0,
            )

        if app_changed or url_changed:
            return AttentionSignal(
                should_attend=True,
                level=PerceptionLevel.STRUCTURED,
                reason=f"Context switch: app={app_changed}, url={url_changed}",
                confidence=0.85,
                urgency=0.7,
            )

        # Task-relevant events
        if self._task_relevant(event):
            return AttentionSignal(
                should_attend=True,
                level=PerceptionLevel.STRUCTURED,
                reason="Task-relevant event",
                confidence=0.7,
                urgency=0.5,
            )

        # Periodic sampling for long sessions
        if self._should_sample(now):
            return AttentionSignal(
                should_attend=True,
                level=PerceptionLevel.EVENT,
                reason="Periodic context sample",
                confidence=0.3,
                urgency=0.1,
            )

        return AttentionSignal(
            should_attend=False,
            level=PerceptionLevel.EVENT,
            reason="No significant state change",
            confidence=0.5,
            urgency=0.0,
        )

    def _update_context(self, event: Event, now: float) -> None:
        self._event_timestamps.append(now)
        # Keep last hour
        cutoff = now - 3600
        self._event_timestamps = [t for t in self._event_timestamps if t > cutoff]
        self.context.event_count_1h = len(self._event_timestamps)
        self.context.event_count_1m = len([t for t in self._event_timestamps if t > now - 60])

        self.context.last_event_time = now
        self.context.last_event_type = event.event_type

        # Track application from payload
        app = str(event.payload.get("application") or event.payload.get("app") or "")
        if app:
            self.context.last_application = app

        url = str(event.payload.get("url") or event.payload.get("active_url") or "")
        if url:
            self.context.last_url = url

        task = str(event.payload.get("task") or event.payload.get("active_task") or "")
        if task:
            self.context.active_task = task

        # Track recent transitions
        self.context.recent_transitions.append(event.event_type)
        if len(self.context.recent_transitions) > 50:
            self.context.recent_transitions = self.context.recent_transitions[-50:]

    def _application_changed(self, event: Event) -> bool:
        app = str(event.payload.get("application") or event.payload.get("app") or "")
        return bool(app and app != self.context.last_application)

    def _url_changed(self, event: Event) -> bool:
        url = str(event.payload.get("url") or event.payload.get("active_url") or "")
        return bool(url and url != self.context.last_url)

    def _task_relevant(self, event: Event) -> bool:
        if not self.context.active_task:
            return False
        task_keywords = self.context.active_task.lower().split()
        event_text = (event.event_type + " " + str(event.payload)).lower()
        return any(kw in event_text for kw in task_keywords if len(kw) > 3)

    def _should_sample(self, now: float) -> bool:
        # Sample every 30s if idle, every 5min if active
        idle_threshold = 30.0 if self.context.event_count_1m < 5 else 300.0
        return now - self.context.last_perception_time > idle_threshold

    def _determine_level(self, event: Event) -> PerceptionLevel:
        """Determine required perception level for an event."""
        # Browser navigation -> structured (DOM) first
        if event.event_type.startswith("browser."):
            return PerceptionLevel.BROWSER

        # Application events -> structured (A11y/UIA)
        if event.event_type.startswith("application.") or event.event_type.startswith("window."):
            return PerceptionLevel.ACCESSIBILITY

        # File events -> structured
        if event.event_type.startswith("file."):
            return PerceptionLevel.STRUCTURED

        # Dialog/notification -> try structured first
        if event.event_type in {"dialog.appeared", "notification.received"}:
            return PerceptionLevel.ACCESSIBILITY

        # Default to event-level
        return PerceptionLevel.EVENT

    def update_friction(self, friction_score: float) -> None:
        self.context.friction_score = max(0.0, min(1.0, friction_score))

    def update_perception(self, level: PerceptionLevel, now: float | None = None) -> None:
        self.context.last_perception_time = now or time.time()
        self.context.last_perception_level = level

    def get_context_snapshot(self) -> dict[str, Any]:
        return {
            "event_count_1m": self.context.event_count_1m,
            "event_count_1h": self.context.event_count_1h,
            "last_application": self.context.last_application,
            "last_url": self.context.last_url,
            "active_task": self.context.active_task,
            "friction_score": self.context.friction_score,
            "last_perception_level": self.context.last_perception_level.value,
        }


__all__ = ["AttentionEngine", "AttentionSignal", "AttentionContext"]
