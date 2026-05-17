"""Batch runner — multiprocessing parallel processing of objectives.

Patterns adapted from Hermes-Agent's batch_runner.py (Nous Research, MIT licensed).
Uses multiprocessing (not ThreadPoolExecutor) for true process isolation,
with result aggregation and per-task retry.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent_core.core import AgentCore
from ..chimera_pilot.error_classifier import ErrorClassifier
from ..chimera_pilot.task_ir import TaskKind
from ..config import GhostChimeraConfig
from ..logging_config import get_logger

logger = get_logger("batch_runner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WORKERS = 4
DEFAULT_TIMEOUT = 600
DEFAULT_RETRY_COUNT = 1
DEFAULT_OUTPUT_DIR = "batch_output"

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchJob:
    """A single job in a batch run."""

    objective: str
    task_kind: TaskKind = TaskKind.REASONING
    timeout: int = DEFAULT_TIMEOUT
    retry_count: int = DEFAULT_RETRY_COUNT
    inputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchJobResult:
    """Result from a single batch job."""

    job_index: int
    objective: str
    result: str
    success: bool
    error: str | None = None
    error_category: str = "unknown"
    duration_seconds: float = 0.0
    task_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_index": self.job_index,
            "objective": self.objective,
            "result": self.result[:2000],
            "success": self.success,
            "error": self.error,
            "error_category": self.error_category,
            "duration_seconds": round(self.duration_seconds, 2),
            "task_count": self.task_count,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class BatchSummary:
    """Summary of a batch run."""

    total_jobs: int
    successful_jobs: int
    failed_jobs: int
    success_rate: float
    total_duration_seconds: float
    avg_duration_seconds: float
    jobs: list[BatchJobResult]
    output_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_jobs": self.total_jobs,
            "successful_jobs": self.successful_jobs,
            "failed_jobs": self.failed_jobs,
            "success_rate": round(self.success_rate, 3),
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "avg_duration_seconds": round(self.avg_duration_seconds, 2),
            "output_dir": self.output_dir,
            "jobs": [j.to_dict() for j in self.jobs],
        }


# ---------------------------------------------------------------------------
# Worker function (runs in separate process)
# ---------------------------------------------------------------------------


def _run_job_worker(job: BatchJob, output_dir: str, checkpoint_interval: int) -> dict[str, Any]:
    """Worker function that runs a single objective via AgentCore."""
    start = time.time()
    try:
        kernel = AgentCore.default()
        results = kernel.compile_and_run(job.objective)

        # Save individual result
        result_file = Path(output_dir) / f"job_{job.job_index}.json"
        try:
            result_file.parent.mkdir(parents=True, exist_ok=True)
            with open(result_file, "w") as f:
                json.dump({"objective": job.objective, "results": [r.to_dict() for r in results]}, f)
        except Exception as exc:
            logger.warning("Batch result write failed for job %s: %s", job.job_index, exc)

        duration = time.time() - start
        return {
            "job_index": job.job_index,
            "objective": job.objective,
            "result": json.dumps([r.to_dict() for r in results]),
            "success": True,
            "error": None,
            "error_category": "none",
            "duration_seconds": duration,
            "task_count": len(results),
            "metadata": job.inputs,
        }
    except Exception as exc:
        duration = time.time() - start
        classifier = ErrorClassifier()
        classification = classifier.classify(str(exc))
        return {
            "job_index": job.job_index,
            "objective": job.objective,
            "result": "",
            "success": False,
            "error": str(exc),
            "error_category": classification.categories[0].value if classification.categories else "unknown",
            "duration_seconds": duration,
            "task_count": 0,
            "metadata": job.inputs,
        }


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


class BatchRunner:
    """Multiprocessing-based batch execution of objectives."""

    def __init__(
        self,
        jobs: list[BatchJob],
        workers: int = DEFAULT_WORKERS,
        output_dir: str = DEFAULT_OUTPUT_DIR,
        timeout: int = DEFAULT_TIMEOUT,
        checkpoint_interval: int = 0,
        config: GhostChimeraConfig | None = None,
    ):
        self.jobs = jobs
        self.workers = min(workers, len(jobs)) if jobs else 0
        self.output_dir = output_dir
        self.timeout = timeout
        self.checkpoint_interval = checkpoint_interval
        self.config = config or GhostChimeraConfig.from_env()
        self._results: list[BatchJobResult] = []
        self._checkpoints: list[dict] = []
        self._checkpoints_count = 0

    def run(self) -> BatchSummary:
        """Execute all jobs in parallel via multiprocessing."""
        if not self.jobs:
            return BatchSummary(
                total_jobs=0,
                successful_jobs=0,
                failed_jobs=0,
                success_rate=0.0,
                total_duration_seconds=0.0,
                avg_duration_seconds=0.0,
                jobs=[],
            )

        start = time.time()
        results = []

        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            futures = []
            for job in self.jobs:
                future = executor.submit(_run_job_worker, job, self.output_dir, self.checkpoint_interval)
                futures.append(future)

            for i, future in enumerate(futures):
                job = self.jobs[i]
                try:
                    result_data = future.result(timeout=self.timeout)
                    results.append(BatchJobResult(**result_data))
                except FuturesTimeout:
                    results.append(
                        BatchJobResult(
                            job_index=job.job_index,
                            objective=job.objective,
                            result="",
                            success=False,
                            error="Batch job timed out",
                            error_category="timeout",
                            duration_seconds=self.timeout,
                            metadata=job.inputs,
                        )
                    )

                # Periodic checkpoint
                if self.checkpoint_interval and (i + 1) % self.checkpoint_interval == 0:
                    self._save_checkpoint(results)

        duration = time.time() - start
        successful = sum(1 for r in results if r.success)

        # Save summary
        self._save_summary(results, duration)

        summary = BatchSummary(
            total_jobs=len(results),
            successful_jobs=successful,
            failed_jobs=len(results) - successful,
            success_rate=successful / len(results) if results else 0.0,
            total_duration_seconds=duration,
            avg_duration_seconds=duration / len(results) if results else 0.0,
            jobs=results,
            output_dir=self.output_dir,
        )
        self._results = results
        return summary

    def run_with_checkpoints(self, output_dir: str | None = None) -> BatchSummary:
        """Run with automatic checkpointing at each step."""
        checkpoint_dir = output_dir or f"{self.output_dir}_checkpoints"

        results = []
        for i, job in enumerate(self.jobs):
            # Create per-job checkpoint
            checkpoint_dir_job = f"{checkpoint_dir}/job_{i}"
            try:
                Path(checkpoint_dir_job).mkdir(parents=True, exist_ok=True)
                with open(f"{checkpoint_dir_job}/state.json", "w") as f:
                    json.dump({"job": job.objective, "index": i, "state": "running"}, f)
            except Exception as exc:
                logger.warning("Batch checkpoint state write failed for job %s: %s", i, exc)

            result = self._run_single_with_checkpoint(job, checkpoint_dir_job)
            results.append(result)

            # Save progress checkpoint
            self._save_checkpoint(results)

        duration = time.time() - getattr(self, "_run_start", time.time())
        successful = sum(1 for r in results if r.success)

        return BatchSummary(
            total_jobs=len(results),
            successful_jobs=successful,
            failed_jobs=len(results) - successful,
            success_rate=successful / len(results) if results else 0.0,
            total_duration_seconds=duration,
            avg_duration_seconds=duration / len(results) if results else 0.0,
            jobs=results,
            output_dir=output_dir or self.output_dir,
        )

    def classify_batch_errors(self, results: list[BatchJobResult]) -> dict[str, int]:
        """Classify all batch errors by category."""
        categories: dict[str, int] = {}
        for r in results:
            if not r.success:
                cats = categories.get(r.error_category, 0)
                categories[r.error_category] = cats + 1
        return categories

    def _run_single_with_checkpoint(self, job: BatchJob, checkpoint_dir: str) -> BatchJobResult:
        """Run a single job with checkpoint support."""
        self._run_start = getattr(self, "_run_start", time.time())
        return _run_job_worker(job, checkpoint_dir, self.checkpoint_interval)

    def _save_checkpoint(self, results: list[BatchJobResult]) -> None:
        """Save a checkpoint of current progress."""
        try:
            checkpoint_file = f"{self.output_dir}/checkpoint_{self._checkpoints_count}.json"
            Path(checkpoint_file).parent.mkdir(parents=True, exist_ok=True)
            checkpoint_data = {
                "checkpoint": self._checkpoints_count,
                "results": [r.to_dict() for r in results],
                "timestamp": time.time(),
            }
            with open(checkpoint_file, "w") as f:
                json.dump(checkpoint_data, f)
            self._checkpoints_count += 1
        except Exception as exc:
            logger.warning("Checkpoint save failed: %s", exc)

    def _save_summary(self, results: list[BatchJobResult], duration: float) -> None:
        """Save batch summary."""
        try:
            summary_file = f"{self.output_dir}/summary.json"
            Path(summary_file).parent.mkdir(parents=True, exist_ok=True)
            summary = {
                "total_jobs": len(results),
                "successful": sum(1 for r in results if r.success),
                "failed": sum(1 for r in results if not r.success),
                "duration_seconds": duration,
                "timestamp": time.time(),
                "jobs": [r.to_dict() for r in results],
            }
            with open(summary_file, "w") as f:
                json.dump(summary, f, indent=2)

            # Also save as JSONL
            jsonl_file = f"{self.output_dir}/results.jsonl"
            with open(jsonl_file, "w") as f:
                for r in results:
                    f.write(json.dumps(r.to_dict()) + "\n")
        except Exception as exc:
            logger.warning("Summary save failed: %s", exc)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def run_batch(
    objectives: list[str],
    workers: int = DEFAULT_WORKERS,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    timeout: int = DEFAULT_TIMEOUT,
) -> BatchSummary:
    """Quick batch run of multiple objectives."""
    jobs = [BatchJob(objective=obj) for obj in objectives]
    runner = BatchRunner(jobs, workers=workers, output_dir=output_dir, timeout=timeout)
    return runner.run()


__all__ = [
    "BatchRunner",
    "BatchJob",
    "BatchJobResult",
    "BatchSummary",
    "run_batch",
]
