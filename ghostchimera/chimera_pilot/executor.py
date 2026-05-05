"""Fallback-aware task executor for Chimera Pilot."""

from __future__ import annotations

from dataclasses import dataclass
import uuid
from enum import Enum
import hashlib
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
from .semantic_verifier import SemanticVerifier

logger = get_logger("executor")

if TYPE_CHECKING:
    from .result_envelope import ResultEnvelope


class PilotRunState(str, Enum):
    PLANNED = "planned"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMMITTED = "committed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class StateTransition:
    state: PilotRunState
    at: float
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "at": self.at, "detail": self.detail}


@dataclass(frozen=True)
class PilotExecution:
    task: TaskSpec
    result: ExecutionResult
    decision: ScheduleDecision
    attempts: list[ExecutionResult]
    verification_error: str | None = None
    envelope: ResultEnvelope | None = None
    transitions: list[StateTransition] | None = None
    run_id: str | None = None
    attempt_id: str | None = None
    checkpoint_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.result.ok and self.verification_error is None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "checkpoint_id": self.checkpoint_id,
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
        if self.transitions is not None:
            d["transitions"] = [t.to_dict() for t in self.transitions]
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
                "run_id": self.run_id,
                "attempt_id": self.attempt_id,
                "checkpoint_id": self.checkpoint_id,
            },
        )

    def to_replay_bundle(self) -> dict[str, Any]:
        """Return a deterministic replay bundle for postmortem/debug workflows."""
        def _sha256_text(value: Any) -> str:
            text = "" if value is None else str(value)
            return hashlib.sha256(text.encode("utf-8")).hexdigest()

        return {
            "run": {
                "run_id": self.run_id,
                "attempt_id": self.attempt_id,
                "checkpoint_id": self.checkpoint_id,
                "task_id": self.task.id,
                "task_kind": self.task.kind.value,
                "objective": self.task.objective,
                "inputs": dict(self.task.inputs),
                "strategy": (self.envelope.metadata.get("strategy") if self.envelope is not None else None),
            },
            "decision": {
                "backend_id": self.decision.backend.id if self.decision is not None else None,
                "score": self.decision.score if self.decision is not None else None,
                "reasons": list(self.decision.reasons) if self.decision is not None else [],
            },
            "attempts": [
                {
                    "backend_id": attempt.backend_id,
                    "ok": attempt.ok,
                    "error": attempt.error,
                    "metrics": dict(attempt.metrics),
                    "output_hash": _sha256_text(attempt.output),
                    "error_hash": _sha256_text(attempt.error),
                }
                for attempt in self.attempts
            ],
            "transitions": [t.to_dict() for t in (self.transitions or [])],
            "trace_hash": _sha256_text([t.to_dict() for t in (self.transitions or [])]),
            "verification_error": self.verification_error,
            "ok": self.ok,
            "warnings": list(self.envelope.warnings) if self.envelope is not None else [],
        }


