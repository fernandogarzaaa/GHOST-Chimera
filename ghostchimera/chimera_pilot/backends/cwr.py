"""Conscious Workspace Retrieval backend."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...memory_layer.store import MemoryStore
from ...memory_layer.temporal_graph import TemporalGraphStore
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult

# Short, low-signal tokens that should not seed graph-fact lookups.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
        "what", "who", "where", "when", "why", "how", "do", "does", "did", "my", "me",
        "with", "about", "i", "you", "it", "this", "that",
    }
)

DEFAULT_MEMORY_DB = Path(os.environ.get("GHOSTCHIMERA_MEMORY_DB", "~/.ghostchimera/memory.sqlite3")).expanduser()


logger = get_logger("cwr")


class CWRBackend:
    """SQLite-backed retrieval backend for RAG queries."""

    id = "cwr.local"
    name = "Conscious Workspace Retrieval"
    _description = "SQLite FTS5 retrieval backend"

    def __init__(
        self,
        store: MemoryStore | None = None,
        *,
        graph: TemporalGraphStore | None = None,
    ) -> None:
        self.store = store or MemoryStore(DEFAULT_MEMORY_DB)
        # Optional bi-temporal knowledge graph: when present, retrieval fuses
        # durable facts (coarse) with episodic FTS chunks (fine) per the
        # decouple-before-aggregate pattern. Absent by default → FTS-only.
        self.graph = graph
        logger.debug("Provider %s initialized", self.name)
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
        citations = [item["source"] for item in results]
        output: dict[str, Any] = {
            "query": query,
            "results": results,
            "citations": citations,
        }
        metrics: dict[str, Any] = {"result_count": len(results), "retrieval": "sqlite_fts"}

        facts = self._graph_facts(query, limit=limit) if self.graph is not None else []
        if facts:
            output["facts"] = facts
            output["citations"] = citations + [f"graph:{f['subject']}/{f['predicate']}" for f in facts]
            metrics["fact_count"] = len(facts)
            metrics["retrieval"] = "sqlite_fts+temporal_graph"

        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=True,
            output=output,
            metrics=metrics,
        )

    def _graph_facts(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        """Retrieve durable facts about entities mentioned in *query*.

        Tokens are matched against fact subjects/objects; for each seed entity
        the active (currently-believed, in-validity-window) facts and their
        one-hop neighbours are returned, de-duplicated and confidence-ordered.
        """

        assert self.graph is not None  # guarded by caller
        seeds = {
            tok.strip(".,?!:;\"'").lower()
            for tok in query.split()
            if len(tok) > 2 and tok.strip(".,?!:;\"'").lower() not in _STOPWORDS
        }
        if not seeds:
            return []
        collected: dict[int, dict[str, Any]] = {}
        for fact in self.graph.system_active_facts(limit=500):
            subject_l = fact.subject.lower()
            object_l = (fact.obj or "").lower()
            if subject_l in seeds or object_l in seeds or any(s in subject_l for s in seeds):
                for active in self.graph.active_facts(subject=fact.subject, limit=limit * 2):
                    collected[active.id] = active.as_dict()
        ranked = sorted(collected.values(), key=lambda f: f["confidence"], reverse=True)
        return ranked[: limit * 2]
