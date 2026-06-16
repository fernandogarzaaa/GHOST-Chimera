"""Typed task DAG with locality-bounded repair for Chimera Pilot.

Chimera Pilot already compiles objectives into :class:`TaskSpec` units.  This
module adds the next step that 2026 agent-orchestration research converged on
(GraSP, TDP, GraphBit): represent the plan as a *typed directed acyclic graph*
with explicit precondition/effect edges, execute it in topological order, and —
critically — when a node fails, invalidate and re-plan **only its topological
descendants** rather than the whole objective.  This keeps replanning cost at
``O(descendants)`` instead of ``O(N)`` and is essential for a small local model
with a tight context budget.

The engine governs all control flow deterministically; the per-node ``runner``
is the only place model/backends are invoked, mirroring the
"engine-orchestrated, LLM-as-judgment-operator" pattern.  Each node may declare
a ``validator`` so schema/quality failures are caught before dependents run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NodeStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class DagNode:
    """A single typed unit of work in the plan graph."""

    id: str
    objective: str
    depends_on: set[str] = field(default_factory=set)
    requires: set[str] = field(default_factory=set)  # state keys that must exist
    produces: set[str] = field(default_factory=set)  # state keys this node sets
    payload: Any = None
    status: NodeStatus = NodeStatus.PENDING
    output: Any = None
    attempts: int = 0


@dataclass
class NodeResult:
    """What a runner returns for one node."""

    ok: bool
    output: Any = None
    effects: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class DagRunReport:
    order: list[str] = field(default_factory=list)
    succeeded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    repairs: int = 0
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.skipped

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "order": list(self.order),
            "succeeded": list(self.succeeded),
            "failed": list(self.failed),
            "skipped": list(self.skipped),
            "repairs": self.repairs,
            "state_keys": sorted(self.state),
        }


class DagCycleError(ValueError):
    """Raised when the declared dependencies do not form a DAG."""


Runner = Callable[[DagNode, dict[str, Any]], NodeResult]
Validator = Callable[[Any], bool]


class TaskDAG:
    """A typed, executable plan graph with locality-bounded repair."""

    def __init__(self) -> None:
        self._nodes: dict[str, DagNode] = {}
        self._validators: dict[str, Validator] = {}

    def add_node(
        self,
        node_id: str,
        objective: str,
        *,
        depends_on: Iterable[str] | None = None,
        requires: Iterable[str] | None = None,
        produces: Iterable[str] | None = None,
        payload: Any = None,
        validator: Validator | None = None,
    ) -> DagNode:
        node_id = node_id.strip()
        if not node_id:
            raise ValueError("node_id is required")
        if node_id in self._nodes:
            raise ValueError(f"duplicate node id: {node_id}")
        node = DagNode(
            id=node_id,
            objective=objective,
            depends_on=set(depends_on or ()),
            requires=set(requires or ()),
            produces=set(produces or ()),
            payload=payload,
        )
        self._nodes[node_id] = node
        if validator is not None:
            self._validators[node_id] = validator
        return node

    @property
    def nodes(self) -> dict[str, DagNode]:
        return dict(self._nodes)

    def topological_order(self) -> list[str]:
        """Return node ids in dependency order (Kahn's algorithm)."""

        indegree = {nid: 0 for nid in self._nodes}
        adjacency: dict[str, list[str]] = {nid: [] for nid in self._nodes}
        for node in self._nodes.values():
            for dep in node.depends_on:
                if dep not in self._nodes:
                    raise ValueError(f"node {node.id} depends on unknown node {dep}")
                indegree[node.id] += 1
                adjacency[dep].append(node.id)
        ready = sorted(nid for nid, d in indegree.items() if d == 0)
        order: list[str] = []
        while ready:
            current = ready.pop(0)
            order.append(current)
            for nxt in sorted(adjacency[current]):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
            ready.sort()
        if len(order) != len(self._nodes):
            raise DagCycleError("dependency graph contains a cycle")
        return order

    def descendants(self, node_id: str) -> set[str]:
        """All nodes transitively dependent on *node_id*."""

        children: dict[str, set[str]] = {nid: set() for nid in self._nodes}
        for node in self._nodes.values():
            for dep in node.depends_on:
                children[dep].add(node.id)
        out: set[str] = set()
        stack = list(children.get(node_id, set()))
        while stack:
            current = stack.pop()
            if current in out:
                continue
            out.add(current)
            stack.extend(children[current])
        return out

    def execute(self, runner: Runner, *, max_repairs: int = 2) -> DagRunReport:
        """Execute the DAG, repairing failed nodes' descendants locally."""

        report = DagRunReport()
        state: dict[str, Any] = {}
        report.state = state
        order = self.topological_order()
        report.order = list(order)
        blocked: set[str] = set()

        for node_id in order:
            node = self._nodes[node_id]
            if node_id in blocked:
                node.status = NodeStatus.SKIPPED
                report.skipped.append(node_id)
                continue
            if not node.requires.issubset(state):
                node.status = NodeStatus.SKIPPED
                report.skipped.append(node_id)
                blocked |= self.descendants(node_id)
                continue

            result = self._run_with_repair(node, runner, state, max_repairs, report)
            if result.ok:
                node.status = NodeStatus.SUCCEEDED
                node.output = result.output
                state.update(result.effects)
                for key in node.produces:
                    state.setdefault(key, result.output)
                report.succeeded.append(node_id)
            else:
                node.status = NodeStatus.FAILED
                report.failed.append(node_id)
                # Locality-bounded: only descendants are invalidated, not siblings.
                blocked |= self.descendants(node_id)
        return report

    def _run_with_repair(
        self,
        node: DagNode,
        runner: Runner,
        state: dict[str, Any],
        max_repairs: int,
        report: DagRunReport,
    ) -> NodeResult:
        attempt = 0
        while True:
            node.attempts = attempt + 1
            result = runner(node, state)
            if result.ok and self._validate(node, result.output):
                return result
            if attempt >= max_repairs:
                if result.ok:  # ran cleanly but failed validation
                    return NodeResult(ok=False, output=result.output, error="validation failed")
                return result
            report.repairs += 1
            attempt += 1

    def _validate(self, node: DagNode, output: Any) -> bool:
        validator = self._validators.get(node.id)
        if validator is None:
            return True
        try:
            return bool(validator(output))
        except Exception:
            return False
