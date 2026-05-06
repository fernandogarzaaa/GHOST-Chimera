"""High-level Chimera Pilot kernel."""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from ..memory_layer.store import MemoryStore
from .backends.cwr import CWRBackend
from .backends.desktop_runtime import DesktopRuntimeBackend
from .backends.deterministic import DeterministicBackend
from .backends.llamacpp import LlamaCppBackend
from .backends.pyqpanda3_backend import PyQPanda3Backend
from .backends.python_runtime import PythonRuntimeBackend
from .calibration import CalibrationStore, ChimeraCalibrator
from .compiler import RuleBasedTaskCompiler
from .executor import ChimeraPilotExecutor, PilotExecution
from .hooks import HookName, HookRegistry
from .policy import PilotPolicy
from .resource_registry import ResourceRegistry
from .scheduler import ChimeraScheduler
from .task_ir import TaskKind, TaskSpec
from .telemetry import InMemoryTelemetryStore

logger = get_logger("kernel")


class ChimeraPilotKernel:
    """Control-plane facade for compiling, scheduling, and executing tasks."""

    def __init__(
        self,
        *,
        registry: ResourceRegistry | None = None,
        compiler: RuleBasedTaskCompiler | None = None,
        policy: PilotPolicy | None = None,
        telemetry: InMemoryTelemetryStore | None = None,
        calibration_store: CalibrationStore | None = None,
        policy_registry: Any | None = None,
        memory_store: MemoryStore | None = None,
        hooks: HookRegistry | None = None,
    ) -> None:
        self.registry = registry or ResourceRegistry()
        self.compiler = compiler or RuleBasedTaskCompiler()
        self.policy = policy or PilotPolicy()
        self.telemetry = telemetry or InMemoryTelemetryStore()
        self.calibration_store = calibration_store or CalibrationStore()
        self._policy_registry = policy_registry
        self.memory_store = memory_store
        self.hooks = hooks or HookRegistry()

    @classmethod
    def default(
        cls,
        *,
        include_deterministic_backend: bool = False,
        include_quantum_backend: bool = False,
        cwd: str | None = None,
        allow_python_execution: bool = False,
        allow_network: bool = False,
        allow_desktop_control: bool = False,
        enable_desktop_backend: bool = False,
        enable_live_desktop: bool = False,
        desktop_kill_switch_path: str | None = None,
        desktop_action_log_path: str | None = None,
        desktop_max_live_actions: int | None = DesktopRuntimeBackend.DEFAULT_MAX_LIVE_ACTIONS,
        desktop_max_session_seconds: float | None = DesktopRuntimeBackend.DEFAULT_MAX_SESSION_SECONDS,
        ghost_mode: str = "whisper",
        memory_store: MemoryStore | None = None,
        local_model_path: str | None = None,
        local_model_profile: str = "tiny",
        local_model_gpu_layers: int = 0,
        hooks: HookRegistry | None = None,
    ) -> ChimeraPilotKernel:
        policy = PilotPolicy(
            allow_python_execution=allow_python_execution,
            allow_network=allow_network,
            allow_desktop_control=allow_desktop_control,
            ghost_mode=ghost_mode,
        )
        kernel = cls(policy=policy, memory_store=memory_store, hooks=hooks)
        kernel.registry.register(PythonRuntimeBackend(cwd=cwd, allowed_roots=[cwd] if cwd else None))
        kernel.registry.register(CWRBackend(store=memory_store))
        if enable_desktop_backend:
            kernel.registry.register(
                DesktopRuntimeBackend(
                    dry_run=not enable_live_desktop,
                    kill_switch_path=desktop_kill_switch_path,
                    action_log_path=desktop_action_log_path,
                    max_live_actions=desktop_max_live_actions,
                    max_session_seconds=desktop_max_session_seconds,
                )
            )
        if local_model_path:
            kernel.registry.register(
                LlamaCppBackend(
                    model_path=local_model_path,
                    profile_name=local_model_profile,
                    n_gpu_layers=local_model_gpu_layers,
                )
            )
        if include_quantum_backend and PyQPanda3Backend.is_available():
            kernel.registry.register(PyQPanda3Backend())
        if include_deterministic_backend:
            kernel.registry.register(DeterministicBackend())
        return kernel

    def register_backend(self, backend: Any) -> None:
        self.registry.register(backend)

    def compile(self, objective: str) -> list[TaskSpec]:
        logger.info("Compiling objective: %s", objective[:50])
        tasks = self.compiler.compile(objective)
        self.hooks.fire(HookName.TASK_COMPILE, objective=objective, tasks=tasks)
        return tasks

    def execute_task(self, task: TaskSpec) -> PilotExecution:
        from ..safety_layer.material_policy import MaterialRegistry
        registry = self._policy_registry or MaterialRegistry()
        scheduler = ChimeraScheduler(self.registry.list(), policy_registry=registry)
        executor = ChimeraPilotExecutor(
            scheduler,
            policy=self.policy,
            telemetry=self.telemetry,
            outcome_store=self.memory_store,
            hooks=self.hooks,
        )
        self.hooks.fire(HookName.TASK_EXECUTE_PRE, task=task)
        execution = executor.execute(task)
        self.hooks.fire(HookName.TASK_EXECUTE_POST, task=task, execution=execution)
        return execution

    def run(self, objective: str) -> list[PilotExecution]:
        self.hooks.fire(HookName.SESSION_START, objective=objective)
        tasks = self.compile(objective)
        logger.info("Running pilot with %d tasks", len(tasks))
        results = [self.execute_task(task) for task in tasks]
        self.hooks.fire(HookName.SESSION_END, objective=objective, results=results)
        return results

    def calibrate(self) -> dict[str, Any]:
        calibrator = ChimeraCalibrator(self.registry.list(), self.calibration_store)
        health = calibrator.run_once()
        return {
            "health": {
                backend_id: {
                    "available": item.available,
                    "reliability": item.reliability,
                    "latency_ms": item.latency_ms,
                    "estimated_cost_usd": item.estimated_cost_usd,
                    "last_error": item.last_error,
                }
                for backend_id, item in health.items()
            },
            "summary": self.calibration_store.summary(),
        }

    def status(self) -> dict[str, Any]:
        logger.info("Status check: %d backends registered", len(self.registry.list()))
        backends = []
        for backend in self.registry.list():
            health = backend.probe()
            backends.append(
                {
                    "id": backend.id,
                    "name": backend.name,
                    "available": health.available,
                    "reliability": health.reliability,
                    "latency_ms": health.latency_ms,
                    "estimated_cost_usd": health.estimated_cost_usd,
                    "last_error": health.last_error,
                    "kinds": sorted(kind.value for kind in backend.capabilities.kinds),
                    "offline": backend.capabilities.supports_offline,
                    "network": backend.capabilities.supports_network,
                    "gpu": backend.capabilities.supports_gpu,
                    "metadata": dict(backend.capabilities.metadata),
                }
            )
        return {
            "backend_count": len(backends),
            "backends": backends,
            "policy": self.policy.to_dict(),
            "telemetry": self.telemetry.summary(),
        }


__all__ = ["ChimeraPilotKernel", "TaskKind", "TaskSpec"]
