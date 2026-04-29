"""Chimera Pilot: resource orchestration layer for Ghost Chimera.

Chimera Pilot generalizes quantum-OS style scheduling into a practical
AI/tool/runtime control plane: task IR, backend registry, health calibration,
scoring scheduler, fallback execution, verification, and telemetry.
"""

from .compiler import RuleBasedTaskCompiler
from .executor import ChimeraPilotExecutor, PilotExecution
from .kernel import ChimeraPilotKernel
from .policy import PilotPolicy
from .resource_registry import ResourceRegistry
from .scheduler import ChimeraScheduler, ScheduleDecision
from .task_ir import TaskKind, TaskSpec

__all__ = [
    "ChimeraPilotExecutor",
    "ChimeraPilotKernel",
    "ChimeraScheduler",
    "PilotExecution",
    "PilotPolicy",
    "ResourceRegistry",
    "RuleBasedTaskCompiler",
    "ScheduleDecision",
    "TaskKind",
    "TaskSpec",
]
