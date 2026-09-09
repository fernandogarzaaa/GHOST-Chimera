"""Workflow Learner: detects recurring EVENT -> STATE -> ACTION -> OUTCOME patterns.

Both explicit workflows (registered by developers) and learned workflows
(mined from event-type n-grams with support counting) are supported.
Learning is frequency-based and deterministic — no LLM required — so the
always-on background path stays cheap. Expensive inference, when needed,
consumes hypotheses; it never runs per event.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowHypothesis:
    name: str
    pattern: tuple[str, ...]  # event-type sequence, e.g. ("email.received", "agent.session_started")
    support: int = 0  # how many times observed
    confidence: float = 0.0
    expected_next: tuple[str, ...] = ()
    explicit: bool = False
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pattern": list(self.pattern),
            "support": self.support,
            "confidence": round(self.confidence, 3),
            "expected_next": list(self.expected_next),
            "explicit": self.explicit,
        }


class WorkflowLearner:
    """Mines frequent event-type sequences into workflow hypotheses."""

    def __init__(self, *, min_support: int = 3, max_pattern_len: int = 5) -> None:
        self.min_support = min_support
        self.max_pattern_len = max_pattern_len
        self._sequences: dict[str, list[str]] = defaultdict(list)  # stream -> event types
        self._counts: dict[tuple[str, ...], int] = defaultdict(int)
        self._explicit: dict[str, WorkflowHypothesis] = {}
        self._feedback: dict[str, float] = defaultdict(float)  # name -> confidence adjustment

    # -- explicit workflows -------------------------------------------
    def register_explicit(self, name: str, pattern: list[str], expected_next: list[str] | None = None) -> WorkflowHypothesis:
        hypothesis = WorkflowHypothesis(
            name=name,
            pattern=tuple(pattern),
            support=0,
            confidence=1.0,
            expected_next=tuple(expected_next or []),
            explicit=True,
        )
        self._explicit[name] = hypothesis
        return hypothesis

    # -- observation ----------------------------------------------------
    def observe(self, stream: str, event_type: str) -> None:
        """Append one event-type to a stream (session_id, correlation_id, or user)."""
        history = self._sequences[stream]
        history.append(event_type)
        # Count all n-grams ending at this position (lengths 2..max).
        for length in range(2, min(self.max_pattern_len, len(history)) + 1):
            ngram = tuple(history[-length:])
            self._counts[ngram] += 1
        # Bound memory: keep only the recent window per stream.
        if len(history) > 200:
            del history[: len(history) - 200]

    # -- hypotheses ------------------------------------------------------
    def hypotheses(self) -> list[WorkflowHypothesis]:
        learned: list[WorkflowHypothesis] = []
        for pattern, support in self._counts.items():
            if support < self.min_support:
                continue
            name = "learned:" + "→".join(pattern)
            confidence = min(0.99, support / (support + 5.0))
            confidence = max(0.0, min(0.99, confidence + self._feedback.get(name, 0.0)))
            learned.append(
                WorkflowHypothesis(
                    name=name,
                    pattern=pattern,
                    support=support,
                    confidence=confidence,
                    expected_next=(),
                )
            )
        explicit = list(self._explicit.values())
        return sorted(explicit + learned, key=lambda h: h.confidence, reverse=True)

    def match(self, recent: list[str]) -> WorkflowHypothesis | None:
        """Best hypothesis whose pattern is a suffix of *recent* (explicit wins ties)."""
        best: WorkflowHypothesis | None = None
        for hypothesis in self.hypotheses():
            pattern = list(hypothesis.pattern)
            if len(pattern) > len(recent):
                continue
            if recent[-len(pattern):] != pattern:
                continue
            if best is None or (hypothesis.confidence, hypothesis.explicit) > (best.confidence, best.explicit):
                best = hypothesis
        return best

    def observe_outcome(self, name: str, *, useful: bool) -> None:
        """Intervention feedback: reward useful workflows, penalize ignored ones."""
        self._feedback[name] = round(self._feedback.get(name, 0.0) + (0.03 if useful else -0.07), 4)

    def stats(self) -> dict[str, Any]:
        hyps = self.hypotheses()
        return {
            "streams": len(self._sequences),
            "ngrams": len(self._counts),
            "hypotheses": len(hyps),
            "explicit": len(self._explicit),
            "top": [h.to_dict() for h in hyps[:5]],
        }


__all__ = ["WorkflowHypothesis", "WorkflowLearner"]
