"""Background Runtime: durable queue + workers + retry + recovery.

Never blocks a host session: EVENT -> QUEUE -> BACKGROUND WORKER ->
PROCESS -> STORE RESULT -> AVAILABLE TO HOST. Failures degrade to
silence — a dead Ghost must never take down the host, and a dead
connector must never block the runtime.

Persistence is JSONL (stdlib-only). The existing AutonomyJobQueue /
CronScheduler can front this runtime later; the job envelope is
designed to map onto them without replacement.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BackgroundJob:
    id: str = field(default_factory=lambda: f"job-{uuid.uuid4().hex[:12]}")
    kind: str = "prepare_context"
    payload: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    max_attempts: int = 3
    created_at: float = field(default_factory=time.time)
    status: str = "queued"  # queued | running | done | failed | dead
    result: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "payload": dict(self.payload),
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackgroundJob:
        job = cls(id=str(data["id"]), kind=str(data.get("kind", "prepare_context")))
        job.payload = dict(data.get("payload") or {})
        job.attempts = int(data.get("attempts", 0))
        job.max_attempts = int(data.get("max_attempts", 3))
        job.created_at = float(data.get("created_at", time.time()))
        job.status = str(data.get("status", "queued"))
        job.result = data.get("result")
        job.error = str(data.get("error", ""))
        return job


Handler = Callable[[BackgroundJob], dict[str, Any]]


class BackgroundRuntime:
    """Thread-pool runtime with persistent queue and bounded retry."""

    def __init__(self, *, workers: int = 2, queue_file: str | Path | None = None) -> None:
        self._queue: queue.Queue[BackgroundJob] = queue.Queue()
        self._handlers: dict[str, Handler] = {}
        self._jobs: dict[str, BackgroundJob] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._workers = max(1, workers)
        self._queue_file = Path(queue_file) if queue_file else None
        if self._queue_file is not None:
            self._recover()

    # -- handlers ------------------------------------------------------
    def register(self, kind: str, handler: Handler) -> None:
        with self._lock:
            self._handlers[kind] = handler

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for i in range(self._workers):
            thread = threading.Thread(target=self._work, name=f"ghost-worker-{i}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout / max(1, len(self._threads)))
        self._threads.clear()

    # -- jobs -------------------------------------------------------------
    def submit(self, kind: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> BackgroundJob:
        job = BackgroundJob(kind=kind, payload=dict(payload or {}), **kwargs)
        with self._lock:
            self._jobs[job.id] = job
        self._persist(job)
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> BackgroundJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def wait_for(self, job_id: str, *, timeout: float = 30.0) -> BackgroundJob | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.get(job_id)
            if job is not None and job.status in ("done", "failed", "dead"):
                return job
            time.sleep(0.05)
        return self.get(job_id)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            statuses: dict[str, int] = {}
            for job in self._jobs.values():
                statuses[job.status] = statuses.get(job.status, 0) + 1
            return {"queued": self._queue.qsize(), "total": len(self._jobs), "by_status": statuses}

    # -- internals ----------------------------------------------------------
    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._run(job)
            finally:
                self._queue.task_done()

    def _run(self, job: BackgroundJob) -> None:
        handler = self._handlers.get(job.kind)
        job.attempts += 1
        job.status = "running"
        if handler is None:
            job.status = "failed"
            job.error = f"no handler for kind={job.kind}"
            self._persist(job)
            return
        try:
            job.result = handler(job)
            job.status = "done"
        except Exception as exc:
            job.error = f"{type(exc).__name__}: {exc}"
            if job.attempts >= job.max_attempts:
                job.status = "dead"  # parked, never blocks the runtime
            else:
                job.status = "queued"
                backoff = min(30.0, 0.5 * (2 ** (job.attempts - 1)))
                timer = threading.Timer(backoff, self._requeue, args=(job,))
                timer.daemon = True
                timer.start()
        self._persist(job)

    def _requeue(self, job: BackgroundJob) -> None:
        if self._stop.is_set():
            return
        self._queue.put(job)

    def _persist(self, job: BackgroundJob) -> None:
        if self._queue_file is None:
            return
        try:
            self._queue_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._queue_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(job.to_dict()) + "\n")
        except OSError:
            pass  # persistence is best-effort; memory remains authoritative

    def _recover(self) -> None:
        assert self._queue_file is not None
        try:
            lines = self._queue_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        latest: dict[str, BackgroundJob] = {}
        for line in lines:
            try:
                job = BackgroundJob.from_dict(json.loads(line))
            except (json.JSONDecodeError, KeyError):
                continue
            latest[job.id] = job
        for job in latest.values():
            if job.status in ("queued", "running"):
                job.status = "queued"  # interrupted work is retried, never lost
                job.attempts = 0
                with self._lock:
                    self._jobs[job.id] = job
                self._queue.put(job)


__all__ = ["BackgroundJob", "BackgroundRuntime", "Handler"]
