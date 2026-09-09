"""Prediction Engine: "what is the user probably going to do next?"

Probabilistic only — predictions never become actions. They feed the
Stealth Evaluator, which decides NONE / STORE / PREPARE / INJECT / ACT.
Combines the matched workflow hypothesis, experience-graph successors,
and recency-weighted base rates. Deterministic and cheap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .experience import ExperienceGraph
from .workflow_learner import WorkflowHypothesis


@dataclass(frozen=True)
class Prediction:
    action: str  # predicted next event type or workflow-qualified action
    probability: float
    basis: str  # "workflow" | "experience" | "base_rate"


class PredictionEngine:
    def __init__(self, *, graph: ExperienceGraph | None = None) -> None:
        self.graph = graph or ExperienceGraph()
        self._base_rates: dict[str, int] = {}
        self._total = 0

    def observe(self, event_type: str) -> None:
        self._base_rates[event_type] = self._base_rates.get(event_type, 0) + 1
        self._total += 1

    def predict(
        self,
        recent: list[str],
        hypothesis: WorkflowHypothesis | None = None,
        *,
        limit: int = 5,
    ) -> list[Prediction]:
        scored: dict[str, list[float]] = {}  # action -> [prob, weight]

        def add(action: str, prob: float, basis: str, weight: float) -> None:
            entry = scored.setdefault(action, [0.0, basis])
            entry[0] += prob * weight
            entry[1] = basis  # last basis wins for explainability; keep simple

        if hypothesis is not None:
            for i, nxt in enumerate(hypothesis.expected_next):
                add(f"workflow:{hypothesis.name}:{nxt}", hypothesis.confidence * (0.9**i), "workflow", 1.0)
            # The workflow itself continuing is evidence for its head action.
            if hypothesis.pattern:
                add(f"event:{hypothesis.pattern[-1]}", hypothesis.confidence * 0.3, "workflow", 0.5)

        if recent:
            for action, prob in self.graph.what_normally_follows(recent[-1], limit=limit):
                add(f"event:{action}", prob, "experience", 0.8)

        if self._total:
            for action, count in sorted(self._base_rates.items(), key=lambda kv: kv[1], reverse=True)[:limit]:
                add(f"event:{action}", count / self._total, "base_rate", 0.3)

        add("event:none", 0.21, "base_rate", 0.3)  # "do nothing" prior: silence is often right

        ranked = sorted(scored.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]
        total = sum(prob for _, (prob, _) in ranked) or 1.0
        return [Prediction(action=action, probability=round(prob / total, 3), basis=basis) for action, (prob, basis) in ranked]

    def to_dict(self, predictions: list[Prediction]) -> dict[str, Any]:
        return {"predictions": [{"action": p.action, "p": p.probability, "basis": p.basis} for p in predictions]}


__all__ = ["Prediction", "PredictionEngine"]
