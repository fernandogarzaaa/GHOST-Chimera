"""Tests for the schedulable memory-consolidation entry point."""

from __future__ import annotations

import json

from ghostchimera.memory_layer.maintenance import main, run_memory_consolidation
from ghostchimera.memory_layer.store import MemoryStore
from ghostchimera.memory_layer.temporal_graph import TemporalGraphStore


def test_run_memory_consolidation_promotes_and_reports(tmp_path):
    mem = tmp_path / "memory.sqlite3"
    graph = tmp_path / "graph.sqlite3"
    store = MemoryStore(mem)
    store.add_document(
        "chat",
        "onboarding notes",
        {"subject": "user", "predicate": "uses", "object": "Linux", "access_count": 12},
    )

    result = run_memory_consolidation(memory_db=mem, graph_db=graph, promotion_threshold=0.3)

    assert result["promoted"] == 1
    assert result["semantic_fact_count"] == 1
    facts = TemporalGraphStore(graph).active_facts(subject="user", predicate="uses")
    assert facts[0].obj == "Linux"


def test_main_emits_json(tmp_path, capsys):
    mem = tmp_path / "memory.sqlite3"
    graph = tmp_path / "graph.sqlite3"
    MemoryStore(mem).add_document("note", "irrelevant low heat", {"access_count": 0})

    rc = main(["--memory-db", str(mem), "--graph-db", str(graph), "--json"])
    captured = capsys.readouterr().out

    assert rc == 0
    payload = json.loads(captured)
    assert "promoted" in payload
    assert "semantic_fact_count" in payload


def test_main_human_readable_output(tmp_path, capsys):
    mem = tmp_path / "memory.sqlite3"
    graph = tmp_path / "graph.sqlite3"
    MemoryStore(mem)  # empty store
    rc = main(["--memory-db", str(mem), "--graph-db", str(graph)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "consolidation:" in out
    assert "promoted=" in out
