"""Batch agent runner for Ghost Chimera.

Provides parallel batch processing of objectives via independent worker threads.
Patterned after hermes-agent's batch_runner.py.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result of a single batch task."""
    objective: str
    index: int
    result: str
    success: bool
    error: str | None = None
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "index": self.index,
            "result": self.result,
            "success": self.success,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "metadata": self.metadata,
        }


@dataclass
class BatchSummary:
    """Summary of a batch run."""
    total_tasks: int
    successful_tasks: int
    failed_tasks: int
    total_duration_seconds: float
    results: list[BatchResult]
    output_dir: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "failed_tasks": self.failed_tasks,
            "total_duration_seconds": self.total_duration_seconds,
            "results": [r.to_dict() for r in self.results],
            "output_dir": self.output_dir,
        }


class BatchAgent:
    """Run multiple objectives in parallel using worker threads.

    Each worker creates an independent ``AgentCore`` instance and calls
    ``AgentCore.handle_request()`` for its assigned objective.

    Usage::

        runner = BatchAgent(
            objectives=["objective 1", "objective 2"],
            workers=4,
            output_dir="./output",
        )
        summary = runner.run()
        print(json.dumps(summary.to_dict(), indent=2))
    """

    def __init__(
        self,
        objectives: Sequence[str],
        *,
        workers: int = 4,
        output_dir: str = "./batch_output",
        checkpoint_interval: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.objectives = list(objectives)
        self.workers = max(1, workers)
        self.output_dir = Path(output_dir)
        self.checkpoint_interval = checkpoint_interval
        self.metadata = metadata or {}
        self._results: list[BatchResult] = []
        self._checkpoint_lock = threading.Lock()

    def _process_objective(self, objective: str, index: int) -> BatchResult:
        """Process a single objective in a worker thread."""
        from ..agent_core.core import AgentCore

        agent = AgentCore()
        start_time = time.time()
        try:
            result_text = agent.handle_request(objective)
            duration = time.time() - start_time
            return BatchResult(
                objective=objective,
                index=index,
                result=str(result_text),
                success=True,
                duration_seconds=duration,
                metadata=dict(self.metadata),
            )
        except Exception as exc:
            duration = time.time() - start_time
            return BatchResult(
                objective=objective,
                index=index,
                result="",
                success=False,
                error=str(exc),
                duration_seconds=duration,
                metadata=dict(self.metadata),
            )

    def _save_checkpoint(self, completed: int, checkpoint_data: dict[str, Any]) -> None:
        """Save checkpoint data atomically."""
        checkpoint_data["completed_count"] = completed
        checkpoint_data["last_updated"] = time.time()
        checkpoint_file = self.output_dir / "checkpoint.json"
        tmp_file = self.output_dir / "checkpoint.tmp"
        with open(tmp_file, "w") as f:
            json.dump(checkpoint_data, f, indent=2)
        os.replace(str(tmp_file), str(checkpoint_file))

    def run(self) -> BatchSummary:
        """Execute all objectives in parallel and return results."""
        self._results = []
        self.output_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_data: dict[str, Any] = {"completed_count": 0, "last_updated": time.time()}
        start_time = time.time()
        completed = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(self._process_objective, obj, idx): idx
                for idx, obj in enumerate(self.objectives)
            }
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                self._results.append(result)
                completed += 1
                if completed % self.checkpoint_interval == 0:
                    self._save_checkpoint(completed, checkpoint_data)

        # Sort results by index for deterministic output
        self._results.sort(key=lambda r: r.index)

        total_duration = time.time() - start_time
        self._save_results()

        successes = sum(1 for r in self._results if r.success)
        return BatchSummary(
            total_tasks=len(self._results),
            successful_tasks=successes,
            failed_tasks=len(self._results) - successes,
            total_duration_seconds=total_duration,
            results=self._results,
            output_dir=str(self.output_dir),
        )

    def _save_results(self) -> None:
        """Save all results to output files."""
        # Save individual results
        for result in self._results:
            result_file = self.output_dir / f"task_{result.index}.json"
            with open(result_file, "w") as f:
                json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

        # Save combined results
        combined_file = self.output_dir / "results.jsonl"
        with open(combined_file, "w") as f:
            for result in self._results:
                f.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")

        # Save summary
        successes = sum(1 for r in self._results if r.success)
        summary = {
            "total_tasks": len(self._results),
            "successful_tasks": successes,
            "failed_tasks": len(self._results) - successes,
            "results": [r.to_dict() for r in self._results],
            "output_dir": str(self.output_dir),
        }
        summary_file = self.output_dir / "summary.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)


class ParallelAgent:
    """Lightweight parallel agent that reads objectives from a JSONL file."""

    def __init__(
        self,
        jsonl_file: str,
        *,
        workers: int = 4,
        output_dir: str = "./parallel_output",
    ) -> None:
        self.jsonl_file = jsonl_file
        self.workers = max(1, workers)
        self.output_dir = output_dir

    def run(self) -> BatchSummary:
        """Read objectives from JSONL and run them in parallel."""
        objectives: list[str] = []
        with open(self.jsonl_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                objective = entry.get("objective") or entry.get("prompt") or entry.get("text", "")
                if objective:
                    objectives.append(objective)

        runner = BatchAgent(
            objectives=objectives,
            workers=self.workers,
            output_dir=self.output_dir,
        )
        return runner.run()
