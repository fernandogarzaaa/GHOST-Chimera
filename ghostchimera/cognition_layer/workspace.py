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

    def snapshot(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "evidence": list(self.evidence),
            "reflections": list(self.reflections),
        }


class AttentionController:
    """Rank workspace items by relevance, trust, recency, and novelty."""

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
