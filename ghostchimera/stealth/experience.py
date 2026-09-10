"""Experience Graph: what Ghost has learned from behavior.

Connects events, facts, people, projects, documents, actions, agent
sessions, workflows, interventions, outcomes, corrections, and
preferences. Answers "what normally happens after something like this?"
— the key distinction from a plain knowledge graph.

Backing strategy: in-memory adjacency with counts + recency (cheap,
deterministic, stdlib-only). Durable MemoryStore / TemporalGraphStore
remain the system of record; this projection can later be rebuilt from
them via ``rebuild_from_events`` without replacement.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .events import Event


@dataclass
class ExperienceNode:
    key: str
    kind: str
    label: str = ""
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    count: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperienceEdge:
    source: str
    target: str
    relation: str
    count: int = 0
    last_seen: float = field(default_factory=time.time)
    confidence: float = 0.5


class ExperienceGraph:
    """Weighted, recency-aware multigraph of user experience."""

    def __init__(self) -> None:
        self.nodes: dict[str, ExperienceNode] = {}
        self.edges: dict[tuple[str, str, str], ExperienceEdge] = {}
        self._successes: dict[str, int] = defaultdict(int)
        self._failures: dict[str, int] = defaultdict(int)

    # -- ingestion ----------------------------------------------------
    def _touch_node(self, key: str, kind: str, label: str = "", *, at: float | None = None) -> ExperienceNode:
        now = at if at is not None else time.time()
        node = self.nodes.get(key)
        if node is None:
            node = ExperienceNode(key=key, kind=kind, label=label or key, first_seen=now)
            self.nodes[key] = node
        node.last_seen = now
        node.count += 1
        if label:
            node.label = label
        return node

    def _touch_edge(self, source: str, target: str, relation: str, *, at: float | None = None) -> ExperienceEdge:
        now = at if at is not None else time.time()
        key = (source, target, relation)
        edge = self.edges.get(key)
        if edge is None:
            edge = ExperienceEdge(source=source, target=target, relation=relation)
            self.edges[key] = edge
        edge.count += 1
        edge.last_seen = now
        # Confidence grows with repeated co-occurrence, capped at 0.99.
        edge.confidence = min(0.99, 0.5 + 0.05 * edge.count)
        return edge

    def record_event(self, event: Event) -> None:
        """Project a normalized event into experience nodes/edges."""
        at = event.timestamp
        event_key = f"event:{event.event_type}"
        self._touch_node(event_key, "event", event.event_type, at=at)
        if event.actor:
            actor_key = f"person:{event.actor}"
            self._touch_node(actor_key, "person", event.actor, at=at)
            self._touch_edge(actor_key, event_key, "participated_in", at=at)
        project = str(event.payload.get("project") or event.payload.get("repository") or "")
        if project:
            project_key = f"project:{project}"
            self._touch_node(project_key, "project", project, at=at)
            self._touch_edge(event_key, project_key, "concerns", at=at)
            if event.actor:
                self._touch_edge(f"person:{event.actor}", project_key, "works_on", at=at)
        if event.session_id:
            session_key = f"session:{event.session_id}"
            self._touch_node(session_key, "agent_session", event.session_id, at=at)
            self._touch_edge(session_key, event_key, "contains", at=at)

    def record_intervention(self, workflow: str, intervention_id: str) -> None:
        wf_key = f"workflow:{workflow}"
        int_key = f"intervention:{intervention_id}"
        self._touch_node(wf_key, "workflow", workflow)
        self._touch_node(int_key, "intervention", intervention_id)
        self._touch_edge(wf_key, int_key, "triggered")

    def record_outcome(self, workflow: str, *, useful: bool) -> None:
        """Feedback loop: successes raise future confidence, failures lower it."""
        if useful:
            self._successes[workflow] += 1
        else:
            self._failures[workflow] += 1

    # -- queries ------------------------------------------------------
    def workflow_score(self, workflow: str) -> float:
        """Useful-intervention rate with Laplace smoothing (precision first)."""
        successes = self._successes.get(workflow, 0)
        failures = self._failures.get(workflow, 0)
        return (successes + 1) / (successes + failures + 2)

    def related(self, key: str, *, limit: int = 10) -> list[ExperienceEdge]:
        """Edges touching *key*, ranked by count then recency."""
        now = time.time()
        scored = []
        for edge in self.edges.values():
            if edge.source != key and edge.target != key:
                continue
            recency = 1.0 / (1.0 + max(0.0, now - edge.last_seen) / 86400.0)
            scored.append((edge.count * (1.0 + recency), edge))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [edge for _, edge in scored[:limit]]

    def what_normally_follows(self, event_type: str, *, limit: int = 5) -> list[tuple[str, float]]:
        """Heuristic successor lookup: event types most often co-occurring
        with *event_type* via shared sessions, weighted by edge confidence."""
        event_key = f"event:{event_type}"
        sessions = {
            edge.source for edge in self.edges.values() if edge.target == event_key and edge.relation == "contains"
        }
        neighbors: dict[str, float] = {}
        for edge in self.edges.values():
            if edge.relation != "contains" or edge.source not in sessions:
                continue
            if edge.target.startswith("event:") and edge.target != event_key:
                neighbors[edge.target] = neighbors.get(edge.target, 0.0) + edge.confidence * edge.count
        for edge in self.related(event_key, limit=50):
            other = edge.target if edge.source == event_key else edge.source
            if other.startswith("event:") and other != event_key:
                neighbors[other] = neighbors.get(other, 0.0) + edge.confidence * edge.count
        ranked = sorted(neighbors.items(), key=lambda item: item[1], reverse=True)
        total = sum(score for _, score in ranked) or 1.0
        return [(key.split("event:", 1)[1], score / total) for key, score in ranked[:limit]]

    def rebuild_from_events(self, events: list[Event]) -> None:
        for event in events:
            self.record_event(event)

    def snapshot(self) -> dict[str, Any]:
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "workflows": {
                name: {"useful_rate": round(self.workflow_score(name), 3)}
                for name in set(self._successes) | set(self._failures)
            },
        }


__all__ = ["ExperienceEdge", "ExperienceGraph", "ExperienceNode"]
