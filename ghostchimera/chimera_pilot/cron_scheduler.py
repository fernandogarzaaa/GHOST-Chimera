"""Cron scheduler — persistent scheduled task execution.

Patterns adapted from Hermes-Agent's cron scheduler (Nous Research, MIT licensed).
Supports cron expressions, recurring tasks, and trigger-based execution
with persistent state storage.

Implements :class:`~ghostchimera.chimera_pilot.service_registry.BackgroundService`
so it can be managed by the :class:`~ghostchimera.chimera_pilot.service_registry.ServiceRegistry`.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from croniter import croniter

from ..agent_core.core import AgentCore
from ..chimera_pilot.task_ir import TaskKind
from ..config import GhostChimeraConfig
from ..logging_config import get_logger
from .service_registry import BackgroundService, ServiceHealth

logger = get_logger("cron_scheduler")

# ---------------------------------------------------------------------------
# Constants
# --------------------------- ----------------------- ---------------

DEFAULT_POLL_INTERVAL = 60  # seconds
DEFAULT_STATE_FILE = "cron_jobs.json"
DEFAULT_TIMEZONE = "UTC"

# ---------------------------------------------------------------------------
# Data types
# --------------------------- ----------------------- ---------------

@dataclass()
class CronJob:
    """A scheduled cron job."""
    id: str
    name: str
    cron_expression: str
    objective: str
    task_kind: TaskKind = TaskKind.REASONING
    enabled: bool = True
    next_run: float = 0.0
    last_run: float = 0.0
    run_count: int = 0
    timezone: str = DEFAULT_TIMEZONE
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "cron_expression": self.cron_expression,
            "objective": self.objective,
            "task_kind": self.task_kind.value,
            "enabled": self.enabled,
            "next_run": self.next_run,
            "last_run": self.last_run,
            "run_count": self.run_count,
            "timezone": self.timezone,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronJob:
        return cls(
            id=data["id"],
            name=data["name"],
            cron_expression=data["cron_expression"],
            objective=data["objective"],
            task_kind=TaskKind(data.get("task_kind", "reasoning")),
            enabled=data.get("enabled", True),
            next_run=data.get("next_run", 0.0),
            last_run=data.get("last_run", 0.0),
            run_count=data.get("run_count", 0),
            timezone=data.get("timezone", DEFAULT_TIMEZONE),
            metadata=data.get("metadata", {}),
        )

    def update_next_run(self) -> float:
        """Update the next_run time. Returns the new timestamp."""
        now = time.time()
        try:
            next_time = croniter(self.cron_expression, now).get_next()
            self.next_run = next_time
        except (ValueError, KeyError) as exc:
            logger.error("Invalid cron expression '%s': %s", self.cron_expression, exc)
            self.next_run = now + 86400  # default: run tomorrow
        return self.next_run


@dataclass(frozen=True)
class CronJobResult:
    """Result from executing a cron job."""
    job_id: str
    job_name: str
    objective: str
    success: bool
    output: str = ""
    error: str | None = None
    run_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_name": self.job_name,
            "success": self.success,
            "output": self.output[:2000],
            "error": self.error,
            "run_at": self.run_at,
        }

# ---------------------------------------------------------------------------
# Cron scheduler
# --------------------------- ----------------------- ---------------

class CronScheduler(BackgroundService):
    """Persistent cron-style task scheduler.

    Implements :class:`~ghostchimera.chimera_pilot.service_registry.BackgroundService`.
    """

    service_id = "cron_scheduler"
    service_name = "Cron Scheduler"
    service_description = "Persistent cron-style task scheduler"

    def __init__(
        self,
        state_dir: str | Path | None = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        config: GhostChimeraConfig | None = None,
        job_executor: Callable[[CronJob], CronJobResult] | None = None,
    ):
        self.jobs: dict[str, CronJob] = {}
        self._lock = threading.RLock()
        self.poll_interval = poll_interval
        self.config = config or GhostChimeraConfig.from_env()
        self.job_executor = job_executor
        self._state_dir = Path(state_dir or self.config.state_dir)
        self._state_file = self._state_dir / DEFAULT_STATE_FILE
        self._running = False
        self._thread: threading.Thread | None = None
        self._load_jobs()

    def add_job(
        self,
        name: str,
        cron_expression: str,
        objective: str,
        task_kind: TaskKind = TaskKind.REASONING,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> CronJob:
        """Add a new scheduled job."""
        import uuid
        job_id = f"cron-{uuid.uuid4().hex[:8]}"
        job = CronJob(
            id=job_id,
            name=name,
            cron_expression=cron_expression,
            objective=objective,
            task_kind=task_kind,
            enabled=enabled,
            metadata=metadata or {},
        )
        job.update_next_run()

        with self._lock:
            self.jobs[job_id] = job
        self._save_jobs()
        logger.info("Added cron job '%s' (cron: %s, next: %s)", name, cron_expression, job.next_run)
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        with self._lock:
            if job_id in self.jobs:
                del self.jobs[job_id]
                self._save_jobs()
                return True
        return False

    def list_jobs(self) -> list[CronJob]:
        """List all jobs, sorted by next_run."""
        with self._lock:
            return sorted(self.jobs.values(), key=lambda j: j.next_run)

    def enable_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self.jobs:
                self.jobs[job_id].enabled = True
                self.jobs[job_id].update_next_run()
                self._save_jobs()
                return True
        return False

    def disable_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self.jobs:
                self.jobs[job_id].enabled = False
                self._save_jobs()
                return True
        return False

    def tick(self) -> list[CronJobResult]:
        """Check for due jobs and execute them. Returns results."""
        now = time.time()
        results = []

        with self._lock:
            due_jobs = [j for j in self.jobs.values() if j.enabled and j.next_run <= now]

        for job in due_jobs:
            result = self._run_job(job)
            results.append(result)

            # Update job state
            with self._lock:
                if job.id in self.jobs:
                    self.jobs[job.id].last_run = now
                    self.jobs[job.id].run_count += 1
                    self.jobs[job.id].update_next_run()
            self._save_jobs()

        return results

    def run_due_jobs(self) -> list[CronJobResult]:
        """Convenience alias for tick()."""
        return self.tick()

    def start(self) -> threading.Thread:
        """Start the scheduler loop in a background thread."""
        self._running = True

        def loop():
            while self._running:
                try:
                    self.tick()
                except Exception as exc:
                    logger.error("Cron scheduler error: %s", exc)
                time.sleep(self.poll_interval)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        logger.info("Cron scheduler started (interval: %ds)", self.poll_interval)
        return self._thread

    def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("Cron scheduler stopped")

    def probe(self) -> ServiceHealth:
        """Return the health of the cron scheduler."""
        with self._lock:
            job_count = len(self.jobs)
            enabled = sum(1 for j in self.jobs.values() if j.enabled)
            running = self._running and self._thread is not None and self._thread.is_alive()
        return ServiceHealth(
            ok=running,
            state="running" if running else "stopped",
            details={"job_count": job_count, "enabled_count": enabled},
        )

    def status(self) -> dict[str, Any]:
        """Scheduler status."""
        with self._lock:
            return {
                "running": self._running,
                "job_count": len(self.jobs),
                "enabled_count": sum(1 for j in self.jobs.values() if j.enabled),
                "poll_interval": self.poll_interval,
                "jobs": [j.to_dict() for j in sorted(self.jobs.values(), key=lambda j: j.next_run)],
            }

    def _run_job(self, job: CronJob) -> CronJobResult:
        """Execute a cron job."""
        if self.job_executor is not None:
            return self.job_executor(job)
        try:
            kernel = AgentCore.default()
            results = kernel.compile_and_run(job.objective)
            return CronJobResult(
                job_id=job.id,
                job_name=job.name,
                objective=job.objective,
                success=True,
                output=json.dumps([r.to_dict() for r in results])[:3000],
            )
        except Exception as exc:
            logger.error("Cron job '%s' failed: %s", job.name, exc)
            return CronJobResult(
                job_id=job.id,
                job_name=job.name,
                objective=job.objective,
                success=False,
                error=str(exc),
            )

    def _load_jobs(self) -> None:
        """Load jobs from state file."""
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    data = json.load(f)
                    for jid, jdata in data.get("jobs", {}).items():
                        job = CronJob.from_dict(jdata)
                        # Update next_run in case time has passed
                        job.update_next_run()
                        self.jobs[jid] = job
                logger.info("Loaded %d cron jobs from %s", len(self.jobs), self._state_file)
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to load cron jobs: %s", exc)
        else:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)

    def _save_jobs(self) -> None:
        """Save jobs to state file."""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": "1.0",
                "saved_at": time.time(),
                "jobs": {jid: j.to_dict() for jid, j in self.jobs.items()},
            }
            tmp_file = self._state_file.with_suffix(".tmp")
            with open(tmp_file, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_file, self._state_file)
        except Exception as exc:
            logger.error("Failed to save cron jobs: %s", exc)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_scheduler: CronScheduler | None = None
_scheduler_lock = threading.Lock()


def get_scheduler(state_dir: str | Path | None = None) -> CronScheduler:
    """Get the singleton cron scheduler."""
    global _scheduler
    if _scheduler is None:
        with _scheduler_lock:
            if _scheduler is None:
                _scheduler = CronScheduler(state_dir)
    return _scheduler


def add_job(
    name: str,
    cron_expression: str,
    objective: str,
    **kwargs,
) -> CronJob:
    """Quick job addition."""
    return get_scheduler().add_job(name, cron_expression, objective, **kwargs)


def start_scheduler() -> threading.Thread:
    """Start the cron scheduler."""
    return get_scheduler().start()


def stop_scheduler() -> None:
    """Stop the cron scheduler."""
    get_scheduler().stop()


__all__ = [
    "CronScheduler",
    "CronJob",
    "CronJobResult",
    "get_scheduler",
    "add_job",
    "start_scheduler",
    "stop_scheduler",
]
