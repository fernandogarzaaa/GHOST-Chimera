"""Security event monitor for Ghost Chimera.

Aggregates deep prompt inspection (DPI) events from the Lobster Trap
integration and provides a queryable store for the governance dashboard.

Events are persisted to a JSON file (``~/.ghostchimera/security_events.json``
by default) and kept in memory for fast dashboard queries.

Usage::

    from ghostchimera.safety_layer.security_monitor import SecurityEvent, SecurityMonitor, ThreatCategory

    monitor = SecurityMonitor()
    monitor.record_event(
        SecurityEvent(
            session_id="s1",
            categories=[ThreatCategory.PROMPT_INJECTION],
            risk_score=0.85,
            threats=["prompt_injection:ignore_previous_instructions"],
            action="DENY",
            blocked=True,
            text_snippet="ignore all previous instructions",
        )
    )
    summary = monitor.get_threat_summary()
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger("security_monitor")

_DEFAULT_EVENTS_FILE = os.environ.get(
    "GHOSTCHIMERA_SECURITY_EVENTS_FILE",
    os.path.expanduser("~/.ghostchimera/security_events.json"),
)


class ThreatCategory(StrEnum):
    """High-level threat classification mirroring Lobster Trap's intent taxonomy."""

    PROMPT_INJECTION = "prompt_injection"
    PII_EXFILTRATION = "pii_exfiltration"
    CREDENTIAL_LEAK = "credential_leak"
    EXFILTRATION = "exfiltration"
    INTENT_MISMATCH = "intent_mismatch"
    POLICY_VIOLATION = "policy_violation"
    RATE_LIMIT = "rate_limit"
    ADVERSARIAL = "adversarial"


@dataclass
class SecurityEvent:
    """A single security-relevant DPI inspection event."""

    session_id: str = ""
    categories: list[ThreatCategory] = field(default_factory=list)
    risk_score: float = 0.0
    threats: list[str] = field(default_factory=list)
    action: str = "ALLOW"
    rule_matched: str | None = None
    blocked: bool = False
    text_snippet: str = ""
    dpi_engine: str = "builtin"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["categories"] = [str(c) for c in self.categories]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityEvent:
        cats = []
        for c in data.get("categories", []):
            with contextlib.suppress(ValueError):
                cats.append(ThreatCategory(c))
        return cls(
            session_id=data.get("session_id", ""),
            categories=cats,
            risk_score=float(data.get("risk_score", 0.0)),
            threats=list(data.get("threats", [])),
            action=str(data.get("action", "ALLOW")),
            rule_matched=data.get("rule_matched"),
            blocked=bool(data.get("blocked", False)),
            text_snippet=str(data.get("text_snippet", "")),
            dpi_engine=str(data.get("dpi_engine", "builtin")),
            timestamp=str(data.get("timestamp", "")),
        )


