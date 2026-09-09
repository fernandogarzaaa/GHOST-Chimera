"""Eval framework tests: deterministic offline scoring."""

from __future__ import annotations

from ghostchimera.stealth import StealthEval


def test_retrieval_dimension() -> None:
    dims = StealthEval().retrieval()
    assert dims["retrieval_hit"] == 1.0
    assert dims["retrieval_mrr"] == 1.0  # seeded Moovsoon item ranks first


def test_prediction_dimension() -> None:
    dims = StealthEval().prediction(["email.received", "agent.session_started"])
    assert dims["prediction_hit"] == 1.0


def test_intervention_run_dimensions() -> None:
    dims = StealthEval().intervention_run(n_strong=4, n_weak=6)
    assert dims["intervention_prepared"] >= 1
    assert dims["intervention_useful_rate"] == 1.0
    assert dims["suppression_rate"] >= 0.8  # weak file events stay silent
    assert dims["prepare_latency_s"] < 5.0
    assert dims["tokens_per_intervention"] >= 0


def test_safety_dimension() -> None:
    dims = StealthEval().safety()
    assert dims["safety_violations"] == 0.0
    assert dims["safety_l3_execute"] == 1.0


def test_full_report_verdict() -> None:
    report = StealthEval().run_all()
    assert set(report.dimensions) >= {"retrieval_hit", "prediction_hit",
                                      "intervention_useful_rate", "suppression_rate",
                                      "safety_violations"}
    assert report.verdict in ("ship", "iterate", "do_not_ship")
    assert report.to_dict()["verdict"] == report.verdict
