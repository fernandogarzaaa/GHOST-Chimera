"""Temporal context: a unified model of "now" for hosts and tasks.

Timestamps dot every event and recency decay lives in two places, but
nothing answers "what time is it for the user and what's happening."
TemporalContext ingests calendar events into upcoming items, frames the
moment (daypart, weekday, quiet hours), and renders a compact block so
hosts can greet, prioritize, and stay silent at the right times. Pure
observation — it never schedules, reminds, or acts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .events import Event

CALENDAR_TYPES = frozenset({"calendar.event_created", "calendar.event_updated", "calendar.event_starting"})

END_GRACE_S = 900.0
DEFAULT_DURATION_S = 3600.0


def _as_epoch(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        try:
            moment = float(value)
        except ValueError:
            return None
        return moment if moment > 0 else None
    return None


def daypart(now: float | None = None) -> str:
    """Local daypart: morning / afternoon / evening / night."""

    hour = datetime.fromtimestamp(now if now is not None else time.time()).hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def is_quiet_hours(now: float | None = None) -> bool:
    """Late night and early morning stay silent by default."""

    hour = datetime.fromtimestamp(now if now is not None else time.time()).hour
    return hour < 7 or hour >= 22


def _in_dur(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"in {int(seconds // 60)}m"
    if seconds < 86400:
        hours = seconds / 3600
        return f"in {int(hours)}h" if hours < 10 else f"in {round(hours)}h"
    return f"in {int(seconds // 86400)}d"


@dataclass
class CalendarItem:
    """One upcoming (or just-finished) calendar entry."""

    id: str
    title: str = ""
    starts_at: float = 0.0
    ends_at: float = 0.0
    source_event_id: str = ""

    def happening(self, now: float) -> bool:
        return self.starts_at <= now < self.ends_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "source_event_id": self.source_event_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalendarItem | None:
        data = data if isinstance(data, dict) else {}
        starts_at = _as_epoch(data.get("starts_at"))
        if starts_at is None:
            return None
        ends_at = _as_epoch(data.get("ends_at")) or (starts_at + DEFAULT_DURATION_S)
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            starts_at=starts_at,
            ends_at=max(ends_at, starts_at),
            source_event_id=str(data.get("source_event_id", "")),
        )


def item_from_event(event: Event) -> CalendarItem | None:
    """Extract a calendar item from a calendar.* event payload."""

    payload = event.payload if isinstance(event.payload, dict) else {}
    starts_at = _as_epoch(payload.get("starts_at", payload.get("start", payload.get("start_time"))))
    if starts_at is None:
        return None
    ends_at = _as_epoch(payload.get("ends_at", payload.get("end", payload.get("end_time"))))
    title = str(payload.get("title", payload.get("summary", payload.get("subject", ""))))
    key = str(payload.get("event_id", payload.get("id", ""))) or f"{title}@{starts_at:.0f}"
    end = ends_at if ends_at is not None and ends_at > starts_at else starts_at + DEFAULT_DURATION_S
    return CalendarItem(
        id=key,
        title=title or "untitled",
        starts_at=starts_at,
        ends_at=end,
        source_event_id=event.event_id,
    )


class TemporalContext:
    """Ingested calendar items plus framing of the current moment."""

    def __init__(self) -> None:
        self._items: dict[str, CalendarItem] = {}

    def observe_event(self, event: Event) -> bool:
        """Ingest calendar events (upsert); prune ended items. True on change."""

        self.prune(event.timestamp)
        if event.event_type not in CALENDAR_TYPES:
            return False
        item = item_from_event(event)
        if item is None:
            return False
        self._items[item.id] = item
        return True

    def prune(self, now: float | None = None) -> int:
        """Drop items ended beyond the grace window; returns removals."""

        moment = now if now is not None else time.time()
        expired = [key for key, item in self._items.items() if moment >= item.ends_at + END_GRACE_S]
        for key in expired:
            del self._items[key]
        return len(expired)

    def happening_now(self, now: float | None = None) -> list[CalendarItem]:
        moment = now if now is not None else time.time()
        return sorted(
            (item for item in self._items.values() if item.happening(moment)),
            key=lambda item: item.starts_at,
        )

    def upcoming(self, now: float | None = None, *, within_s: float = 86400.0, limit: int = 5) -> list[CalendarItem]:
        """Future items soonest-first, bounded by window and count."""

        moment = now if now is not None else time.time()
        window = max(0.0, within_s)
        return sorted(
            (item for item in self._items.values() if moment < item.starts_at <= moment + window),
            key=lambda item: item.starts_at,
        )[: max(0, limit)]

    def describe(self, now: float | None = None) -> str:
        """Short framing: weekday, daypart, quiet-hours flag."""

        moment = now if now is not None else time.time()
        stamp = datetime.fromtimestamp(moment)
        parts = [f"{stamp.strftime('%A')} {daypart(moment)}"]
        if is_quiet_hours(moment):
            parts.append("quiet hours")
        return ", ".join(parts)

    def render(self, *, now: float | None = None, max_chars: int = 500) -> str:
        """Compact temporal block for hosts and tasks."""

        moment = now if now is not None else time.time()
        lines = ["# Temporal context", self.describe(moment)]
        for item in self.happening_now(moment):
            lines.append(f"now: {item.title} (until {_clock(item.ends_at)})")
        for item in self.upcoming(moment):
            lines.append(f"next: {item.title} {_in_dur(item.starts_at - moment)}")
        if len(lines) == 2:
            lines.append("(no upcoming items)")
        block = "\n".join(lines).strip()
        budget = max(0, max_chars)
        if len(block) > budget:
            block = block[:budget].rstrip() + "\n[...truncated...]"
        return block

    def __len__(self) -> int:
        return len(self._items)

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self._items.values()]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemporalContext:
        context = cls()
        for raw in (data or {}).get("items", []) or []:
            item = CalendarItem.from_dict(raw)
            if item is not None:
                context._items[item.id] = item
        return context


def _clock(moment: float) -> str:
    return datetime.fromtimestamp(moment).strftime("%H:%M")


__all__ = [
    "CALENDAR_TYPES",
    "DEFAULT_DURATION_S",
    "END_GRACE_S",
    "CalendarItem",
    "TemporalContext",
    "daypart",
    "is_quiet_hours",
    "item_from_event",
]
