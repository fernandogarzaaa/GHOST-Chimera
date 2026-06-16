"""Tests for test-time compute strategies."""

from __future__ import annotations

import itertools

from ghostchimera.model_layer.test_time_compute import (
    best_of_n,
    self_consistency,
    should_scale,
    weighted_best_of_n,
)


def _cycle_sampler(values):
    it = itertools.cycle(values)
    return lambda _prompt: next(it)


def test_best_of_n_picks_highest_scorer():
    sampler = _cycle_sampler(["short", "a much longer better answer", "mid one"])
    result = best_of_n(sampler, "q", n=3, scorer=lambda s: float(len(s)))
    assert result.answer == "a much longer better answer"
    assert result.strategy == "best_of_n"
    assert len(result.samples) == 3
    assert 0.0 < result.confidence <= 1.0


def test_self_consistency_majority_vote():
    sampler = _cycle_sampler(["42", "42", "7", "42", "7"])
    result = self_consistency(sampler, "q", n=5)
    assert result.answer == "42"
    assert result.vote_share == 3 / 5
    assert result.confidence == 3 / 5


def test_self_consistency_with_normalizer():
    sampler = _cycle_sampler(["Yes.", "yes", " YES ", "no"])
    result = self_consistency(sampler, "q", n=4, normalizer=lambda s: s.strip().lower().rstrip("."))
    assert result.answer in {"Yes.", "yes", " YES "}
    assert result.vote_share == 3 / 4


def test_weighted_best_of_n_combines_votes_and_scores():
    # "good" appears twice with high score; "bad" appears 3x with low score.
    sampler = _cycle_sampler(["bad", "good", "bad", "good", "bad"])
    scorer = lambda s: 10.0 if s == "good" else 1.0  # noqa: E731
    result = weighted_best_of_n(sampler, "q", n=5, scorer=scorer)
    assert result.answer == "good"  # 2*10=20 weight beats 3*1=3
    assert result.strategy == "weighted_best_of_n"


def test_empty_samples_handled():
    result = best_of_n(lambda _p: "   ", "q", n=3, scorer=lambda s: 1.0)
    assert result.answer == ""
    assert result.confidence == 0.0


def test_should_scale_gate():
    assert should_scale(0.4) is True
    assert should_scale(0.9) is False
    assert should_scale(0.7, threshold=0.7) is False
    assert should_scale(0.69, threshold=0.7) is True


def test_result_as_dict_is_serializable():
    sampler = _cycle_sampler(["a", "a", "b"])
    result = self_consistency(sampler, "q", n=3)
    d = result.as_dict()
    assert d["answer"] == "a"
    assert set(d) >= {"answer", "strategy", "samples", "confidence", "vote_share"}
