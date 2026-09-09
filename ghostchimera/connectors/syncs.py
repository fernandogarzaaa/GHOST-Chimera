"""Syncs: scheduled connector polling, Nango-Syncs parity, self-hosted.

Nango's remaining capability beyond auth/proxy/webhooks is Syncs —
periodic pulls that keep downstream models fresh. This is that, without
the cloud: register any Connector with an interval, and each tick polls
it into the Stealth loop (or any emit function). Failures degrade per
connector and never stop the schedule. Thread-based, stdlib-only.
"""

from __future__ import annotations

import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from .base import Connector, EmitFn


@dataclass
class SyncRecord:
    connector_id: str
    interval_s: float
    last_run_at: float = 0.0
    last_delivered: int = 0
    last_error: str = ""
    runs: int = 0


class SyncScheduler:
    """Tick loop over registered connectors. Start/stop idempotent."""

    def __init__(self, emit: EmitFn, *, tick_s: float = 5.0) -> None:
        self._emit = emit
        self._tick_s = max(1.0, tick_s)
        self._registry: dict[str, tuple[Connector, float]] = {}
        self._records: dict[str, SyncRecord] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, connector: Connector, *, interval_s: float = 300.0) -> None:
        with self._lock:
            self._registry[connector.id] = (connector, max(5.0, interval_s))
            self._records.setdefault(connector.id, SyncRecord(connector.id, interval_s))

    def unregister(self, connector_id: str) -> bool:
        with self._lock:
            self._records.pop(connector_id, None)
            return self._registry.pop(connector_id, None) is not None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ghost-syncs", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def run_due_now(self) -> dict[str, int]:
        """Poll every due connector once. Returns {connector_id: delivered}."""
        now = time.time()
        due: list[tuple[str, Connector]] = []
        with self._lock:
            items = list(self._registry.items())
        for connector_id, (connector, interval) in items:
            record = self._records[connector_id]
            if now - record.last_run_at >= interval:
                due.append((connector_id, connector))
        results: dict[str, int] = {}
        for connector_id, connector in due:
            try:
                delivered = connector.poll(self._emit)
                error = ""
            except Exception as exc:  # last-resort guard; poll() already isolates
                delivered, error = 0, f"{type(exc).__name__}: {exc}"
            with self._lock:
                record = self._records[connector_id]
                record.last_run_at = time.time()
                record.last_delivered = delivered
                record.last_error = error
                record.runs += 1
            results[connector_id] = delivered
        return results

    def _loop(self) -> None:
        while not self._stop.is_set():
            with suppress(Exception):  # the schedule itself never dies
                self.run_due_now()
            self._stop.wait(self._tick_s)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"running": self._thread is not None and self._thread.is_alive(),
                    "syncs": [
                        {"connector_id": r.connector_id, "interval_s": r.interval_s,
                         "runs": r.runs, "last_delivered": r.last_delivered,
                         "last_error": r.last_error, "last_run_at": r.last_run_at}
                        for r in self._records.values()]}


__all__ = ["SyncRecord", "SyncScheduler"]
