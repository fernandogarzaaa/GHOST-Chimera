"""Task IR for Chimera Pilot.

The task IR is the neutral contract between natural-language objectives and
runtime backends.  It intentionally contains no Origin-specific names or
private implementation assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class TaskKind(str, Enum):
    """Supported Chimera Pilot task classes."""

    REASONING = "reasoning"
    CODE_EDIT = "code_edit"
    TEST_RUN = "test_run"
    WEB_RESEARCH = "web_research"
    FILE_ANALYSIS = "file_analysis"
    RAG_QUERY = "rag_query"
    TOOL_CALL = "tool_call"
    PYTHON = "python"
    QUANTUM_SIM = "quantum_sim"


def new_task_id(prefix: str = "task") -> str:
    """Return a compact unique task id."""

    return f"{prefix}-{uuid4().hex[:12]}"


@dataclass(frozen=True)
class TaskSpec:
    """A normalized unit of work for the Chimera Pilot scheduler."""

    id: str
    kind: TaskKind
    objective: str
    inputs: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    privacy_level: str = "normal"
    max_cost_usd: float | None = None
    max_latency_ms: int | None = None
    requires_network: bool = False
    requires_gpu: bool = False

    @classmethod
    def create(
        cls,
        *,
        kind: TaskKind,
        objective: str,
        inputs: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        priority: int = 5,
        privacy_level: str = "normal",
        max_cost_usd: float | None = None,
        max_latency_ms: int | None = None,
        requires_network: bool = False,
        requires_gpu: bool = False,
    ) -> "TaskSpec":
        return cls(
            id=new_task_id(kind.value),
            kind=kind,
            objective=objective,
            inputs=dict(inputs or {}),
            constraints=dict(constraints or {}),
            priority=priority,
            privacy_level=privacy_level,
            max_cost_usd=max_cost_usd,
            max_latency_ms=max_latency_ms,
            requires_network=requires_network,
            requires_gpu=requires_gpu,
        )
