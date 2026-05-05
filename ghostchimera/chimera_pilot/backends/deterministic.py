"""Deterministic backend used for tests and offline smoke checks."""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult

logger = get_logger("deterministic")


class DeterministicBackend:
    """A real backend with deterministic, configured behavior.

    This is intentionally simple and explicit.  It is useful for tests,
    scheduler smoke checks, and CI environments where no model provider or
    quantum simulator is available.
    """

    id = "deterministic.local"
    name = "Deterministic Local Backend"
    _description = "Deterministic local backend for tests and smoke checks"
    _check_fn = None

    def __init__(
        self,
        backend_id: str = "deterministic.local",
        *,
        kinds: set[TaskKind] | None = None,
        output: Any = "ok",
        fail: bool = False,
        reliability: float = 1.0,
        latency_ms: int = 1,
        supports_offline: bool = True,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        self.id = backend_id
        self._health = BackendHealth(
            available=True,
            reliability=reliability,
            latency_ms=latency_ms,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.capabilities = BackendCapabilities(
            kinds=kinds or {TaskKind.REASONING, TaskKind.TOOL_CALL, TaskKind.RAG_QUERY},
            supports_offline=supports_offline,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=not supports_offline,
            max_context_tokens=4096,
        )
        logger.debug("Provider %s initialized", self.name)
        self._output = output
        self._fail = fail

    def probe(self) -> BackendHealth:
        return self._health

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        return self._health

    def execute(self, task: TaskSpec) -> ExecutionResult:
        if self._fail:
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output="",
                error="deterministic failure",
                metrics={"deterministic": True},
            )
        output = self._output(task) if callable(self._output) else self._output
        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=True,
            output=output,
            metrics={"deterministic": True},
        )
