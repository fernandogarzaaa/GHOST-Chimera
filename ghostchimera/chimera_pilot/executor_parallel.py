"""Parallel task execution for Chimera Pilot.

Runs multiple tasks concurrently using ThreadPoolExecutor.  Patterned after
hermes-agent/batch_runner.py's parallel execution model.

Supports dependency ordering: groups of tasks execute sequentially, while
tasks within each group can run in parallel (bounded by max_workers).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .executor import ChimeraPilotExecutor, PilotExecution
from .policy import PilotPolicy
from .scheduler import ChimeraScheduler
from .task_ir import TaskSpec
from .telemetry import InMemoryTelemetryStore

if TYPE_CHECKING:
    pass  # no extra imports needed at runtime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParallelExecutionResult:
    """Aggregated results from parallel task execution."""

    results: list[PilotExecution]
    successes: int = 0
    failures: int = 0
    total_time_seconds: float = 0.0
    task_order: list[tuple[int, PilotExecution]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "successes": self.successes,
            "failures": self.failures,
            "total_tasks": self.successes + self.failures,
            "total_time_seconds": self.total_time_seconds,
            "task_order": [(idx, r.to_dict()) for idx, r in self.task_order],
        }


def _execute_group(
    scheduler: ChimeraScheduler,
    tasks: list[TaskSpec],
    task_indices: list[int],
    max_workers: int,
    policy: PilotPolicy,
    telemetry: InMemoryTelemetryStore,
) -> list[tuple[int, PilotExecution]]:
    """Execute a group of tasks in parallel and return ordered results.

    Args:
        scheduler: ChimeraScheduler for backend routing.
        tasks: sequence of TaskSpec to execute.
        task_indices: original indices corresponding to *tasks*.
        max_workers: maximum parallelism for this group.
        policy: PilotPolicy applied to every task.
        telemetry: InMemoryTelemetryStore for recording events.

    Returns:
        List of (original_index, PilotExecution) tuples, in the same order
        as the input *tasks*/task_indices.
    """
    executor = ChimeraPilotExecutor(
        scheduler,
        policy=policy,
        telemetry=telemetry,
    )

    if len(tasks) == 1:
        # Single task: no need for thread pool
        result = executor.execute(tasks[0])
        return [(task_indices[0], result)]

    max_workers = min(max_workers, len(tasks))

    results: list[tuple[int, PilotExecution]] = [None] * len(tasks)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures: dict[Future, int] = {}
        for i, task in enumerate(tasks):
            future = pool.submit(executor.execute, task)
            futures[future] = i

        for future in futures:
            idx = futures[future]
            try:
                results[idx] = (task_indices[idx], future.result(timeout=300))
            except Exception as exc:
                logger.error("Task %s (original index %s) failed: %s", tasks[idx].id, task_indices[idx], exc)
                results[idx] = (
                    task_indices[idx],
                    PilotExecution(
                        task=tasks[idx],
                        result=_make_error_result(tasks[idx]),
                        decision=None,
                        attempts=[],
                        verification_error=str(exc),
                    ),
                )

    return [r for r in results if r is not None]


def _make_error_result(task: TaskSpec) -> Any:
    """Create a synthetic ExecutionResult indicating failure."""
    from .backends.base import ExecutionResult

    return ExecutionResult(
        backend_id="error",
        task_id=task.id,
        ok=False,
        output=None,
        error="Parallel execution raised an exception",
        metrics={},
    )


def execute_tasks_parallel(
    tasks: Sequence[TaskSpec] | list[TaskSpec],
    scheduler: ChimeraScheduler,
    max_workers: int = 4,
    *,
    policy: PilotPolicy | None = None,
    telemetry: InMemoryTelemetryStore | None = None,
    dependency_order: list[list[int]] | None = None,
) -> ParallelExecutionResult:
    """Execute multiple tasks in parallel (optionally respecting dependencies).

    Args:
        tasks: sequence of TaskSpec to execute.
        scheduler: ChimeraScheduler for backend routing.
        max_workers: maximum parallelism across all workers.
        policy: PilotPolicy applied to every task.
            Defaults to a permissive policy if *None*.
        telemetry: InMemoryTelemetryStore.
            Creates a fresh store if *None*.
        dependency_order: optional list of lists of integer indices into *tasks*.
            Each inner list is a group; groups execute sequentially, but tasks
            within a group run in parallel (up to *max_workers*).
            If *None*, all tasks run in parallel (bounded by *max_workers*).

    Returns:
        ParallelExecutionResult with results in original task order.
    """
    tasks = list(tasks)

    if not tasks:
        return ParallelExecutionResult(results=[], successes=0, failures=0, total_time_seconds=0.0)

    num_tasks = len(tasks)
    policy = policy or PilotPolicy.permissive()
    telemetry = telemetry or InMemoryTelemetryStore()
    max_workers = max(1, min(max_workers, num_tasks))

    overall_start = time.monotonic()
    all_results: dict[int, PilotExecution] = {}

    if dependency_order is not None:
        # Execute groups sequentially
        for group_indices in dependency_order:
            group_tasks = [tasks[i] for i in group_indices]
            ordered = _execute_group(
                scheduler,
                group_tasks,
                list(group_indices),
                max_workers,
                policy,
                telemetry,
            )
            for _orig_idx, execution in ordered:
                all_results[_orig_idx] = execution
    else:
        # Run all tasks in parallel (up to max_workers)
        ordered = _execute_group(
            scheduler,
            tasks,
            list(range(num_tasks)),
            max_workers,
            policy,
            telemetry,
        )
        for _orig_idx, execution in ordered:
            all_results[_orig_idx] = execution

    total_time = time.monotonic() - overall_start

    # Build ordered output preserving original task order
    results: list[PilotExecution] = []
    task_order: list[tuple[int, PilotExecution]] = []
    successes = 0
    failures = 0

    for i in range(num_tasks):
        exec = all_results.get(i)
        if exec is None:
            # Task was not executed (shouldn't happen, but guard anyway)
            failures += 1
            continue
        results.append(exec)
        task_order.append((i, exec))
        if exec.ok:
            successes += 1
        else:
            failures += 1

    return ParallelExecutionResult(
        results=results,
        successes=successes,
        failures=failures,
        total_time_seconds=total_time,
        task_order=task_order,
    )


__all__ = ["ParallelExecutionResult", "execute_tasks_parallel"]
