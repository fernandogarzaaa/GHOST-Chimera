"""Test-time compute strategies for small local models.

A recurring 2026 finding: a small model that *thinks longer* at inference time
(sampling multiple candidates and selecting among them) can outperform a much
larger model that answers in a single pass.  This is the most direct lever for
Ghost Chimera's "flawless on 4GB/8GB" goal — it trades a little extra local
compute for accuracy instead of a bigger model that will not fit.

This module is deliberately model-agnostic: it operates over an injected
``sampler`` callable ``(prompt) -> str`` and optional ``scorer``/``normalizer``
callables, so it works with the llama.cpp runtime, a remote provider, or a test
double.  Three strategies are provided:

* **best_of_n** — sample N candidates, keep the highest scorer score.
* **self_consistency** — sample N candidates, return the majority answer
  (Wang et al. self-consistency), optionally after normalization.
* **weighted_best_of_n** — combine verifier score and answer agreement.

A confidence gate (:func:`should_scale`) lets callers spend the extra samples
only on hard/low-confidence tasks and keep cheap tasks single-shot.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Sampler = Callable[[str], str]
Scorer = Callable[[str], float]
Normalizer = Callable[[str], str]


@dataclass
class InferenceScaleResult:
    """The selected answer plus the evidence behind the selection."""

    answer: str
    strategy: str
    samples: list[str]
    confidence: float
    scores: list[float] = field(default_factory=list)
    vote_share: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "strategy": self.strategy,
            "samples": list(self.samples),
            "confidence": round(self.confidence, 6),
            "scores": [round(s, 6) for s in self.scores],
            "vote_share": round(self.vote_share, 6),
        }


def _clamp_n(n: int) -> int:
    return max(1, min(int(n), 64))


def _collect(sampler: Sampler, prompt: str, n: int) -> list[str]:
    samples = [str(sampler(prompt)) for _ in range(_clamp_n(n))]
    return [s for s in samples if s.strip()]


def best_of_n(
    sampler: Sampler,
    prompt: str,
    *,
    n: int = 4,
    scorer: Scorer,
) -> InferenceScaleResult:
    """Sample *n* candidates and return the one the *scorer* rates highest."""

    samples = _collect(sampler, prompt, n)
    if not samples:
        return InferenceScaleResult(answer="", strategy="best_of_n", samples=[], confidence=0.0)
    scores = [float(scorer(s)) for s in samples]
    best_idx = max(range(len(samples)), key=lambda i: scores[i])
    total = sum(max(0.0, s) for s in scores)
    confidence = (max(0.0, scores[best_idx]) / total) if total > 0 else 1.0 / len(samples)
    return InferenceScaleResult(
        answer=samples[best_idx],
        strategy="best_of_n",
        samples=samples,
        confidence=confidence,
        scores=scores,
    )


def self_consistency(
    sampler: Sampler,
    prompt: str,
    *,
    n: int = 5,
    normalizer: Normalizer | None = None,
) -> InferenceScaleResult:
    """Sample *n* candidates and return the majority answer (self-consistency)."""

    samples = _collect(sampler, prompt, n)
    if not samples:
        return InferenceScaleResult(answer="", strategy="self_consistency", samples=[], confidence=0.0)
    norm = normalizer or (lambda s: s.strip())
    counts = Counter(norm(s) for s in samples)
    winner, votes = counts.most_common(1)[0]
    vote_share = votes / len(samples)
    # Return the first raw sample matching the winning normalized form.
    answer = next((s for s in samples if norm(s) == winner), winner)
    return InferenceScaleResult(
        answer=answer,
        strategy="self_consistency",
        samples=samples,
        confidence=vote_share,
        vote_share=vote_share,
    )


def weighted_best_of_n(
    sampler: Sampler,
    prompt: str,
    *,
    n: int = 5,
    scorer: Scorer,
    normalizer: Normalizer | None = None,
) -> InferenceScaleResult:
    """Weighted majority: sum verifier scores per normalized answer, pick the max.

    Combines self-consistency agreement with verifier quality, which is more
    robust than either alone when candidates are noisy.
    """

    samples = _collect(sampler, prompt, n)
    if not samples:
        return InferenceScaleResult(answer="", strategy="weighted_best_of_n", samples=[], confidence=0.0)
    norm = normalizer or (lambda s: s.strip())
    scores = [max(0.0, float(scorer(s))) for s in samples]
    weight: dict[str, float] = {}
    representative: dict[str, str] = {}
    for sample, score in zip(samples, scores, strict=True):
        key = norm(sample)
        weight[key] = weight.get(key, 0.0) + score
        representative.setdefault(key, sample)
    total = sum(weight.values())
    winner = max(weight, key=lambda k: weight[k])
    confidence = (weight[winner] / total) if total > 0 else 1.0 / len(samples)
    return InferenceScaleResult(
        answer=representative[winner],
        strategy="weighted_best_of_n",
        samples=samples,
        confidence=confidence,
        scores=scores,
        vote_share=sum(1 for s in samples if norm(s) == winner) / len(samples),
    )


def should_scale(confidence: float, *, threshold: float = 0.7) -> bool:
    """Return True when a single-shot answer is too uncertain to trust.

    Gate test-time compute on this so cheap/high-confidence tasks stay single
    pass and only hard tasks pay for extra samples.
    """

    return float(confidence) < float(threshold)
