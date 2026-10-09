"""Background execution of long console operations.

POST /api/console/run (and siblings) must not block an HTTP worker thread for
the whole objective. This module owns the small job manager: each submitted
callable runs on a daemon worker thread, bounded by a semaphore so a burst of
runs cannot exhaust the machine. Callers get a run_id immediately (HTTP 202),
then poll run status / history or cancel.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Terminal states: the worker thread has finished (or will never start).
TERMINAL_RUN_STATES = frozenset({"completed", "failed", "cancelled"})


@dataclass
class ConsoleRun:
    run_id: str
    label: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "label": self.label,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


class ConsoleRunManager:
    """Run callables on background threads with bounded concurrency."""

    def __init__(self, max_concurrent: int = 4, history_limit: int = 100) -> None:
        self._semaphore = threading.Semaphore(max_concurrent)
        self._history_limit = history_limit
        self._runs: dict[str, ConsoleRun] = {}
        self._lock = threading.Lock()

    def submit(self, label: str, fn: Callable[[], Any]) -> ConsoleRun:
        run = ConsoleRun(run_id=uuid.uuid4().hex, label=label)

        def _worker() -> None:
            # Bound concurrency: wait here (still "queued") until a slot frees.
            with self._semaphore:
                with self._lock:
                    if run._cancel_event.is_set():
                        run.status = "cancelled"
                        run.finished_at = time.time()
                        return
                    run.status = "running"
                    run.started_at = time.time()
                try:
                    result = fn()
                except Exception as exc:  # noqa: BLE001 - surfaced via run record
                    with self._lock:
                        run.status = "failed"
                        run.error = str(exc)
                        run.finished_at = time.time()
                else:
                    with self._lock:
                        if run._cancel_event.is_set():
                            run.status = "cancelled"
                        else:
                            run.status = "completed"
                            run.result = result
                        run.finished_at = time.time()

        thread = threading.Thread(target=_worker, name=f"console-run-{run.run_id[:8]}", daemon=True)
        run._thread = thread
        with self._lock:
            self._runs[run.run_id] = run
            # Bound memory: drop oldest terminal runs beyond the history limit.
            terminal = [r for r in self._runs.values() if r.status in TERMINAL_RUN_STATES]
            if len(terminal) > self._history_limit:
                terminal.sort(key=lambda r: r.finished_at or 0)
                for old in terminal[: len(terminal) - self._history_limit]:
                    del self._runs[old.run_id]
        thread.start()
        return run

    def get(self, run_id: str) -> ConsoleRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
            return [r.to_dict() for r in runs]

    def cancel(self, run_id: str) -> dict[str, Any]:
        """Request cancellation. Cooperative: a queued run never starts; a
        running run is marked cancelled and its result is discarded."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return {"ok": False, "error": "Unknown run_id"}
            if run.status in TERMINAL_RUN_STATES:
                return {"ok": True, "run_id": run_id, "status": run.status, "already_done": True}
            run._cancel_event.set()
            run.status = "cancelled"
            run.finished_at = time.time()
            return {"ok": True, "run_id": run_id, "status": "cancelled"}
