"""Event Fabric: producer -> normalizer -> classifier -> deduplicator -> bus -> consumers.

Decoupled pub/sub. Consumers never talk to producers. Delivery is
synchronous and in-order per ``emit`` call; durability/retry lives in
the Background Runtime (Phase 4), not here. ``replay()`` re-runs a
recorded sequence with side-effecting consumers disabled.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict, defaultdict, deque
from collections.abc import Callable
from contextlib import suppress

from ..logging_config import get_logger
from .events import Event, normalize_event

logger = get_logger("stealth.event_bus")

Consumer = Callable[[Event], None]

# The replay log and the dedup-id set used to grow forever (every event and its
# full payload held for the process lifetime). Both are now bounded.
DEFAULT_LOG_MAX = 5000
DEFAULT_SEEN_IDS_MAX = 50_000


def _env_cap(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return max(1, value)


class EventBus:
    """Thread-safe, idempotent, replayable event bus."""

    def __init__(self, *, log_max: int | None = None, seen_ids_max: int | None = None) -> None:
        self._subs: dict[str, list[Consumer]] = defaultdict(list)
        self._wildcards: list[Consumer] = []
        self.log_max = log_max or _env_cap("GHOSTCHIMERA_BUS_LOG_MAX", DEFAULT_LOG_MAX)
        self.seen_ids_max = max(
            self.log_max, seen_ids_max or _env_cap("GHOSTCHIMERA_BUS_SEEN_IDS_MAX", DEFAULT_SEEN_IDS_MAX)
        )
        # Insertion-ordered so the oldest ids are evicted first.
        self._seen_ids: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()
        self._log: deque[Event] = deque(maxlen=self.log_max)
        self._processed = 0
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
            with suppress(ValueError):
                targets.remove(consumer)

    # -- emission -----------------------------------------------------
    def emit(self, event: Event) -> bool:
        """Normalize -> dedup -> classify -> deliver. Returns True if delivered."""
        event = normalize_event(event)
        with self._lock:
            if event.event_id in self._seen_ids:
                self._dropped_duplicates += 1
                return False
            self._seen_ids[event.event_id] = None
            while len(self._seen_ids) > self.seen_ids_max:
                self._seen_ids.popitem(last=False)
            self._log.append(event)
            self._processed += 1
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
        """Events delivered since start (the replay log itself is bounded)."""
        with self._lock:
            return self._processed

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
            self._processed = 0
            self._dropped_duplicates = 0


def read_only_consumer(fn: Consumer) -> Consumer:
    """Mark a consumer safe for replay mode."""
    fn._ghost_read_only = True  # type: ignore[attr-defined]
    return fn


__all__ = ["Consumer", "EventBus", "read_only_consumer"]
