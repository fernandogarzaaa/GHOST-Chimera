"""Chimera Pilot: resource orchestration layer for Ghost Chimera.

Chimera Pilot generalizes quantum-OS style scheduling into a practical
AI/tool/runtime control plane: task IR, backend registry, health calibration,
scoring scheduler, fallback execution, verification, and telemetry.
"""

from .agent_pool import BatchAgent, BatchResult, BatchSummary, ParallelAgent
from .backend_registry import BackendRegistry, default, discover_builtin_backends
from .calibration_async import calibrate_backends_parallel
from .claim_extractor import ClaimExtractor
from .compiler import RuleBasedTaskCompiler
from .executor import ChimeraPilotExecutor, PilotExecution
from .executor_async import AsyncChimeraPilotExecutor
from .executor_parallel import ParallelExecutionResult, execute_tasks_parallel
from .hooks import HookName, HookRegistry
from .kernel import ChimeraPilotKernel
from .plugin_manifest import PluginLoader, PluginManifest, get_loader
from .policy import PilotPolicy
from .resource_registry import ResourceRegistry
from .result_envelope import ResultEnvelope, merge_envelopes
from .scheduler import ChimeraScheduler, ScheduleDecision
from .semantic_verifier import SemanticVerifier
from .service_registry import BackgroundService, ServiceHealth, ServiceRegistry, get_registry as get_service_registry
from .task_ir import TaskKind, TaskSpec
from .tool_middleware import ToolMiddlewareChain, ToolResultMiddleware, get_default_chain

__all__ = [
    "AsyncChimeraPilotExecutor",
    "BackendRegistry",
    "BackgroundService",
    "BatchAgent",
    "BatchResult",
    "BatchSummary",
    "ChimeraPilotExecutor",
    "ChimeraPilotKernel",
    "ChimeraScheduler",
    "ClaimExtractor",
    "HookName",
    "HookRegistry",
    "PilotExecution",
    "PilotPolicy",
    "ParallelAgent",
    "ParallelExecutionResult",
    "PluginLoader",
    "PluginManifest",
    "ResourceRegistry",
    "ResultEnvelope",
    "RuleBasedTaskCompiler",
    "ScheduleDecision",
    "SemanticVerifier",
    "ServiceHealth",
    "ServiceRegistry",
    "TaskKind",
    "TaskSpec",
    "ToolMiddlewareChain",
    "ToolResultMiddleware",
    "merge_envelopes",
    "calibrate_backends_parallel",
    "default",
    "discover_builtin_backends",
    "execute_tasks_parallel",
    "get_default_chain",
    "get_loader",
    "get_service_registry",
]
