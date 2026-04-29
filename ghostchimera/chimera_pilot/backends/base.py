"""Backend contracts for Chimera Pilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..task_ir import TaskKind, TaskSpec


@dataclass(frozen=True)
class BackendCapabilities:
    """Static capabilities advertised by a backend."""

    kinds: set[TaskKind]
    supports_offline: bool
    supports_streaming: bool = False
    supports_gpu: bool = False
    supports_network: bool = False
    max_context_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def supports(self, task: TaskSpec) -> bool:
        if task.kind not in self.kinds:
            return False
        if task.requires_gpu and not self.supports_gpu:
            return False
        if task.requires_network and not self.supports_network:
            return False
        required_context = task.constraints.get("required_context_tokens")
        if required_context is not None and self.max_context_tokens is not None:
            try:
                if int(required_context) > self.max_context_tokens:
                    return False
            except (TypeError, ValueError):
                return False
        return True


@dataclass(frozen=True)
class BackendHealth:
    """Dynamic backend health and cost estimate."""

    available: bool
    reliability: float
    latency_ms: int
    estimated_cost_usd: float = 0.0
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    """Result returned by a backend after executing one task."""

    backend_id: str
    task_id: str
    ok: bool
    output: Any
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


class ChimeraBackend(Protocol):
    """Runtime backend protocol.

    Backends are intentionally small: they expose capability metadata,
    estimate whether they can execute a task, and then execute it.
    """

    id: str
    name: str
    capabilities: BackendCapabilities

    def probe(self) -> BackendHealth:
        ...

    def can_run(self, task: TaskSpec) -> bool:
        ...

    def estimate(self, task: TaskSpec) -> BackendHealth:
        ...

    def execute(self, task: TaskSpec) -> ExecutionResult:
        ...
