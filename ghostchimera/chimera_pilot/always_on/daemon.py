"""Always-on daemon for Ghost Chimera.

Supervises :class:`GatewayServer` and :class:`CronScheduler` through the
:class:`ServiceRegistry`, exposing:

- ``POST /hooks/<name>`` inbound webhook route (shared-secret auth,
  payload normalization via :mod:`connectors.webhooks`, async agent dispatch)
- Cron jobs that execute real tool-using agent runs, with results recorded
  in the :class:`TrustRuntimeStore`
- Persistent agent identity (``identity_store`` when available, stable
  fallback otherwise) and durable session snapshots, so a restart loses
  nothing
- PID file + graceful SIGTERM/SIGINT shutdown with no orphaned threads

The daemon never blocks the caller: :meth:`Daemon.start` is non-blocking,
:meth:`Daemon.run_forever` blocks until a termination signal arrives.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import signal
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...config import GhostChimeraConfig
from ...connectors.webhooks import normalize_webhook
from ...logging_config import get_logger
from ...trust_runtime import TrustRuntimeStore
from ..agent_loop import AIAgent
from ..cron_scheduler import CronJob, CronJobResult, CronScheduler
from ..gateway_server import GatewayServer, HttpResponse
from ..service_registry import BackgroundService, ServiceHealth, ServiceRegistry

logger = get_logger("daemon")

PID_FILE = "daemon.pid"
HOOK_SECRET_ENV = "GHOSTCHIMERA_HOOK_SECRET"
DEFAULT_MAX_WORKERS = 4


# ---------------------------------------------------------------------------
# Identity (tolerant of identity_store not being merged yet)
# ---------------------------------------------------------------------------


def load_daemon_identity(state_dir: str | Path) -> dict[str, Any]:
    """Load the persistent agent identity for the daemon.

    Uses ``ghostchimera.identity_store.IdentityStore`` when importable
    (PR #107); otherwise falls back to a stable local identity so the
    daemon still runs on main before that PR merges.
    """
    try:
        from ...identity_store import IdentityStore
    except ImportError:
        logger.warning("identity_store not available; using ephemeral fallback identity")
        return {
            "id": "ghost-local",
            "name": "ghost-chimera",
            "capabilities": [],
            "owner": "",
            "ephemeral": True,
        }
    identity = IdentityStore(state_dir).load_or_create()
    return identity.to_dict()


# ---------------------------------------------------------------------------
# Hook definitions
# ---------------------------------------------------------------------------


@dataclass
class HookDefinition:
    """A named inbound webhook that triggers an agent task."""

    name: str
    source: str = "generic"  # gmail | slack | zendesk | generic
    objective_template: str = "Handle inbound {source} event: {summary}"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------


class Daemon(BackgroundService):
    """Always-on supervisor for the Ghost Chimera ambient runtime."""

    service_id = "ghost_daemon"
    service_name = "Ghost Daemon"
    service_description = "Always-on supervisor: gateway + cron + webhooks"

    def __init__(
        self,
        state_dir: str | Path | None = None,
        config: GhostChimeraConfig | None = None,
        hook_secret: str | None = None,
        poll_interval: int = 60,
        max_workers: int = DEFAULT_MAX_WORKERS,
        tool_provider: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.config = config or GhostChimeraConfig.from_env()
        self.state_dir = Path(state_dir or self.config.state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.hook_secret = hook_secret or os.environ.get(HOOK_SECRET_ENV, "")
        self.poll_interval = poll_interval
        self.tool_provider = tool_provider

        self.identity = load_daemon_identity(self.state_dir)
        self.store = TrustRuntimeStore(self.state_dir)

        self.gateway = GatewayServer(config=self.config)
        self.scheduler = CronScheduler(
            state_dir=self.state_dir,
            poll_interval=poll_interval,
            config=self.config,
            job_executor=self._execute_cron_job,
        )
        self.registry = ServiceRegistry()
        self.registry.register(self.gateway)
        self.registry.register(self.scheduler)

        self._hooks: dict[str, HookDefinition] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="daemon-agent",
        )
        self._shutdown = threading.Event()
        self._started = False
        self._lock = threading.Lock()

        self._register_hook_route()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def pid_file(self) -> Path:
        return self.state_dir / PID_FILE

    def start(self) -> None:
        """Start all supervised services. Non-blocking."""
        with self._lock:
            if self._started:
                return
            self._write_pid_file()
            results = self.registry.start_all()
            failed = [sid for sid, ok in results.items() if not ok]
            if failed:
                raise RuntimeError(f"daemon failed to start services: {failed}")
            self._started = True
        logger.info(
            "Ghost daemon started (identity=%s, pid=%d)",
            self.identity.get("id"),
            os.getpid(),
        )

    def stop(self) -> None:
        """Stop all supervised services, shut down workers, remove PID file."""
        with self._lock:
            if not self._started:
                return
            self._started = False
        self.registry.stop_all()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._remove_pid_file()
        self._shutdown.set()
        logger.info("Ghost daemon stopped")

    def run_forever(self) -> None:
        """Start and block until SIGTERM/SIGINT arrives."""
        self.start()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle_signal)
        logger.info("Ghost daemon running; waiting for signal")
        self._shutdown.wait()

    def probe(self) -> ServiceHealth:
        health = self.registry.probe_all()
        ok = all(h.ok for h in health.values()) if health else False
        return ServiceHealth(
            ok=ok and self._started,
            state="running" if self._started else "stopped",
            details={
                "identity_id": self.identity.get("id"),
                "services": {sid: h.to_dict() for sid, h in health.items()},
                "hooks": sorted(self._hooks),
                "pid_file": str(self.pid_file),
            },
        )

    def status(self) -> dict[str, Any]:
        snap = super().status()
        snap["pid"] = os.getpid() if self._started else None
        snap["jobs"] = [j.to_dict() for j in self.scheduler.list_jobs()]
        return snap

    # ------------------------------------------------------------------
    # PID file
    # ------------------------------------------------------------------

    def _write_pid_file(self) -> None:
        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def _remove_pid_file(self) -> None:
        try:
            self.pid_file.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove PID file %s", self.pid_file)

    @classmethod
    def read_pid(cls, state_dir: str | Path) -> int | None:
        try:
            return int((Path(state_dir) / PID_FILE).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _handle_signal(self, signum: int, _frame: Any) -> None:
        logger.info("Ghost daemon received signal %d; shutting down", signum)
        self.stop()

    # ------------------------------------------------------------------
    # Webhook ingress
    # ------------------------------------------------------------------

    def register_hook(self, hook: HookDefinition) -> None:
        """Register a named inbound webhook."""
        self._hooks[hook.name] = hook
        logger.info("Registered hook '%s' (source=%s)", hook.name, hook.source)

    def _register_hook_route(self) -> None:
        self.gateway.register_route(
            "/hooks/",
            self._handle_hook,
            method="POST",
            auth="open",  # own shared-secret check inside the handler
            prefix=True,
            description="Inbound webhook dispatch to agent tasks",
        )

    def _handle_hook(self, ctx: dict[str, Any]) -> HttpResponse | dict[str, Any]:
        path = str(ctx.get("path", ""))
        name = path[len("/hooks/") :].strip("/")
        hook = self._hooks.get(name)
        if hook is None or not hook.enabled:
            return self._http_error(404, f"unknown hook: {name}")

        if not self._check_hook_secret(ctx):
            return self._http_error(403, "invalid hook secret")

        try:
            payload = json.loads(ctx.get("body") or "{}")
        except json.JSONDecodeError:
            return self._http_error(400, "invalid JSON body")
        if not isinstance(payload, dict):
            return self._http_error(400, "JSON body must be an object")

        delivery_id = str(ctx.get("headers", {}).get("x-delivery-id", uuid.uuid4().hex[:12]))
        event = normalize_webhook(hook.source, delivery_id, name, payload)
        summary = self._event_summary(event, payload)
        objective = hook.objective_template.format(source=hook.source, summary=summary, name=name)

        receipt_id = f"hook-{uuid.uuid4().hex[:12]}"
        self._executor.submit(self._run_hook_task, receipt_id, hook, objective, event, payload)
        return {"ok": True, "receipt_id": receipt_id, "hook": name, "objective": objective}

    @staticmethod
    def _http_error(status: int, message: str) -> HttpResponse:
        return HttpResponse(
            body=json.dumps({"ok": False, "error": message}),
            status=status,
            content_type="application/json",
        )

    def _check_hook_secret(self, ctx: dict[str, Any]) -> bool:
        if not self.hook_secret:
            return False
        headers = ctx.get("headers", {}) or {}
        query = ctx.get("query", {}) or {}
        presented = str(headers.get("x-hook-secret", "") or query.get("secret", ""))
        if not presented:
            return False
        return hmac.compare_digest(presented.encode(), self.hook_secret.encode())

    @staticmethod
    def _event_summary(event: Any, payload: dict[str, Any]) -> str:
        if event is not None:
            data = getattr(event, "payload", None) or {}
            for key in ("subject", "text", "ticket_id", "message_id"):
                value = data.get(key)
                if value:
                    return str(value)[:200]
            return str(getattr(event, "event_type", "event"))
        return str(payload.get("subject") or payload.get("text") or "payload")[:200]

    def _run_hook_task(
        self,
        receipt_id: str,
        hook: HookDefinition,
        objective: str,
        event: Any,
        payload: dict[str, Any],
    ) -> None:
        try:
            self._run_agent_task(
                objective,
                source=f"webhook:{hook.name}",
                metadata={
                    "receipt_id": receipt_id,
                    "hook": hook.name,
                    "hook_source": hook.source,
                    "event_id": getattr(event, "event_id", ""),
                },
            )
            logger.info("Hook '%s' task %s completed", hook.name, receipt_id)
        except Exception as exc:
            logger.error("Hook '%s' task %s failed: %s", hook.name, receipt_id, exc)

    # ------------------------------------------------------------------
    # Cron execution
    # ------------------------------------------------------------------

    def _execute_cron_job(self, job: CronJob) -> CronJobResult:
        """Run a cron job as a real tool-using agent turn; record the result."""
        try:
            output = self._run_agent_task(
                job.objective,
                source=f"cron:{job.name}",
                metadata={"job_id": job.id, "job_name": job.name, "task_kind": job.task_kind.value},
            )
            return CronJobResult(
                job_id=job.id,
                job_name=job.name,
                objective=job.objective,
                success=True,
                output=output[:3000],
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

    # ------------------------------------------------------------------
    # Agent task execution (shared by hooks and cron)
    # ------------------------------------------------------------------

    def _run_agent_task(
        self,
        objective: str,
        *,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Execute one agent turn with tools; record it in the trust store."""
        run = self.store.create_run(
            objective,
            source=source,
            agent_name=str(self.identity.get("name", "ghost-chimera")),
            metadata=metadata or {},
        )
        run_id = run["run_id"]
        tools = self.tool_provider() if self.tool_provider is not None else []
        agent = AIAgent(
            system_prompt=f"You are {self.identity.get('name', 'ghost-chimera')}, an ambient agent. Identity id: {self.identity.get('id')}.",
            config=self.config,
        )
        try:
            result = agent.run(objective, tools)
        except Exception as exc:
            self.store.record_step(
                run_id,
                step_type="agent_run",
                status="error",
                input_payload={"objective": objective},
                output_payload={"error": str(exc)},
            )
            raise
        self.store.record_step(
            run_id,
            step_type="agent_run",
            status="ok",
            input_payload={"objective": objective},
            output_payload={"result": str(result)[:2000]},
        )
        self._persist_session_snapshot(source, objective, str(result))
        return str(result)

    def _persist_session_snapshot(self, source: str, objective: str, result: str) -> None:
        """Best-effort durable session snapshot (uses save_session when available)."""
        save = getattr(self.store, "save_session", None)
        if not callable(save):
            return
        try:
            session_id = f"daemon-{hashlib.sha256(source.encode()).hexdigest()[:12]}"
            save(
                {
                    "session_id": session_id,
                    "source": source,
                    "objective": objective,
                    "result": result[:2000],
                    "identity_id": self.identity.get("id"),
                    "messages": [
                        {"role": "user", "content": objective},
                        {"role": "assistant", "content": result[:2000]},
                    ],
                }
            )
        except Exception:
            logger.exception("Failed to persist daemon session snapshot")


__all__ = [
    "Daemon",
    "HookDefinition",
    "HOOK_SECRET_ENV",
    "PID_FILE",
    "DEFAULT_MAX_WORKERS",
    "load_daemon_identity",
]