class SecurityMonitor:
    """Thread-safe in-memory and file-backed security event store.

    Provides aggregated statistics and time-series data for the governance
    dashboard at ``/api/console/security/*``.
    """

    def __init__(self, events_file: str | None = None, max_events: int = 5000) -> None:
        self._events_file = events_file or _DEFAULT_EVENTS_FILE
        self._max_events = max_events
        self._events: list[SecurityEvent] = []
        self._lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_event(self, event: SecurityEvent) -> None:
        """Append *event* to the in-memory store and persist to disk."""
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]
            self._save_locked()
        if event.blocked:
            logger.warning(
                "Blocked [%s] risk=%.2f session=%s threats=%s",
                event.action,
                event.risk_score,
                event.session_id,
                ", ".join(event.threats[:3]),
            )
        elif event.risk_score >= 0.5:
            logger.info(
                "Risk event [%s] risk=%.2f session=%s",
                event.action,
                event.risk_score,
                event.session_id,
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_events(
        self,
        *,
        limit: int = 100,
        threat_category: ThreatCategory | str | None = None,
        session_id: str | None = None,
        blocked_only: bool = False,
        min_risk: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Return recent events matching the given filters."""
        with self._lock:
            events = list(self._events)
        if threat_category is not None:
            cat = ThreatCategory(threat_category) if isinstance(threat_category, str) else threat_category
            events = [e for e in events if cat in e.categories]
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        if blocked_only:
            events = [e for e in events if e.blocked]
        if min_risk > 0:
            events = [e for e in events if e.risk_score >= min_risk]
        return [e.to_dict() for e in events[-limit:]]

    def get_threat_summary(self) -> dict[str, Any]:
        """Return aggregated threat statistics for the governance dashboard."""
        with self._lock:
            events = list(self._events)
        if not events:
            return {
                "total_events": 0,
                "blocked_events": 0,
                "allowed_events": 0,
                "block_rate": 0.0,
                "average_risk_score": 0.0,
                "max_risk_score": 0.0,
                "by_category": {},
                "by_action": {},
                "top_threats": [],
                "sessions_affected": 0,
            }

        total = len(events)
        blocked = sum(1 for e in events if e.blocked)
        risk_scores = [e.risk_score for e in events]
        avg_risk = sum(risk_scores) / total
        max_risk = max(risk_scores)

        by_category: dict[str, int] = {}
        for event in events:
            for cat in event.categories:
                by_category[str(cat)] = by_category.get(str(cat), 0) + 1

        by_action: dict[str, int] = {}
        for event in events:
            by_action[event.action] = by_action.get(event.action, 0) + 1

        threat_counts: dict[str, int] = {}
        for event in events:
            for threat in event.threats:
                threat_counts[threat] = threat_counts.get(threat, 0) + 1
        top_threats = sorted(threat_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        sessions = {e.session_id for e in events if e.session_id}

        return {
            "total_events": total,
            "blocked_events": blocked,
            "allowed_events": total - blocked,
            "block_rate": round(blocked / total, 4) if total else 0.0,
            "average_risk_score": round(avg_risk, 4),
            "max_risk_score": round(max_risk, 4),
            "by_category": by_category,
            "by_action": by_action,
            "top_threats": [{"threat": t, "count": c} for t, c in top_threats],
            "sessions_affected": len(sessions),
        }

    def get_risk_timeline(self, *, bucket_minutes: int = 5) -> list[dict[str, Any]]:
        """Return risk scores bucketed into time intervals for chart display."""
        with self._lock:
            events = list(self._events)
        if not events:
            return []

        bucket_seconds = bucket_minutes * 60
        buckets: dict[int, list[float]] = {}
        blocked_buckets: dict[int, int] = {}

        for event in events:
            try:
                ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                continue
            bucket_key = int(ts // bucket_seconds) * bucket_seconds
            buckets.setdefault(bucket_key, []).append(event.risk_score)
            if event.blocked:
                blocked_buckets[bucket_key] = blocked_buckets.get(bucket_key, 0) + 1

        timeline = []
        for bucket_key in sorted(buckets):
            scores = buckets[bucket_key]
            timeline.append({
                "timestamp": datetime.fromtimestamp(bucket_key, tz=UTC).isoformat().replace("+00:00", "Z"),
                "event_count": len(scores),
                "blocked_count": blocked_buckets.get(bucket_key, 0),
                "average_risk_score": round(sum(scores) / len(scores), 4),
                "max_risk_score": round(max(scores), 4),
            })
        return timeline

    def clear(self) -> None:
        """Remove all in-memory events (used in tests)."""
        with self._lock:
            self._events.clear()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self._events_file):
            return
        try:
            with open(self._events_file, encoding="utf-8") as fh:
                raw = json.load(fh)
            for item in raw if isinstance(raw, list) else raw.get("events", []):
                self._events.append(SecurityEvent.from_dict(item))
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]
        except Exception as exc:
            logger.debug("Could not load security events: %s", exc)

    def _save_locked(self) -> None:
        """Must be called with ``self._lock`` held."""
        try:
            Path(self._events_file).parent.mkdir(parents=True, exist_ok=True)
            data = {"events": [e.to_dict() for e in self._events]}
            with open(self._events_file, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            logger.debug("Could not persist security events: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_monitor_instance: SecurityMonitor | None = None
_monitor_lock = threading.Lock()


def get_monitor(events_file: str | None = None) -> SecurityMonitor:
    """Return the process-wide :class:`SecurityMonitor` singleton."""
    global _monitor_instance  # noqa: PLW0603
    if _monitor_instance is None:
        with _monitor_lock:
            if _monitor_instance is None:
                _monitor_instance = SecurityMonitor(events_file=events_file)
    return _monitor_instance


__all__ = [
    "SecurityEvent",
    "SecurityMonitor",
    "ThreatCategory",
    "get_monitor",
]
