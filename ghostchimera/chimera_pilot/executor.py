"""Fallback-aware task executor for Chimera Pilot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .backends.base import ExecutionResult
from .policy import PilotPolicy
from .scheduler import ChimeraScheduler, ScheduleDecision
from .task_ir import TaskSpec
from .telemetry import InMemoryTelemetryStore, PilotTelemetryEvent, now
from .verifier import ResultVerifier


@dataclass(frozen=True)
class PilotExecution:
    task: TaskSpec
    result: ExecutionResult
    decision: ScheduleDecision
    attempts: list[ExecutionResult]
    verification_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.result.ok and self.verification_error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task.id,
            "task_kind": self.task.kind.value,
            "backend_id": self.result.backend_id,
            "ok": self.ok,
            "output": self.result.output,
            "error": self.result.error,
            "verification_error": self.verification_error,
            "score": self.decision.score,
            "reasons": list(self.decision.reasons),
            "attempts": [
                {
                    "backend_id": attempt.backend_id,
                    "ok": attempt.ok,
                    "error": attempt.error,
                    "metrics": dict(attempt.metrics),
                }
                for attempt in self.attempts
            ],
        }


class ChimeraPilotExecutor:
    """Execute tasks using scheduler ranking and fallback."""

    def __init__(
        self,
        scheduler: ChimeraScheduler,
        *,
        policy: PilotPolicy | None = None,
        verifier: ResultVerifier | None = None,
        telemetry: InMemoryTelemetryStore | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.policy = policy or PilotPolicy()
        self.verifier = verifier or ResultVerifier()
        self.telemetry = telemetry or InMemoryTelemetryStore()

    def execute(self, task: TaskSpec) -> PilotExecution:
        self.policy.validate(task)
        ranked = self.scheduler.rank_backends(task)
        if not ranked:
            raise RuntimeError(f"No available backend can run task {task.id}: {task.kind.value}")

        attempts: list[ExecutionResult] = []
        last_verification_error: str | None = None
        last_decision = ranked[0]
        last_result: ExecutionResult | None = None

        for decision in ranked:
            started = now()
            try:
                result = decision.backend.execute(task)
            except Exception as exc:  # pragma: no cover - defensive guard for third-party backends
                result = ExecutionResult(
                    backend_id=decision.backend.id,
                    task_id=task.id,
                    ok=False,
                    output="",
                    error=str(exc),
                    metrics={},
                )
            finished = now()
            attempts.append(result)
            self.telemetry.record(
                PilotTelemetryEvent(
                    task_id=task.id,
                    backend_id=decision.backend.id,
                    ok=result.ok,
                    started_at=started,
                    finished_at=finished,
                    error=result.error,
                    metrics=result.metrics,
                )
            )
            last_decision = decision
            last_result = result
            verified, verification_error = self.verifier.verify(task, result)
            last_verification_error = verification_error
            if result.ok and verified:
                return PilotExecution(
                    task=task,
                    result=result,
                    decision=decision,
                    attempts=attempts,
                    verification_error=None,
                )

        assert last_result is not None
        return PilotExecution(
            task=task,
            result=last_result,
            decision=last_decision,
            attempts=attempts,
            verification_error=last_verification_error,
        )
