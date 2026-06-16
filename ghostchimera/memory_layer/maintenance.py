"""Schedulable memory-maintenance entry point.

This wires the episodic full-text store and the bi-temporal knowledge graph into
:class:`~ghostchimera.memory_layer.consolidation.MemoryConsolidator` and exposes
a single function plus a ``python -m`` entry point so the "sleep-time"
consolidation pass can be run on a schedule (cron, the daily-maintenance
workflow, or the console) without any model call.

Usage::

    python -m ghostchimera.memory_layer.maintenance --json

Paths default to the same locations the kernel uses and can be overridden via
``GHOSTCHIMERA_MEMORY_DB`` / ``GHOSTCHIMERA_TEMPORAL_GRAPH_DB``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .consolidation import MemoryConsolidator
from .store import MemoryStore
from .temporal_graph import TemporalGraphStore

DEFAULT_MEMORY_DB = "~/.ghostchimera/memory.sqlite3"
DEFAULT_TEMPORAL_GRAPH_DB = "~/.ghostchimera/temporal_graph.sqlite3"


def _resolve(path: str | Path | None, env_var: str, default: str) -> Path:
    return Path(path or os.environ.get(env_var, default)).expanduser()


def run_memory_consolidation(
    *,
    memory_db: str | Path | None = None,
    graph_db: str | Path | None = None,
    promotion_threshold: float = 0.55,
    stale_after_days: float = 365.0,
    limit: int = 200,
) -> dict[str, Any]:
    """Run one consolidation pass and return a JSON-serializable report."""

    episodic = MemoryStore(_resolve(memory_db, "GHOSTCHIMERA_MEMORY_DB", DEFAULT_MEMORY_DB))
    semantic = TemporalGraphStore(
        _resolve(graph_db, "GHOSTCHIMERA_TEMPORAL_GRAPH_DB", DEFAULT_TEMPORAL_GRAPH_DB)
    )
    consolidator = MemoryConsolidator(
        episodic,
        semantic,
        promotion_threshold=promotion_threshold,
        stale_after_days=stale_after_days,
    )
    report = consolidator.run(limit=limit)
    result = report.as_dict()
    result["semantic_fact_count"] = semantic.count(active_only=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Ghost Chimera sleep-time memory consolidation.")
    parser.add_argument("--memory-db", default=None, help="Episodic SQLite path (overrides env/default).")
    parser.add_argument("--graph-db", default=None, help="Temporal-graph SQLite path (overrides env/default).")
    parser.add_argument("--promotion-threshold", type=float, default=0.55)
    parser.add_argument("--stale-after-days", type=float, default=365.0)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = parser.parse_args(argv)

    result = run_memory_consolidation(
        memory_db=args.memory_db,
        graph_db=args.graph_db,
        promotion_threshold=args.promotion_threshold,
        stale_after_days=args.stale_after_days,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"consolidation: promoted={result['promoted']} "
            f"scanned={result['scanned']} expired_stale={result['expired_stale']} "
            f"semantic_facts={result['semantic_fact_count']}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
