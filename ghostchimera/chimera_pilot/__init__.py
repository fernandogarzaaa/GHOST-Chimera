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
from .kernel import ChimeraPilotKernel
from .policy import PilotPolicy
from .resource_registry import ResourceRegistry
from .scheduler import ChimeraScheduler, ScheduleDecision
from .semantic_verifier import SemanticVerifier
from .result_envelope import ResultEnvelope, merge_envelopes
from .task_ir import TaskKind, TaskSpec

__all__ = [
    "AsyncChimeraPilotExecutor",
    "BackendRegistry",
    "BatchAgent",
    "BatchResult",
    "BatchSummary",
    "ChimeraPilotExecutor",
    "ChimeraPilotKernel",
    "ChimeraScheduler",
    "ClaimExtractor",
    "PilotExecution",
    "PilotPolicy",
    "ParallelAgent",
    "ParallelExecutionResult",
    "ResourceRegistry",
    "ResultEnvelope",
    "RuleBasedTaskCompiler",
    "ScheduleDecision",
    "SemanticVerifier",
    "TaskKind",
    "TaskSpec",
    "merge_envelopes",
    "calibrate_backends_parallel",
    "discover_builtin_backends",
    "execute_tasks_parallel",
]
