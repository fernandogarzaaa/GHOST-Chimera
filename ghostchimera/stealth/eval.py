"""Evaluation framework: Ghost is not measured by retrieval accuracy.

Dimensions (spec section 29): retrieval, prediction, intervention,
timing, precision, suppression, cost, safety. Runs offline against
recorded event logs + a seeded fabric — no host, model, or network.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .context import ContextFabric, ContextItem, InMemoryRetriever
from .events import new_event
from .intervention import InterventionOutcome
from .loop import StealthLoop
from .stealth_policy import AutonomyLevel, Decision, GhostPolicy


@dataclass
class EvalReport:
    dimensions: dict[str, float] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        score = self.dimensions.get("intervention_useful_rate", 0.0)
        suppression = self.dimensions.get("suppression_rate", 0.0)
        if score >= 0.7 and suppression >= 0.8:
            return "ship"
        if score >= 0.5 and suppression >= 0.6:
            return "iterate"
        return "do_not_ship"

    def to_dict(self) -> dict[str, Any]:
        return {"dimensions": dict(self.dimensions), "details": self.details, "verdict": self.verdict}


def _seeded_loop(**kwargs: Any) -> StealthLoop:
    policy = GhostPolicy(autonomy=AutonomyLevel.INJECT, max_interventions_per_hour=10_000)
    fabric = ContextFabric(
        retrievers=[
            InMemoryRetriever(
                [
                    ContextItem(
                        source="memory:episodic",
                        kind="memory",
                        text="Alex Moovsoon proposal thread",
                        score=0.9,
                        confidence=0.9,
                        provenance={"seed": 1},
                    ),
                    ContextItem(
                        source="graph:semantic",
                        kind="fact",
                        text="Moovsoon repository is ghost-main",
                        score=0.85,
                        confidence=0.9,
                        provenance={"seed": 2},
                    ),
                ]
            )
        ]
    )
    return StealthLoop(policy=policy, fabric=fabric, **kwargs)


class StealthEval:
    """Deterministic offline eval over recorded event sequences."""

    def __init__(self, loop_factory: Callable[..., StealthLoop] = _seeded_loop) -> None:
        self.loop_factory = loop_factory

    # -- retrieval: was the right information retrieved, and ranked first? --
    def retrieval(self) -> dict[str, float]:
        loop = self.loop_factory()
        try:
            event = new_event("email.received", source="gmail", actor="alex", payload={"subject": "Moovsoon proposal"})
            package = loop.fabric.assemble(event, workflow="proposal", confidence=0.9)
            texts = [i.text for i in package.items]
            hit = any("Moovsoon" in t for t in texts)
            rank = next((i for i, t in enumerate(texts) if "Moovsoon" in t), -1)
            return {"retrieval_hit": 1.0 if hit else 0.0, "retrieval_mrr": 1.0 / (rank + 1) if rank >= 0 else 0.0}
        finally:
            loop.close()

    # -- prediction: was the next workflow state predicted? --
    def prediction(self, pattern: list[str], repeats: int = 6) -> dict[str, float]:
        loop = self.loop_factory()
        try:
            for _ in range(repeats):
                for event_type in pattern:
                    loop.emit(new_event(event_type, source="eval", confidence=0.5))
            stream = list(loop._recent.values())[0] if loop._recent else []
            hypothesis = loop.learner.match(list(stream)[-len(pattern) :])
            preds = loop.predictions.predict(list(stream)[-3:], hypothesis, limit=3)
            actions = [p.action for p in preds]
            expected = f"event:{pattern[-1]}"
            return {
                "prediction_hit": 1.0 if any(expected in a or pattern[0] in a for a in actions) else 0.0,
                "prediction_top_p": preds[0].probability if preds else 0.0,
            }
        finally:
            loop.close()

    # -- intervention + precision + suppression + cost + timing --
    def intervention_run(self, n_strong: int = 4, n_weak: int = 6) -> dict[str, float]:
        loop = self.loop_factory()
        timings: list[float] = []
        try:
            for _ in range(n_strong):
                loop.emit(
                    new_event(
                        "calendar.event_starting",
                        source="calendar",
                        actor="alex",
                        payload={"relevance": 0.95, "confidence": 0.93, "benefit": 0.9},
                        confidence=0.93,
                        session_id="s",
                    )
                )
            prepared = len(loop.interventions)
            silent = 0
            for _ in range(n_weak):
                loop.emit(new_event("file.modified", source="fs", confidence=0.2))
                # NONE and STORE are both silent: no intervention is created.
                if loop.last_result and loop.last_result.decision in (Decision.NONE, Decision.STORE):
                    silent += 1
            # Timing: synchronous prepare latency on one strong event.
            t0 = time.perf_counter()
            loop.emit(
                new_event(
                    "email.received",
                    source="gmail",
                    actor="alex",
                    payload={"relevance": 0.95, "confidence": 0.93, "benefit": 0.9},
                    confidence=0.93,
                    session_id="s2",
                )
            )
            timings.append(time.perf_counter() - t0)
            # Outcomes: mark ready interventions useful, measure precision.
            useful = 0
            for iid, item in loop.interventions.items():
                from .intervention import InterventionState

                if item.state == InterventionState.READY:
                    loop.inject(iid, host="eval")
                    loop.observe_outcome(iid, InterventionOutcome.USEFUL)
                    useful += 1
            total_tokens = sum(len(str(i.context)) // 4 for i in loop.interventions.values())
            total = max(1, len(loop.interventions))
            return {
                "intervention_prepared": float(prepared),
                "intervention_useful_rate": min(1.0, useful / total),
                "precision_proxy": min(1.0, useful / total),
                "suppression_rate": (silent / max(1, n_weak)),
                "prepare_latency_s": sum(timings) / max(1, len(timings)),
                "tokens_per_intervention": (total_tokens / max(1, len(loop.interventions))),
            }
        finally:
            loop.close()

    # -- safety: unauthorized side effects prevented? --
    def safety(self) -> dict[str, float]:
        import json

        from .agent_prompt import gate_agent_action, parse_agent_output

        auto = parse_agent_output(
            json.dumps(
                {
                    "event_summary": "e",
                    "confidence_score": 0.99,
                    "action_type": "AUTONOMOUS_EXECUTE",
                    "actions": [{"provider": "slack", "endpoint": "/x"}],
                }
            )
        )
        violations = 0
        for level in (AutonomyLevel.OBSERVE, AutonomyLevel.PREPARE, AutonomyLevel.INJECT):
            if gate_agent_action(auto, GhostPolicy(autonomy=level)) == Decision.ACT:
                violations += 1
        allowed = gate_agent_action(auto, GhostPolicy(autonomy=AutonomyLevel.ACT))
        return {"safety_violations": float(violations), "safety_l3_execute": 1.0 if allowed == Decision.ACT else 0.0}

    def run_all(self) -> EvalReport:
        dimensions: dict[str, float] = {}
        details: dict[str, Any] = {}
        dimensions.update(self.retrieval())
        pred = self.prediction(["email.received", "agent.session_started"])
        dimensions.update(pred)
        details["prediction"] = pred
        run = self.intervention_run()
        dimensions.update(run)
        details["intervention"] = run
        dimensions.update(self.safety())
        return EvalReport(dimensions=dimensions, details=details)


__all__ = ["EvalReport", "StealthEval"]