class ChimeraPilotExecutor:
    """Execute tasks using scheduler ranking and fallback."""

    def __init__(
        self,
        scheduler: ChimeraScheduler,
        *,
        policy: PilotPolicy | None = None,
        verifier: ResultVerifier | None = None,
        semantic_verifier: SemanticVerifier | None = None,
        telemetry: InMemoryTelemetryStore | None = None,
        checkpoint_manager: Any | None = None,
        outcome_store: Any | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.policy = policy or PilotPolicy()
        self.verifier = verifier or ResultVerifier()
        self.semantic_verifier = semantic_verifier or SemanticVerifier()
        self.telemetry = telemetry or InMemoryTelemetryStore()
        self.checkpoint_manager = checkpoint_manager
        self.outcome_store = outcome_store
        self._cancelled_runs: set[str] = set()

    def _record_checkpoint(self, run_id: str, state: str) -> None:
        if self.checkpoint_manager is None:
            return
        try:
            self.checkpoint_manager.create_checkpoint(description=f"{state}:{run_id}")
        except Exception:  # pragma: no cover - defensive only
            logger.debug("checkpoint recording failed for run %s", run_id, exc_info=True)

    def _record_outcome(
        self,
        *,
        backend_id: str,
        task_kind: str,
        success: bool,
        latency_ms: float,
        verifier_score: float,
        policy_warnings: list[str] | None = None,
    ) -> None:
        if self.outcome_store is None:
            return
        try:
            self.outcome_store.record_outcome(
                backend_id=backend_id,
                task_kind=task_kind,
                success=success,
                latency_ms=latency_ms,
                verifier_score=verifier_score,
                policy_warnings=policy_warnings or [],
            )
        except Exception:  # pragma: no cover - defensive only
            logger.debug("outcome recording failed for %s", backend_id, exc_info=True)

    def _historical_success_rate(self, task_kind: str) -> float | None:
        if self.outcome_store is None or not hasattr(self.outcome_store, "recent_outcomes"):
            return None
        try:
            rows = self.outcome_store.recent_outcomes(limit=100)
        except Exception:  # pragma: no cover - defensive only
            return None
        filtered = [row for row in rows if row.get("task_kind") == task_kind]
        if not filtered:
            return None
        successes = sum(1 for row in filtered if bool(row.get("success")))
        return successes / len(filtered)

    def cancel_run(self, run_id: str) -> None:
        """Mark a run as cancelled. Future or in-flight execution checks will stop."""
        self._cancelled_runs.add(run_id)

    def execute(self, task: TaskSpec) -> PilotExecution:
        run_id = f"run-{task.id}-{uuid.uuid4().hex[:8]}"
        attempt_id = f"attempt-{uuid.uuid4().hex[:8]}"
        checkpoint_id = f"ckpt-{uuid.uuid4().hex[:8]}"
        return self._execute_with_context(
            task=task,
            run_id=run_id,
            attempt_id=attempt_id,
            checkpoint_id=checkpoint_id,
            resumed_from_checkpoint=None,
        )

    def resume_run(self, task: TaskSpec, *, run_id: str, checkpoint_id: str) -> PilotExecution:
        """Resume an interrupted run from a known checkpoint context."""
        attempt_id = f"attempt-{uuid.uuid4().hex[:8]}"
        return self._execute_with_context(
            task=task,
            run_id=run_id,
            attempt_id=attempt_id,
            checkpoint_id=checkpoint_id,
            resumed_from_checkpoint=checkpoint_id,
        )

    def _execute_with_context(
        self,
        *,
        task: TaskSpec,
        run_id: str,
        attempt_id: str,
        checkpoint_id: str,
        resumed_from_checkpoint: str | None,
    ) -> PilotExecution:
        valid, errors = validate_task(task.kind, task.inputs)
        if not valid:
            raise RuntimeError(f"Validation failed: {errors}")
        self.policy.validate(task)
        selected_strategy = "single"
        if hasattr(self.scheduler, "select_strategy"):
            uncertainty = task.constraints.get("uncertainty")
            try:
                uncertainty_value = float(uncertainty) if uncertainty is not None else None
            except (TypeError, ValueError):
                uncertainty_value = None
            historical_success_rate = self._historical_success_rate(task.kind.value)
            selected_strategy = self.scheduler.select_strategy(
                task,
                historical_success_rate=historical_success_rate,
                uncertainty=uncertainty_value,
            )
        ranked = self.scheduler.rank_backends(task)
        if not ranked:
            raise RuntimeError(f"No available backend can run task {task.id}: {task.kind.value}")

        transitions: list[StateTransition] = [
            StateTransition(PilotRunState.PLANNED, now(), f"task accepted strategy={selected_strategy}")
        ]
        if resumed_from_checkpoint:
            transitions.append(
                StateTransition(PilotRunState.PLANNED, now(), f"resumed_from={resumed_from_checkpoint}")
            )
        attempts: list[ExecutionResult] = []
        last_verification_error: str | None = None
        last_decision = ranked[0]
        last_result: ExecutionResult | None = None

        transitions.append(StateTransition(PilotRunState.SCHEDULED, now(), f"ranked_backends={len(ranked)}"))

        if run_id in self._cancelled_runs:
            transitions.append(StateTransition(PilotRunState.CANCELLED, now(), "cancelled_before_execution"))
            cancelled_result = ExecutionResult(
                backend_id=ranked[0].backend.id,
                task_id=task.id,
                ok=False,
                output="",
                error="Run cancelled",
                metrics={},
            )
            envelope = ResultEnvelope(
                kind=task.kind.value,
                value="",
                confidence=0.0,
                confidence_source="execution_cancelled",
                provenance=[],
                claims=[{"claim": "task_completed", "passed": False}],
                warnings=["run_cancelled"],
                metadata={"task_id": task.id, "run_id": run_id, "attempt_id": attempt_id, "checkpoint_id": checkpoint_id},
            )
            execution = PilotExecution(
                task=task,
                result=cancelled_result,
                decision=ranked[0],
                attempts=[],
                verification_error="Run cancelled",
                envelope=envelope,
                transitions=transitions,
                run_id=run_id,
                attempt_id=attempt_id,
                checkpoint_id=checkpoint_id,
            )
            self.telemetry.record_replay_bundle(execution.to_replay_bundle())
            self._record_checkpoint(run_id, "cancelled")
            return execution

        for decision in ranked:
            if run_id in self._cancelled_runs:
                transitions.append(StateTransition(PilotRunState.CANCELLED, now(), "cancelled_during_execution"))
                break
            logger.info("Executing task %s on backend %s", task.id, decision.backend.id)
            transitions.append(StateTransition(PilotRunState.EXECUTING, now(), f"backend={decision.backend.id}"))
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
            if hasattr(self.scheduler, "adapt_from_outcome"):
                self.scheduler.adapt_from_outcome(
                    backend_id=decision.backend.id,
                    success=result.ok,
                    latency_ms=(finished - started) * 1000.0,
                )
            self._record_outcome(
                backend_id=decision.backend.id,
                task_kind=task.kind.value,
                success=result.ok,
                latency_ms=(finished - started) * 1000.0,
                verifier_score=1.0 if result.ok else 0.0,
                policy_warnings=[],
            )
            last_decision = decision
            last_result = result
            transitions.append(StateTransition(PilotRunState.VERIFYING, now(), f"backend={decision.backend.id}"))
            verified, verification_error = self.verifier.verify(task, result)
            last_verification_error = verification_error
            if result.ok and verified:
                # Run semantic verification alongside structural
                semantic_ok, semantic_err, semantic_warnings = self.semantic_verifier.verify(task, result, envelope=None)
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
                    warnings=semantic_warnings if semantic_ok else [],
                    metadata={
                        "task_id": task.id,
                        "task_kind": task.kind.value,
                        "attempts": len(attempts),
                        "score": decision.score,
                        "backend_id": decision.backend.id,
                        "semantic_ok": semantic_ok,
                        "strategy": selected_strategy,
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "checkpoint_id": checkpoint_id,
                    },
                )
                transitions.append(StateTransition(PilotRunState.COMMITTED, now(), f"backend={decision.backend.id}"))
                execution = PilotExecution(
                    task=task,
                    result=result,
                    decision=decision,
                    attempts=attempts,
                    verification_error=None,
                    envelope=envelope,
                    transitions=transitions,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    checkpoint_id=checkpoint_id,
                )
                self.telemetry.record_replay_bundle(execution.to_replay_bundle())
                self._record_checkpoint(run_id, "committed")
                return execution

        if run_id in self._cancelled_runs and last_result is None:
            envelope = ResultEnvelope(
                kind=task.kind.value,
                value="",
                confidence=0.0,
                confidence_source="execution_cancelled",
                provenance=[],
                claims=[{"claim": "task_completed", "passed": False}],
                warnings=["run_cancelled"],
                metadata={"task_id": task.id, "run_id": run_id, "attempt_id": attempt_id, "checkpoint_id": checkpoint_id},
            )
            execution = PilotExecution(
                task=task,
                result=ExecutionResult(
                    backend_id=ranked[0].backend.id,
                    task_id=task.id,
                    ok=False,
                    output="",
                    error="Run cancelled",
                    metrics={},
                ),
                decision=ranked[0],
                attempts=[],
                verification_error="Run cancelled",
                envelope=envelope,
                transitions=transitions,
                run_id=run_id,
                attempt_id=attempt_id,
                checkpoint_id=checkpoint_id,
            )
            self.telemetry.record_replay_bundle(execution.to_replay_bundle())
            self._record_checkpoint(run_id, "cancelled")
            return execution

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
                "strategy": selected_strategy,
                "run_id": run_id,
                "attempt_id": attempt_id,
                "checkpoint_id": checkpoint_id,
            },
        )
        transitions.append(StateTransition(PilotRunState.FAILED, now(), f"attempts={len(attempts)}"))
        execution = PilotExecution(
            task=task,
            result=last_result,
            decision=last_decision,
            attempts=attempts,
            verification_error=last_verification_error,
            envelope=envelope,
            transitions=transitions,
            run_id=run_id,
            attempt_id=attempt_id,
            checkpoint_id=checkpoint_id,
        )
        self.telemetry.record_replay_bundle(execution.to_replay_bundle())
        self._record_checkpoint(run_id, "failed")
        return execution
