"""Inspectable consciousness-inspired workspace primitives.

These classes do not claim subjective consciousness. They provide explicit
state surfaces for identity, goals, evidence, attention, and reflection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class SelfModel:
    """Agent self-state: capabilities, limits, and active goals."""

    identity: str = "ghost-chimera"
    capabilities: dict[str, str] = field(default_factory=dict)
    limits: dict[str, str] = field(default_factory=dict)
    goals: dict[str, str] = field(default_factory=dict)

    def add_capability(self, name: str, description: str) -> None:
        self.capabilities[name] = description

    def add_limit(self, name: str, description: str) -> None:
        self.limits[name] = description

    def set_goal(self, name: str, description: str) -> None:
        self.goals[name] = description

    def query(self, key: str) -> str | None:
        if key in self.capabilities:
            return self.capabilities[key]
        if key in self.limits:
            return self.limits[key]
        if key in self.goals:
            return self.goals[key]
        return None

    def clear_goals(self) -> None:
        self.goals.clear()

    def snapshot(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "capabilities": dict(self.capabilities),
            "limits": dict(self.limits),
            "goals": dict(self.goals),
        }


@dataclass
class WorkingMemory:
    """Task-local workspace for evidence, decisions, and reflections."""

    task: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    reflections: list[dict[str, Any]] = field(default_factory=list)

    def add_evidence(self, source: str, content: str, *, confidence: float = 0.5) -> None:
        self.evidence.append(
            {
                "source": source,
                "content": content,
                "confidence": max(0.0, min(1.0, float(confidence))),
                "timestamp": _now(),
            }
        )

    def query_evidence(self, source: str | None = None) -> list[dict]:
        if source:
            return [e for e in self.evidence if e.get("source") == source]
        return list(self.evidence)

    def compact_high_confidence(self, threshold: float = 0.8) -> int:
        before = len(self.evidence)
        self.evidence = [e for e in self.evidence if e.get("confidence", 0) >= threshold]
        return before - len(self.evidence)

    def clear_evidence(self) -> None:
        self.evidence.clear()

    def snapshot(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "evidence": list(self.evidence),
            "reflections": list(self.reflections),
        }


class AttentionController:
    """Rank workspace items by relevance, trust, recency, and novelty."""

    def rank_backends(self, backends: list[dict], context: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for b in backends:
            item = dict(b)
            item["relevance"] = context.get("task_relevance", 0.5)
            item["trust"] = b.get("reliability", 0.5)
            item["recency"] = 1.0 / (1.0 + context.get("latency_ms", 0) / 1000.0)
            item["novelty"] = context.get("novelty", 0.0)
            items.append(item)
        return self.rank(items)

    def rank(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        for item in items:
            relevance = float(item.get("relevance", 0.0))
            trust = float(item.get("trust", 0.0))
            recency = float(item.get("recency", 0.0))
            novelty = float(item.get("novelty", 0.0))
            score = (relevance * 0.45) + (trust * 0.30) + (recency * 0.20) + (novelty * 0.05)
            enriched = dict(item)
            enriched["attention_score"] = round(max(0.0, min(1.0, score)), 6)
            ranked.append(enriched)
        ranked.sort(key=lambda item: item["attention_score"], reverse=True)
        return ranked


class ReflectionEngine:
    """Record post-action reflections into working memory."""

    def record(self, memory: WorkingMemory, *, action: str, outcome: str, confidence: float = 0.5) -> None:
        memory.reflections.append(
            {
                "action": action,
                "outcome": outcome,
                "confidence": max(0.0, min(1.0, float(confidence))),
                "timestamp": _now(),
            }
        )

    def clear(self, memory: WorkingMemory) -> None:
        memory.reflections.clear()
