"""Telemetry events for Chimera Pilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(frozen=True)
class PilotTelemetryEvent:
    task_id: str
    backend_id: str
    ok: bool
    started_at: float
    finished_at: float
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        return int((self.finished_at - self.started_at) * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "backend_id": self.backend_id,
            "ok": self.ok,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "metrics": dict(self.metrics),
        }


class InMemoryTelemetryStore:
    """Simple process-local telemetry store."""

    def __init__(self, max_events: int = 1000) -> None:
        self.max_events = max_events
        self._events: list[PilotTelemetryEvent] = []

    def record(self, event: PilotTelemetryEvent) -> None:
        self._events.append(event)
        if len(self._events) > self.max_events:
            del self._events[: len(self._events) - self.max_events]

    def events(self) -> list[PilotTelemetryEvent]:
        return list(self._events)

    def summary(self) -> dict[str, Any]:
        total = len(self._events)
        failures = sum(1 for event in self._events if not event.ok)
        avg_duration = 0 if total == 0 else sum(event.duration_ms for event in self._events) / total
        return {
            "total_events": total,
            "failures": failures,
            "successes": total - failures,
            "average_duration_ms": avg_duration,
            "last_event": self._events[-1].to_dict() if self._events else None,
        }


def now() -> float:
    return time()
