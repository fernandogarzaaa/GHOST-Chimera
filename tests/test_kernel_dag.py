"""Tests for the kernel typed-DAG execution path."""

from __future__ import annotations

from ghostchimera.chimera_pilot import ChimeraPilotKernel, TaskKind, TaskSpec
from ghostchimera.memory_layer.store import MemoryStore


def _kernel(tmp_path, monkeypatch) -> ChimeraPilotKernel:
    monkeypatch.setenv("GHOSTCHIMERA_TEMPORAL_GRAPH_DB", str(tmp_path / "graph.sqlite3"))
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.add_document("memory", "Ghost Chimera remembers project goals through CWR retrieval.")
    return ChimeraPilotKernel.default(include_deterministic_backend=True, memory_store=store)


def test_execute_dag_runs_independent_tasks(tmp_path, monkeypatch):
    kernel = _kernel(tmp_path, monkeypatch)
    a = TaskSpec.create(kind=TaskKind.RAG_QUERY, objective="retrieve project goals", inputs={"query": "goals"})
    b = TaskSpec.create(kind=TaskKind.RAG_QUERY, objective="retrieve retrieval notes", inputs={"query": "retrieval"})

    report, executions = kernel.execute_dag([a, b])

    assert report.ok
    assert set(report.succeeded) == {a.id, b.id}
    assert set(executions) == {a.id, b.id}
    assert executions[a.id].result.backend_id == "cwr.local"


def test_execute_dag_respects_dependency_order(tmp_path, monkeypatch):
    kernel = _kernel(tmp_path, monkeypatch)
    a = TaskSpec.create(kind=TaskKind.RAG_QUERY, objective="first", inputs={"query": "goals"})
    b = TaskSpec.create(
        kind=TaskKind.RAG_QUERY,
        objective="second",
        inputs={"query": "retrieval"},
        constraints={"depends_on": [a.id]},
    )

    report, _executions = kernel.execute_dag([a, b])

    assert report.ok
    assert report.order.index(a.id) < report.order.index(b.id)


def test_run_dag_compiles_and_executes_objective(tmp_path, monkeypatch):
    kernel = _kernel(tmp_path, monkeypatch)
    report, executions = kernel.run_dag("retrieve project goals")

    assert report.ok
    assert len(executions) == 1
    only = next(iter(executions.values()))
    assert only.result.backend_id == "cwr.local"
