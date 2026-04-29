"""Conscious Workspace Retrieval backend."""

from __future__ import annotations

import os
from pathlib import Path

from .base import BackendCapabilities, BackendHealth, ExecutionResult
from ...memory_layer.store import MemoryStore
from ..task_ir import TaskKind, TaskSpec


DEFAULT_MEMORY_DB = Path(os.environ.get("GHOSTCHIMERA_MEMORY_DB", "~/.ghostchimera/memory.sqlite3")).expanduser()


class CWRBackend:
    """SQLite-backed retrieval backend for RAG queries."""

    id = "cwr.local"
    name = "Conscious Workspace Retrieval"

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore(DEFAULT_MEMORY_DB)
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.RAG_QUERY},
            supports_offline=True,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=False,
            max_context_tokens=8192,
        )

    def probe(self) -> BackendHealth:
        return BackendHealth(available=True, reliability=1.0, latency_ms=1, estimated_cost_usd=0.0)

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        return self.probe()

    def execute(self, task: TaskSpec) -> ExecutionResult:
        query = str(task.inputs.get("query") or task.objective)
        limit = int(task.constraints.get("retrieval_limit", 5))
        results = self.store.search(query, limit=limit)
        output = {
            "query": query,
            "results": results,
            "citations": [item["source"] for item in results],
        }
        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=True,
            output=output,
            metrics={"result_count": len(results), "retrieval": "sqlite_fts"},
        )
