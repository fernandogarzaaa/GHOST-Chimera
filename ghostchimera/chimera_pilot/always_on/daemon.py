"""Always-on daemon: the persistent agent runtime.

The daemon owns the agent lifecycle:

* ``sleeping`` — idle, waiting for a trigger.
* ``queued`` — a wake request is waiting to be processed.
* ``awake`` — actively executing a wake request.
* ``completed`` — a wake request finished (recorded in the wake history).

Wake sources are webhooks (:class:`WebhookRegistry`), schedules (the shared
:class:`CronScheduler`, whose job executor wakes the daemon), and direct
``wake()`` calls. Wake requests are persisted to
``<state_dir>/always_on/wake_queue/`` so a wake enqueued from another process
(the Ghost Console, the CLI) is picked up even when the daemon runs
elsewhere. Processed requests move to ``wake_queue/done/``.

Tool execution inside the daemon always flows through
:class:`QueuedApprovalHandler`, installed as the process-default approval
handler while the daemon runs: high-stakes actions pause for a human
decision instead of executing. There is no auto-approve path.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import signal
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ...config import GhostChimeraConfig
from ...logging_config import get_logger
from ...safety_layer.approval import ApprovalHandler, get_default_handler, set_default_handler
from ..autonomy import AutonomyProfile, get_autonomy_profile
from ..cron_scheduler import CronJob, CronJobResult, CronScheduler
from ..service_registry import BackgroundService, ServiceHealth
from ..subagent import DelegationContract, DelegationResult, SubagentPool
from .approvals import ApprovalStore, QueuedApprovalHandler
from .compaction import AutoCompactor
from .identity import IdentityStore
from .sessions import DurableSession, SessionStore
from .triggers import WebhookRegistry

logger = get_logger("always_on.daemon")

WAKE_QUEUE_DIRNAME = "wake_queue"
WAKE_DONE_DIRNAME = "done"
MAX_WAKE_HISTORY_FILES = 200


class LifecycleState(StrEnum):
    """Explicit lifecycle states for an always-on agent."""

    SLEEPING = "sleeping"
    QUEUED = "queued"
    AWAKE = "awake"
    COMPLETED = "completed"


WAKE_STATUS_QUEUED = "queued"
WAKE_STATUS_RUNNING = "running"
WAKE_STATUS_COMPLETED = "completed"
WAKE_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class WakeRequest:
    """One unit of agent work waiting for (or undergoing) execution."""

    request_id: str
    objective: str
    source: str
    agent_id: str
    created_at: float
    status: str = WAKE_STATUS_QUEUED
    result_summary: str = ""
    error: str = ""
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "objective": self.objective,
            "source": self.source,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "status": self.status,
            "result_summary": self.result_summary,
            "error": self.error,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WakeRequest:
        return cls(
            request_id=str(data["request_id"]),
            objective=str(data.get("objective") or ""),
            source=str(data.get("source") or "manual"),
            agent_id=str(data.get("agent_id") or ""),
            created_at=float(data.get("created_at") or 0.0),
            status=str(data.get("status") or WAKE_STATUS_QUEUED),
            result_summary=str(data.get("result_summary") or ""),
            error=str(data.get("error") or ""),
            finished_at=data.get("finished_at"),
        )


# Executor: (objective, durable_session) -> result text. Injected in tests.
Executor = Callable[[str, DurableSession], str]


class AlwaysOnDaemon(BackgroundService):
    """Persistent agent runtime with explicit lifecycle states."""

    service_id = "always_on_daemon"
    service_name = "Always-On Agent Daemon"
    service_description = "Persistent agent runtime: wake triggers, durable sessions, approval-gated execution"

    def __init__(
        self,
        *,
        state_dir: str | Path | None = None,
        config: GhostChimeraConfig | None = None,
        profile: str | AutonomyProfile = "supervised",
        executor: Executor | None = None,
        subagent_pool_factory: Any | None = None,
        approval_wait_timeout_seconds: float = 300.0,
        cron_poll_interval: float = 60.0,
    ) -> None:
        self.config = config or GhostChimeraConfig.from_env()
        base = Path(state_dir or self.config.state_dir).expanduser()
        self.state_dir = base
        self.profile = profile if isinstance(profile, AutonomyProfile) else get_autonomy_profile(profile)

        self.identities = IdentityStore(base)
        self.sessions = SessionStore(base)
        self.approval_store = ApprovalStore(base)
        self.approval_handler = QueuedApprovalHandler(
            self.approval_store,
            wait_timeout_seconds=approval_wait_timeout_seconds,
            policy=None,
        )
        self.webhooks = WebhookRegistry(base)
        self.compactor = AutoCompactor()

        self._wake_dir = base / "always_on" / WAKE_QUEUE_DIRNAME
        self._wake_done_dir = self._wake_dir / WAKE_DONE_DIRNAME
        self._wake_queue: queue.Queue[WakeRequest] = queue.Queue()
        self._seen_wake_ids: set[str] = set()

        self._executor = executor or self._default_executor
        self._pool_factory = subagent_pool_factory or self._default_pool_factory

        self._cron = CronScheduler(
            state_dir=base,
            job_executor=self._execute_cron_job,
            poll_interval=cron_poll_interval,
        )

        self._running = False
        self._worker: threading.Thread | None = None
        self._lock = threading.RLock()
        self._previous_approval_handler: ApprovalHandler | None = None
        self._primary_agent_id: str | None = None

    # ------------------------------------------------------------------
    # BackgroundService
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the daemon: approval gate, scheduler, and worker thread."""
        with self._lock:
            if self._running:
                return
            primary = self.identities.get_or_create_primary()
            self._primary_agent_id = primary.agent_id
            self.identities.set_state(primary.agent_id, LifecycleState.SLEEPING.value)

            # Route every approval decision through the queued gate while running.
            self._previous_approval_handler = get_default_handler()
            set_default_handler(self.approval_handler)

            self._running = True
            self._cron.start()
            self._worker = threading.Thread(target=self._worker_loop, name="always-on-worker", daemon=True)
            self._worker.start()
        logger.info("Always-on daemon started (agent %s)", self._primary_agent_id)

    def stop(self) -> None:
        """Clean shutdown: stop scheduler, drain, persist, restore handler."""
        with self._lock:
            if not self._running:
                return
            self._running = False
        try:
            self._cron.stop()
        finally:
            worker, self._worker = self._worker, None
            if worker is not None:
                worker.join(timeout=15)
            with self._lock:
                if self._primary_agent_id:
                    pending = not self._wake_queue.empty()
                    self.identities.set_state(
                        self._primary_agent_id,
                        LifecycleState.QUEUED.value if pending else LifecycleState.SLEEPING.value,
                    )
                if self._previous_approval_handler is not None:
                    set_default_handler(self._previous_approval_handler)
                    self._previous_approval_handler = None
        logger.info("Always-on daemon stopped cleanly")

    def probe(self) -> ServiceHealth:
        with self._lock:
            running = self._running and self._worker is not None and self._worker.is_alive()
            details: dict[str, Any] = {
                "worker_alive": bool(running),
                "queued_wakes": self._wake_queue.qsize(),
                "pending_approvals": len(self.approval_store.list_pending()),
            }
        return ServiceHealth(
            ok=bool(running),
            state="running" if running else "stopped",
            details=details,
        )

    # ------------------------------------------------------------------
    # Entrypoint
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Run in the foreground until SIGINT/SIGTERM (the daemon entrypoint)."""
        self.start()

        def _handle_signal(signum: int, _frame: Any) -> None:
            logger.info("Received signal %s; shutting down", signum)
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle_signal)
            except (OSError, ValueError) as exc:  # pragma: no cover - platform dependent
                logger.warning("Could not install handler for signal %s: %s", sig, exc)

        worker = self._worker
        try:
            while self._running and worker is not None and worker.is_alive():
                worker.join(timeout=1.0)
        finally:
            self.stop()

    # ------------------------------------------------------------------
    # Wake API
    # ------------------------------------------------------------------

    def wake(self, objective: str, *, source: str = "manual", agent_id: str | None = None) -> WakeRequest:
        """Enqueue a wake request (durable: visible to other processes)."""
        objective = str(objective or "").strip()
        if not objective:
            raise ValueError("wake objective must not be empty")
        with self._lock:
            resolved_agent = agent_id or self._primary_agent_id or self.identities.get_or_create_primary().agent_id
            request = WakeRequest(
                request_id=f"wake-{uuid.uuid4().hex[:12]}",
                objective=objective,
                source=source,
                agent_id=resolved_agent,
                created_at=time.time(),
            )
            self._persist_wake_request(request)
            self._wake_queue.put(request)
            self._seen_wake_ids.add(request.request_id)
            self.identities.set_state(resolved_agent, LifecycleState.QUEUED.value)
        logger.info("Wake %s enqueued from %s", request.request_id, source)
        return request

    def register_webhook(
        self,
        name: str,
        handler: Any = None,
        *,
        description: str = "",
        objective_template: str = "",
    ) -> Any:
        """Register a named webhook that wakes the agent when triggered.

        Pass either a ``handler`` callable or an ``objective_template``
        (``{placeholders}`` filled from the trigger payload). Template
        webhooks are fully durable across restarts.
        """
        if objective_template:
            return self.webhooks.register_template(name, objective_template, description=description)
        if handler is None:
            raise ValueError("register_webhook requires a handler or an objective_template")
        return self.webhooks.register(name, handler, description=description)

    def handle_webhook(self, name: str, payload: dict[str, Any] | None = None) -> WakeRequest:
        """Trigger a webhook: derive the objective and wake the agent."""
        objective = self.webhooks.trigger(name, payload)
        return self.wake(objective, source=f"webhook:{name}")

    # ------------------------------------------------------------------
    # Schedules (cron triggers)
    # ------------------------------------------------------------------

    def add_schedule(
        self,
        name: str,
        cron_expression: str,
        objective: str,
        *,
        enabled: bool = True,
    ) -> CronJob:
        """Add a cron schedule whose firing wakes the agent."""
        return self._cron.add_job(
            name=name,
            cron_expression=cron_expression,
            objective=objective,
            enabled=enabled,
            metadata={"trigger": "always-on-wake"},
        )

    def list_schedules(self) -> list[CronJob]:
        return self._cron.list_jobs()

    def enable_schedule(self, schedule_id: str) -> bool:
        """Enable a schedule by id."""
        return self._cron.enable_job(schedule_id)

    def disable_schedule(self, schedule_id: str) -> bool:
        """Disable a schedule by id."""
        return self._cron.disable_job(schedule_id)

    def remove_schedule(self, schedule_id: str) -> bool:
        """Remove a schedule by id."""
        return self._cron.remove_job(schedule_id)

    def _execute_cron_job(self, job: CronJob) -> CronJobResult:
        """CronScheduler job executor: a fired schedule wakes the agent."""
        try:
            request = self.wake(job.objective, source=f"schedule:{job.name}")
            return CronJobResult(
                job_id=job.id,
                job_name=job.name,
                objective=job.objective,
                success=True,
                output=f"wake {request.request_id} enqueued",
            )
        except Exception as exc:
            logger.error("Schedule '%s' failed to wake agent: %s", job.name, exc)
            return CronJobResult(
                job_id=job.id, job_name=job.name, objective=job.objective, success=False, error=str(exc)
            )

    # ------------------------------------------------------------------
    # Subagent delegation
    # ------------------------------------------------------------------

    def delegate(
        self,
        objective: str,
        goals: list[str],
        *,
        contract: DelegationContract | None = None,
        tools: list[str] | None = None,
    ) -> DelegationResult:
        """Fan out bounded subtasks to child subagents and collect results."""
        if not goals:
            raise ValueError("delegation requires at least one goal")
        contract = contract or DelegationContract()
        pool = self._pool_factory(objective)
        if isinstance(pool, SubagentPool):
            result = pool.spawn_parallel_with_contract(list(goals), contract, tools=tools)
        else:  # pragma: no cover - custom factories return DelegationResult directly
            result = pool
        logger.info(
            "Delegation for '%s': %d/%d subtasks succeeded",
            objective[:60],
            result.successful_count,
            len(result.results),
        )
        return result

    @staticmethod
    def _default_pool_factory(objective: str) -> SubagentPool:
        return SubagentPool(parent_objective=objective)

    # ------------------------------------------------------------------
    # Status (console surface)
    # ------------------------------------------------------------------

    def agents_status(self) -> list[dict[str, Any]]:
        """Agent rows for the console: identity, lifecycle, session, queues."""
        with self._lock:
            agents = self.identities.list()
            pending_approvals = len(self.approval_store.list_pending())
            queued_wakes = self._wake_queue.qsize()
            rows: list[dict[str, Any]] = []
            for identity in agents:
                sessions = self.sessions.list_for_agent(identity.agent_id)
                session = sessions[-1] if sessions else None
                rows.append(
                    {
                        "agent_id": identity.agent_id,
                        "name": identity.name,
                        "lifecycle_state": identity.lifecycle_state,
                        "last_seen": identity.last_seen,
                        "session_id": session.session_id if session else None,
                        "session_messages": len(session.messages) if session else 0,
                        "compaction_count": session.compaction_count if session else 0,
                        "pending_approvals": pending_approvals,
                        "queued_wakes": queued_wakes,
                        "wake_history": [dict(w) for w in session.wake_history[-5:]] if session else [],
                    }
                )
            return rows

    def status(self) -> dict[str, Any]:
        payload = super().status()
        payload["agents"] = self.agents_status()
        payload["webhooks"] = [d.to_dict() for d in self.webhooks.list()]
        payload["schedules"] = [j.to_dict() for j in self.list_schedules()]
        payload["pending_approvals"] = [t.to_dict() for t in self.approval_store.list_pending()]
        payload["compaction"] = self.compactor.stats()
        return payload

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while self._running:
            self._drain_wake_dir()
            try:
                request = self._wake_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._process_wake_request(request)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Wake %s crashed: %s", request.request_id, exc)
            finally:
                self._wake_queue.task_done()

    def _drain_wake_dir(self) -> None:
        """Pick up wake requests persisted by other processes."""
        # Also pick up schedules added/removed via console or CLI while running.
        try:
            self._cron.reload()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Cron reload failed: %s", exc)
        if not self._wake_dir.exists():
            return
        for path in sorted(self._wake_dir.glob("wake-*.json")):
            request_id = path.stem
            with self._lock:
                if request_id in self._seen_wake_ids:
                    continue
                try:
                    request = WakeRequest.from_dict(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    logger.warning("Ignoring unreadable wake request %s: %s", path.name, exc)
                    continue
                self._seen_wake_ids.add(request_id)
                self._wake_queue.put(request)
                self.identities.set_state(request.agent_id, LifecycleState.QUEUED.value)

    def _process_wake_request(self, request: WakeRequest) -> None:
        agent_id = request.agent_id
        self.identities.set_state(agent_id, LifecycleState.AWAKE.value)
        session = self.sessions.get_or_create_for_agent(agent_id)
        self.sessions.set_state(session.session_id, LifecycleState.AWAKE.value)
        # Restore compaction continuity, then run with auto-compaction.
        self.compactor.set_compaction_state(session.compaction_state)

        started = time.time()
        status = WAKE_STATUS_FAILED
        summary = ""
        error = ""
        try:
            self.sessions.append_message(session.session_id, {"role": "user", "content": request.objective})
            result_text = self._executor(request.objective, session)
            summary = str(result_text or "")[:2000]
            self.sessions.append_message(session.session_id, {"role": "assistant", "content": summary})
            # Auto-compact the durable transcript when over budget.
            reloaded = self.sessions.get(session.session_id)
            if reloaded is not None:
                compacted_messages, did_compact = self.compactor.maybe_compact(reloaded.messages)
                if did_compact:
                    reloaded.messages = compacted_messages
                    reloaded.compaction_count = self.compactor.get_compaction_state().get("compression_count", 0)
                    self.sessions.save(reloaded)
            status = WAKE_STATUS_COMPLETED
            logger.info("Wake %s completed in %.1fs", request.request_id, time.time() - started)
        except Exception as exc:
            error = str(exc)
            logger.error("Wake %s failed: %s", request.request_id, exc)

        finished = WakeRequest(
            request_id=request.request_id,
            objective=request.objective,
            source=request.source,
            agent_id=request.agent_id,
            created_at=request.created_at,
            status=status,
            result_summary=summary,
            error=error,
            finished_at=time.time(),
        )
        self.sessions.record_wake(
            session.session_id,
            finished.to_dict(),
            compaction_state=self.compactor.get_compaction_state(),
            compaction_count=self.compactor.get_compaction_state().get("compression_count", 0),
        )
        self.sessions.set_state(session.session_id, LifecycleState.COMPLETED.value)
        self._archive_wake_file(request.request_id)
        # Settle the agent: queued when more work waits, else sleeping.
        with self._lock:
            more_pending = not self._wake_queue.empty()
        self.identities.set_state(
            agent_id, LifecycleState.QUEUED.value if more_pending else LifecycleState.SLEEPING.value
        )
        self.identities.touch(agent_id)

    # ------------------------------------------------------------------
    # Wake queue persistence
    # ------------------------------------------------------------------

    def _persist_wake_request(self, request: WakeRequest) -> None:
        self._wake_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._wake_dir / f".{request.request_id}.tmp"
        tmp.write_text(json.dumps(request.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._wake_dir / f"{request.request_id}.json")

    def _archive_wake_file(self, request_id: str) -> None:
        src = self._wake_dir / f"{request_id}.json"
        if not src.exists():
            return
        self._wake_done_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(self._wake_done_dir / f"{request_id}.json"))
        except OSError as exc:
            logger.warning("Could not archive wake file %s: %s", request_id, exc)
        # Prune old done files.
        done_files = sorted(self._wake_done_dir.glob("wake-*.json"), key=lambda p: p.stat().st_mtime)
        for stale in done_files[:-MAX_WAKE_HISTORY_FILES]:
            with contextlib.suppress(OSError):
                stale.unlink()

    # ------------------------------------------------------------------
    # Default executor (production path: real agent loop, approval-gated)
    # ------------------------------------------------------------------

    def _default_executor(self, objective: str, session: DurableSession) -> str:
        from ..agent_loop import AIAgent

        agent = AIAgent(
            system_prompt=(
                "You are an always-on Ghost Chimera agent. Complete the wake objective, "
                "then summarize what you did. High-stakes tool calls require approval "
                "and will pause until an operator decides."
            ),
            config=self.config,
            autonomy_profile=self.profile,
        )
        return agent.run(objective)


__all__ = [
    "AlwaysOnDaemon",
    "LifecycleState",
    "WakeRequest",
    "WAKE_STATUS_QUEUED",
    "WAKE_STATUS_RUNNING",
    "WAKE_STATUS_COMPLETED",
    "WAKE_STATUS_FAILED",
]
