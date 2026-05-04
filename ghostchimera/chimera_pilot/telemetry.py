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

    @staticmethod
    def _mask_sensitive(value: str) -> str:
        """Mask potential secrets in diagnostic output."""
        if not value:
            return value
        sensitive_patterns = ("Bearer sk-", "Bearer pk-", "Bearer ak")
        for pat in sensitive_patterns:
            if pat in value[:20]:
                return pat + "*MASKED*"
        return value

    def to_dict(self) -> dict[str, Any]:
        sanitized_metrics = {}
        for k, v in self.metrics.items():
            sv = self._mask_sensitive(str(v)) if isinstance(v, str) else v
            sanitized_metrics[k] = sv
        return {
            "task_id": self.task_id,
            "backend_id": self.backend_id,
            "ok": self.ok,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "metrics": sanitized_metrics,
        }

    def sanitize(self) -> "PilotTelemetryEvent":
        """Return a copy with all sensitive data stripped."""
        return PilotTelemetryEvent(
            task_id=self.task_id,
            backend_id=self.backend_id,
            ok=self.ok,
            started_at=self.started_at,
            finished_at=self.finished_at,
            error=None,
            metrics={k: ("MASKED" if isinstance(v, str) else v) for k, v in self.metrics.items()},
        )


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

    def percentile(self, field: str = "duration_ms", p: float = 95) -> float:
        """Compute the p-th percentile of a numeric field across events."""
        values = sorted(getattr(event, field, event.to_dict().get(field, 0)) for event in self._events)
        if not values:
            return 0.0
        k = (len(values) - 1) * (p / 100.0)
        f = int(k)
        c = f + 1
        if c >= len(values):
            return float(values[f])
        return float(values[f] + (values[c] - values[f]) * (k - f))

    def diagnostics(self) -> dict[str, Any]:
        """Return rich diagnostic stats."""
        total = len(self._events)
        failures = sum(1 for event in self._events if not event.ok)
        durations = [event.duration_ms for event in self._events]
        per_backend: dict[str, int] = {}
        for event in self._events:
            per_backend[event.backend_id] = per_backend.get(event.backend_id, 0) + 1
        return {
            "total_events": total,
            "failures": failures,
            "successes": total - failures,
            "error_rate": failures / total if total else 0.0,
            "p50_duration_ms": self.percentile("duration_ms", 50),
            "p95_duration_ms": self.percentile("duration_ms", 95),
            "p99_duration_ms": self.percentile("duration_ms", 99),
            "average_duration_ms": sum(durations) / total if total else 0,
            "per_backend_events": per_backend,
        }

    def export_json(self, path: str) -> str:
        """Export events as JSON to *path*. Returns the written content."""
        import json as _json
        data = {
            "events": [event.to_dict() for event in self._events],
            "summary": self.summary(),
        }
        content = _json.dumps(data, indent=2)
        Path(path).write_text(content, encoding="utf-8")
        return content

    def export_csv(self, path: str) -> str:
        """Export events as CSV to *path*. Returns the written content."""
        import csv as _csv
        from io import StringIO as _StringIO
        buf = _StringIO()
        writer = _csv.writer(buf)
        writer.writerow(["task_id", "backend_id", "ok", "started_at", "finished_at", "duration_ms", "error"])
        for event in self._events:
            writer.writerow([
                event.task_id, event.backend_id, event.ok,
                event.started_at, event.finished_at, event.duration_ms,
                event.error or "",
            ])
        content = buf.getvalue()
        buf.close()
        Path(path).write_text(content, encoding="utf-8")
        return content

    def export_dashboard(self) -> dict[str, Any]:
        """Return data suitable for a web dashboard."""
        from collections import defaultdict
        hourly: dict[str, list] = defaultdict(list)
        for event in self._events:
            hour = f"{int(event.started_at // 3600):04d}:{int((event.started_at % 3600) // 60):02d}"
            hourly[hour].append(event.to_dict())
        return {
            "events_by_hour": dict(hourly),
            "summary": self.summary(),
            "diagnostics": self.diagnostics(),
        }


def now() -> float:
    return time()
