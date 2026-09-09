"""Phase 2 Experience Layer tests: deterministic, stdlib-only."""

from __future__ import annotations

from ghostchimera.stealth import new_event
from ghostchimera.stealth.experience import ExperienceGraph
from ghostchimera.stealth.prediction import PredictionEngine
from ghostchimera.stealth.workflow_learner import WorkflowLearner


def _proposal_sequence(actor: str = "alex", project: str = "moovsoon") -> list:
    return [
        new_event("email.received", source="gmail", actor=actor, payload={"project": project}),
        new_event("github.commit", source="github", actor=actor, payload={"project": project}),
        new_event("agent.session_started", source="claude", actor=actor, payload={"project": project}),
    ]


def test_experience_graph_links_people_projects_and_sessions() -> None:
    graph = ExperienceGraph()
    for event in _proposal_sequence():
        graph.record_event(event)
    assert "person:alex" in graph.nodes
    assert "project:moovsoon" in graph.nodes
    related = graph.related("person:alex")
    assert any(e.target == "project:moovsoon" and e.relation == "works_on" for e in related)
    assert graph.snapshot()["nodes"] >= 5


def test_workflow_score_rewards_useful_interventions() -> None:
    graph = ExperienceGraph()
    assert graph.workflow_score("proposal_prep") == 0.5  # Laplace prior
    for _ in range(4):
        graph.record_outcome("proposal_prep", useful=True)
    graph.record_outcome("proposal_prep", useful=False)
    assert graph.workflow_score("proposal_prep") > 0.6


def test_learner_discovers_repeated_workflow() -> None:
    learner = WorkflowLearner(min_support=3)
    pattern = ["email.received", "github.commit", "agent.session_started"]
    for _ in range(7):
        for event_type in pattern:
            learner.observe("user-1", event_type)
    hyps = learner.hypotheses()
    assert hyps, "expected at least one learned hypothesis"
    full = [h for h in hyps if list(h.pattern) == pattern]
    assert full and full[0].support >= 7
    matched = learner.match(pattern)
    assert matched is not None
    # Explicit workflows win ties and always match.
    learner.register_explicit("proposal_prep", pattern, ["prepare_context"])
    matched = learner.match(pattern)
    assert matched is not None and matched.explicit


def test_learner_requires_min_support_and_feedback_moves_confidence() -> None:
    learner = WorkflowLearner(min_support=5)
    for _ in range(2):
        learner.observe("u", "email.received")
        learner.observe("u", "agent.session_started")
    assert learner.match(["email.received", "agent.session_started"]) is None
    name = "learned:email.received→agent.session_started"
    before = None
    for _ in range(5):
        learner.observe("u2", "email.received")
        learner.observe("u2", "agent.session_started")
    matched = learner.match(["email.received", "agent.session_started"])
    assert matched is not None
    before = matched.confidence
    learner.observe_outcome(matched.name, useful=False)
    after = [h for h in learner.hypotheses() if h.name == matched.name][0].confidence
    assert after < before
    assert name == matched.name


def test_prediction_engine_is_probabilistic_and_feeds_evaluator() -> None:
    graph = ExperienceGraph()
    for event in _proposal_sequence():
        graph.record_event(event)
    engine = PredictionEngine(graph=graph)
    for event_type in ("email.received", "email.received", "github.commit"):
        engine.observe(event_type)
    learner = WorkflowLearner(min_support=2)
    for _ in range(3):
        for event_type in ("email.received", "github.commit", "agent.session_started"):
            learner.observe("u", event_type)
    hypothesis = learner.match(["email.received", "github.commit", "agent.session_started"])
    preds = engine.predict(["email.received", "github.commit"], hypothesis, limit=5)
    assert preds
    assert all(0.0 <= p.probability <= 1.0 for p in preds)
    assert abs(sum(p.probability for p in preds) - 1.0) < 0.02
    # Predictions are data, not decisions: evaluator still defaults to silence on weak signals.
    from ghostchimera.stealth import Decision, GhostPolicy, StealthEvaluator
    from ghostchimera.stealth.stealth_policy import EvaluationSignals

    top = preds[0]
    decision, _ = StealthEvaluator(GhostPolicy.conservative_default()).evaluate(
        EvaluationSignals(relevance=0.2, confidence=top.probability)
    )
    assert decision == Decision.NONE


def test_experience_rebuild_from_event_log() -> None:
    graph = ExperienceGraph()
    events = _proposal_sequence() * 2
    graph.rebuild_from_events(events)
    assert graph.snapshot()["nodes"] >= 5
    follows = graph.what_normally_follows("email.received")
    assert isinstance(follows, list)
