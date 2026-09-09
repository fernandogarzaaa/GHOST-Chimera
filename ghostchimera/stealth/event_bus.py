"""Event Fabric: producer -> normalizer -> classifier -> deduplicator -> bus -> consumers.

Decoupled pub/sub. Consumers never talk to producers. Delivery is
synchronous and in-order per ``emit`` call; durability/retry lives in
the Background Runtime (Phase 4), not here. ``replay()`` re-runs a
recorded sequence with side-effecting consumers disabled.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from ..logging_config import get_logger
from .events import Event, normalize_event

logger = get_logger("stealth.event_bus")

Consumer = Callable[[Event], None]


class EventBus:
    """Thread-safe, idempotent, replayable event bus."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Consumer]] = defaultdict(list)
        self._wildcards: list[Consumer] = []
        self._seen_ids: set[str] = set()
        self._lock = threading.Lock()
        self._log: list[Event] = []
        self._dropped_duplicates = 0

    # -- subscription -------------------------------------------------
    def subscribe(self, event_type: str, consumer: Consumer) -> None:
        """Subscribe to an exact type, ``prefix.*``, or ``*``."""
        with self._lock:
            if event_type == "*":
                self._wildcards.append(consumer)
            else:
                self._subs[event_type].append(consumer)

    def unsubscribe(self, event_type: str, consumer: Consumer) -> None:
        with self._lock:
            targets = self._wildcards if event_type == "*" else self._subs.get(event_type, [])
            try:
                targets.remove(consumer)
            except ValueError:
                pass

    # -- emission -----------------------------------------------------
    def emit(self, event: Event) -> bool:
        """Normalize -> dedup -> classify -> deliver. Returns True if delivered."""
        event = normalize_event(event)
        with self._lock:
            if event.event_id in self._seen_ids:
                self._dropped_duplicates += 1
                return False
            self._seen_ids.add(event.event_id)
            self._log.append(event)
            consumers = list(self._subs.get(event.event_type, []))
            prefix = event.event_type.split(".")[0] + ".*"
            consumers += list(self._subs.get(prefix, []))
            consumers += list(self._wildcards)
        for consumer in consumers:
            try:
                consumer(event)
            except Exception as exc:  # never take down the producer/host
                logger.warning("EventBus consumer %s raised on %s: %s", consumer, event.event_type, exc)
        return True

    # -- observability / replay ---------------------------------------
    def replay(self, events: list[Event], *, read_only: bool = True) -> int:
        """Re-process a sequence without external side effects.

        In read-only mode only consumers marked ``_ghost_read_only=True``
        receive events; mutating consumers must opt out by not setting it.
        Returns the number of events delivered.
        """
        delivered = 0
        with self._lock:
            subs_snapshot = {k: list(v) for k, v in self._subs.items()}
            wildcards_snapshot = list(self._wildcards)
        for event in events:
            event = normalize_event(event)
            consumers: list[Consumer] = list(subs_snapshot.get(event.event_type, []))
            prefix = event.event_type.split(".")[0] + ".*"
            consumers += list(subs_snapshot.get(prefix, []))
            consumers += list(wildcards_snapshot)
            if read_only:
                consumers = [c for c in consumers if getattr(c, "_ghost_read_only", False)]
            for consumer in consumers:
                try:
                    consumer(event)
                except Exception as exc:
                    logger.warning("Replay consumer %s raised: %s", consumer, exc)
            delivered += 1
        return delivered

    @property
    def processed(self) -> int:
        with self._lock:
            return len(self._log)

    @property
    def dropped_duplicates(self) -> int:
        with self._lock:
            return self._dropped_duplicates

    def event_log(self) -> list[Event]:
        with self._lock:
            return list(self._log)

    def clear(self) -> None:
        with self._lock:
            self._subs.clear()
            self._wildcards.clear()
            self._seen_ids.clear()
            self._log.clear()
            self._dropped_duplicates = 0


def read_only_consumer(fn: Consumer) -> Consumer:
    """Mark a consumer safe for replay mode."""
    fn._ghost_read_only = True  # type: ignore[attr-defined]
    return fn


__all__ = ["Consumer", "EventBus", "read_only_consumer"]
