"""Fallback-aware task executor for Chimera Pilot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..logging_config import get_logger
from .backends.base import ExecutionResult
from .policy import PilotPolicy
from .result_envelope import ResultEnvelope
from .scheduler import ChimeraScheduler, ScheduleDecision
from .schema import validate_task
from .task_ir import TaskSpec
from .telemetry import InMemoryTelemetryStore, PilotTelemetryEvent, now
from .verifier import ResultVerifier

logger = get_logger("executor")

if TYPE_CHECKING:
    from .result_envelope import ResultEnvelope


@dataclass(frozen=True)
class PilotExecution:
    task: TaskSpec
    result: ExecutionResult
    decision: ScheduleDecision
    attempts: list[ExecutionResult]
    verification_error: str | None = None
    envelope: ResultEnvelope | None = None

    @property
    def ok(self) -> bool:
        return self.result.ok and self.verification_error is None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
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
        if self.envelope is not None:
            d["envelope"] = self.envelope.to_dict()
        return d

    def to_envelope(self) -> ResultEnvelope:
        """Return the envelope, constructing one from execution state if needed."""
        if self.envelope is not None:
            return self.envelope
        # Build envelope on-demand for backward compatibility
        confidence = 1.0 if self.ok else 0.0
        return ResultEnvelope(
            kind=self.task.kind.value,
            value=self.result.output,
            confidence=confidence,
            confidence_source="pilot_execution" if self.ok else "verification_failure",
            provenance=[
                {
                    "step": "backend_selection",
                    "backend_id": self.result.backend_id,
                    "score": self.decision.score,
                    "reasons": list(self.decision.reasons),
                }
            ],
            claims=[
                {"claim": "task_completed", "passed": self.ok},
                {"claim": "verification_passed", "passed": self.verification_error is None},
            ],
            warnings=[],
            metadata={
                "task_id": self.task.id,
                "task_kind": self.task.kind.value,
                "attempts": len(self.attempts),
                "score": self.decision.score,
                "backend_id": self.result.backend_id,
                "backend_name": self.result.backend_id,
                "verification_error": self.verification_error,
            },
        )


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
        valid, errors = validate_task(task.kind, task.inputs)
        if not valid:
            raise RuntimeError(f"Validation failed: {errors}")
        self.policy.validate(task)
        ranked = self.scheduler.rank_backends(task)
        if not ranked:
            raise RuntimeError(f"No available backend can run task {task.id}: {task.kind.value}")

        attempts: list[ExecutionResult] = []
        last_verification_error: str | None = None
        last_decision = ranked[0]
        last_result: ExecutionResult | None = None

        for decision in ranked:
            logger.info("Executing task %s on backend %s", task.id, decision.backend.id)
            started = now()
            try:
                result = decision.backend.execute(task)
            except Exception as exc:  # pragma: no cover - defensive guard for third-party backends
                raw_error = str(exc)
                # Mask any leaked API keys before storing
                for secret_prefix in ("Bearer sk-", "Bearer pk-", "Bearer ak"):
                    if secret_prefix in raw_error:
                        raw_error = raw_error[:raw_error.index(secret_prefix)] + secret_prefix + "*MASKED*"
                result = ExecutionResult(
                    backend_id=decision.backend.id,
                    task_id=task.id,
                    ok=False,
                    output="",
                    error=raw_error,
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
                envelope = ResultEnvelope(
                    kind=task.kind.value,
                    value=result.output,
                    confidence=1.0,
                    confidence_source="execution_success",
                    provenance=[
                        {
                            "step": "backend_selection",
                            "backend_id": decision.backend.id,
                            "score": decision.score,
                            "reasons": list(decision.reasons),
                        }
                    ],
                    claims=[
                        {"claim": "task_completed", "passed": True},
                        {"claim": "verification_passed", "passed": True},
                    ],
                    warnings=[],
                    metadata={
                        "task_id": task.id,
                        "task_kind": task.kind.value,
                        "attempts": len(attempts),
                        "score": decision.score,
                        "backend_id": decision.backend.id,
                    },
                )
                return PilotExecution(
                    task=task,
                    result=result,
                    decision=decision,
                    attempts=attempts,
                    verification_error=None,
                    envelope=envelope,
                )

        assert last_result is not None
        envelope = ResultEnvelope(
            kind=task.kind.value,
            value=last_result.output,
            confidence=0.0,
            confidence_source="execution_failure",
            provenance=[
                {
                    "step": "backend_selection",
                    "backend_id": last_decision.backend.id,
                    "score": last_decision.score,
                    "reasons": list(last_decision.reasons),
                }
            ],
            claims=[
                {"claim": "task_completed", "passed": last_result.ok},
                {"claim": "verification_passed", "passed": last_verification_error is None},
            ],
            warnings=[],
            metadata={
                "task_id": task.id,
                "task_kind": task.kind.value,
                "attempts": len(attempts),
                "score": last_decision.score,
                "backend_id": last_decision.backend.id,
                "verification_error": last_verification_error,
            },
        )
        return PilotExecution(
            task=task,
            result=last_result,
            decision=last_decision,
            attempts=attempts,
            verification_error=last_verification_error,
            envelope=envelope,
        )
