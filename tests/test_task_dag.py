"""Tests for the typed task DAG with locality-bounded repair."""

from __future__ import annotations

import pytest

from ghostchimera.chimera_pilot.task_dag import (
    DagCycleError,
    NodeResult,
    NodeStatus,
    TaskDAG,
)


def _ok_runner(node, state):
    return NodeResult(ok=True, output=f"out:{node.id}", effects={k: True for k in node.produces})


def test_topological_order_respects_dependencies():
    dag = TaskDAG()
    dag.add_node("a", "first")
    dag.add_node("b", "second", depends_on=["a"])
    dag.add_node("c", "third", depends_on=["b"])
    assert dag.topological_order() == ["a", "b", "c"]


def test_cycle_detected():
    dag = TaskDAG()
    dag.add_node("a", "a", depends_on=["c"])
    dag.add_node("b", "b", depends_on=["a"])
    dag.add_node("c", "c", depends_on=["b"])
    with pytest.raises(DagCycleError):
        dag.topological_order()


def test_unknown_dependency_raises():
    dag = TaskDAG()
    dag.add_node("a", "a", depends_on=["ghost"])
    with pytest.raises(ValueError):
        dag.topological_order()


def test_descendants():
    dag = TaskDAG()
    dag.add_node("root", "r")
    dag.add_node("mid", "m", depends_on=["root"])
    dag.add_node("leaf", "l", depends_on=["mid"])
    dag.add_node("sibling", "s", depends_on=["root"])
    assert dag.descendants("root") == {"mid", "leaf", "sibling"}
    assert dag.descendants("mid") == {"leaf"}
    assert dag.descendants("leaf") == set()


def test_full_success_run():
    dag = TaskDAG()
    dag.add_node("a", "a", produces=["x"])
    dag.add_node("b", "b", depends_on=["a"], requires=["x"])
    report = dag.execute(_ok_runner)
    assert report.ok
    assert report.succeeded == ["a", "b"]
    assert dag.nodes["b"].status == NodeStatus.SUCCEEDED


def test_failure_only_blocks_descendants_not_siblings():
    dag = TaskDAG()
    dag.add_node("root", "r")
    dag.add_node("bad", "bad", depends_on=["root"])
    dag.add_node("child_of_bad", "c", depends_on=["bad"])
    dag.add_node("sibling", "s", depends_on=["root"])

    def runner(node, state):
        if node.id == "bad":
            return NodeResult(ok=False, error="boom")
        return NodeResult(ok=True, output=node.id)

    report = dag.execute(runner, max_repairs=1)
    assert "bad" in report.failed
    assert "child_of_bad" in report.skipped
    # Sibling is unaffected — locality-bounded repair does not touch it.
    assert "sibling" in report.succeeded
    assert "root" in report.succeeded


def test_validator_triggers_repair_then_recovers():
    dag = TaskDAG()
    attempts = {"n": 0}

    def runner(node, state):
        attempts["n"] += 1
        # First attempt returns a bad value; second returns a good one.
        return NodeResult(ok=True, output="bad" if attempts["n"] == 1 else "good")

    dag.add_node("n", "n", validator=lambda out: out == "good")
    report = dag.execute(runner, max_repairs=2)
    assert report.succeeded == ["n"]
    assert report.repairs == 1
    assert attempts["n"] == 2


def test_validator_exhausts_repairs_and_fails():
    dag = TaskDAG()
    dag.add_node("n", "n", validator=lambda out: False)
    dag.add_node("after", "after", depends_on=["n"])
    report = dag.execute(lambda node, state: NodeResult(ok=True, output="x"), max_repairs=2)
    assert "n" in report.failed
    assert "after" in report.skipped
    assert report.repairs == 2


def test_missing_precondition_skips_and_blocks():
    dag = TaskDAG()
    dag.add_node("a", "a")  # produces nothing
    dag.add_node("b", "b", depends_on=["a"], requires=["never_set"])
    dag.add_node("c", "c", depends_on=["b"])
    report = dag.execute(_ok_runner)
    assert "a" in report.succeeded
    assert "b" in report.skipped
    assert "c" in report.skipped
    assert not report.ok
