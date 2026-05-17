"""High-level Chimera Pilot kernel."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ..logging_config import get_logger
from ..memory_layer.store import MemoryStore
from ..safety_layer.production import ProductionGuardrails
from .autonomy import AutonomyProfile, get_autonomy_profile, get_autonomy_profile_from_env
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

if TYPE_CHECKING:
    from ..cognition_layer.workspace_state import OperatorWorkspaceStore

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
        autonomy_profile: AutonomyProfile | None = None,
        desktop_confirmation_token: str | None = None,
        workspace_store: OperatorWorkspaceStore | None = None,
        enable_personal_context: bool = False,
        personal_context_limit: int = 5,
        enable_minimind_personal_context: bool = True,
    ) -> None:
        self.registry = registry or ResourceRegistry()
        self.compiler = compiler or RuleBasedTaskCompiler()
        self.policy = policy or PilotPolicy()
        self.telemetry = telemetry or InMemoryTelemetryStore()
        self.calibration_store = calibration_store or CalibrationStore()
        self._policy_registry = policy_registry
        self.memory_store = memory_store
        self.hooks = hooks or HookRegistry()
        self.autonomy_profile = autonomy_profile or self.policy.autonomy_profile
        self.desktop_confirmation_token = desktop_confirmation_token
        self.workspace_store = workspace_store
        self.enable_personal_context = enable_personal_context
        self.personal_context_limit = personal_context_limit
        self.enable_minimind_personal_context = enable_minimind_personal_context

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
        desktop_action_classes: tuple[str, ...] | list[str] | None = None,
        desktop_allowed_apps: tuple[str, ...] | list[str] | None = None,
        desktop_denied_apps: tuple[str, ...] | list[str] | None = None,
        desktop_allowed_windows: tuple[str, ...] | list[str] | None = None,
        desktop_denied_windows: tuple[str, ...] | list[str] | None = None,
        desktop_confirmation_token: str | None = None,
        enable_desktop_backend: bool = False,
        enable_live_desktop: bool = False,
        desktop_kill_switch_path: str | None = None,
        desktop_action_log_path: str | None = None,
        desktop_screenshot_dir: str | None = None,
        desktop_max_live_actions: int | None = DesktopRuntimeBackend.DEFAULT_MAX_LIVE_ACTIONS,
        desktop_max_session_seconds: float | None = DesktopRuntimeBackend.DEFAULT_MAX_SESSION_SECONDS,
        ghost_mode: str = "whisper",
        memory_store: MemoryStore | None = None,
        local_model_path: str | None = None,
        local_model_profile: str = "tiny",
        local_model_gpu_layers: int = 0,
        local_runtime_specialization: bool = True,
        local_runtime_specialization_cache_dir: str | None = None,
        hooks: HookRegistry | None = None,
        autonomy_level: str | None = None,
        enable_personal_context: bool = False,
        personal_context_limit: int = 5,
        enable_minimind_personal_context: bool = True,
    ) -> ChimeraPilotKernel:
        autonomy_profile = get_autonomy_profile(autonomy_level) if autonomy_level else get_autonomy_profile_from_env()
        local_model_profile = local_model_profile or autonomy_profile.local_model_profile
        policy = PilotPolicy(
            allow_python_execution=allow_python_execution,
            allow_network=allow_network,
            allow_desktop_control=allow_desktop_control,
            ghost_mode=ghost_mode,
            allowed_desktop_action_classes=tuple(desktop_action_classes)
            if desktop_action_classes
            else ("read_only", "mutating"),
            allowed_desktop_apps=tuple(desktop_allowed_apps or ()),
            denied_desktop_apps=tuple(desktop_denied_apps or ()),
            allowed_desktop_windows=tuple(desktop_allowed_windows or ()),
            denied_desktop_windows=tuple(desktop_denied_windows or ()),
            production_guardrails=ProductionGuardrails.from_env(),
            default_max_cost_usd=autonomy_profile.default_max_cost_usd,
            autonomy_profile=autonomy_profile,
        )
        kernel = cls(
            policy=policy,
            memory_store=memory_store,
            hooks=hooks,
            autonomy_profile=autonomy_profile,
            desktop_confirmation_token=desktop_confirmation_token,
            enable_personal_context=enable_personal_context,
            personal_context_limit=personal_context_limit,
            enable_minimind_personal_context=enable_minimind_personal_context,
        )
        kernel.registry.register(PythonRuntimeBackend(cwd=cwd, allowed_roots=[cwd] if cwd else None))
        kernel.registry.register(CWRBackend(store=memory_store))
        if enable_desktop_backend:
            kernel.registry.register(
                DesktopRuntimeBackend(
                    dry_run=not enable_live_desktop,
                    kill_switch_path=desktop_kill_switch_path,
                    action_log_path=desktop_action_log_path,
                    screenshot_dir=desktop_screenshot_dir,
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
                    runtime_specialization=local_runtime_specialization,
                    specialization_cache_dir=local_runtime_specialization_cache_dir,
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

        if self.workspace_store is not None:
            context_items = self.workspace_store.workspace_context_for_objective(objective, limit=5)
            if context_items:
                tasks = [
                    replace(
                        task,
                        constraints={
                            **task.constraints,
                            "workspace_context": context_items,
                        },
                    )
                    for task in tasks
                ]

        personal_context_text = ""
        personal_sources: tuple[str, ...] = ()
        personal_detail = ""
        if self.enable_personal_context and self.memory_store is not None:
            try:
                from ..personalization.context_provider import PersonalContextProvider

                provider = PersonalContextProvider(
                    memory_store=self.memory_store,
                    enable_minimind=self.enable_minimind_personal_context,
                )
                result = provider.context_for_objective(objective, limit=self.personal_context_limit)
                personal_context_text = result.context
                personal_sources = result.sources
                personal_detail = result.detail
            except Exception as exc:  # noqa: BLE001
                logger.warning("Personal context provider failed: %s", exc)

        if personal_context_text:
            _SYSTEM_PROMPT_KINDS = {TaskKind.REASONING, TaskKind.LONG_CONTEXT_DOC, TaskKind.CODE_EDIT}
            _QUERY_CONTEXT_KINDS = {
                TaskKind.WEB_RESEARCH,
                TaskKind.FILE_ANALYSIS,
                TaskKind.RAG_QUERY,
                TaskKind.ANALYTICS_QUERY,
            }
            updated: list[TaskSpec] = []
            for task in tasks:
                merged_constraints = {
                    **task.constraints,
                    "personal_context": personal_context_text,
                    "personal_context_sources": list(personal_sources),
                    "personal_context_detail": personal_detail,
                }
                merged_inputs = dict(task.inputs)
                ctx_prefix = f"Personal context (local memory):\n{personal_context_text}".strip()
                if task.kind in _SYSTEM_PROMPT_KINDS:
                    existing_system = str(merged_inputs.get("system") or "").strip()
                    merged_inputs["system"] = (
                        ctx_prefix + ("\n\n" + existing_system if existing_system else "")
                    ).strip()
                elif task.kind in _QUERY_CONTEXT_KINDS:
                    # Inject as a separate "context" field; backends that call
                    # LLMs can pick this up without modifying the query itself.
                    merged_inputs["context"] = personal_context_text
                updated.append(replace(task, inputs=merged_inputs, constraints=merged_constraints))
            tasks = updated

        self.hooks.fire(HookName.TASK_COMPILE, objective=objective, tasks=tasks)
        return tasks

    def execute_task(self, task: TaskSpec) -> PilotExecution:
        from ..safety_layer.material_policy import MaterialRegistry

        if task.kind == TaskKind.DESKTOP_CONTROL and self.desktop_confirmation_token:
            task = replace(
                task,
                constraints={
                    **task.constraints,
                    "confirmation_token": self.desktop_confirmation_token,
                },
            )
        registry = self._policy_registry or MaterialRegistry()
        scheduler = ChimeraScheduler(
            self.registry.list(),
            policy_registry=registry,
            autonomy_profile=self.autonomy_profile,
        )
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
        if (
            self.autonomy_profile.allow_parallel_execution
            and len(tasks) > 1
            and self.autonomy_profile.max_parallel_tasks > 1
        ):
            from .executor_parallel import execute_tasks_parallel

            scheduler = ChimeraScheduler(self.registry.list(), autonomy_profile=self.autonomy_profile)
            parallel = execute_tasks_parallel(
                tasks,
                scheduler,
                max_workers=self.autonomy_profile.max_parallel_tasks,
                policy=self.policy,
                telemetry=self.telemetry,
            )
            results = parallel.results
        else:
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
            "autonomy": self.autonomy_profile.to_dict(),
            "telemetry": self.telemetry.summary(),
        }


__all__ = ["ChimeraPilotKernel", "TaskKind", "TaskSpec"]
