"""Stealth Kernel tests: deterministic, stdlib-only, no external services."""

from __future__ import annotations

import pytest

from ghostchimera.stealth import (
    AutonomyLevel,
    Decision,
    EventBus,
    GhostPolicy,
    InterventionOutcome,
    InterventionState,
    StealthEvaluator,
    StealthHookRegistry,
    WorldState,
    define_hook,
    new_event,
    read_only_consumer,
)
from ghostchimera.stealth.event_bus import read_only_consumer as roc2
from ghostchimera.stealth.hooks import StealthHook
from ghostchimera.stealth.intervention import Intervention


def test_event_normalization_and_idempotent_bus() -> None:
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe("email.received", lambda e: seen.append(e.event_id))
    evt = new_event("  EMAIL.Received ", source="gmail", actor="alex")
    assert evt.event_type == "email.received"
    assert bus.emit(evt) is True
    assert bus.emit(evt) is False  # duplicate id -> dropped
    assert seen == [evt.event_id]
    assert bus.processed == 1
    assert bus.dropped_duplicates == 1


def test_event_out_of_order_and_replay_read_only() -> None:
    bus = EventBus()
    calls: list[str] = []

    @read_only_consumer
    def safe_consumer(event) -> None:
        calls.append(event.event_id)

    def mutating_consumer(event) -> None:
        calls.append("MUTATE-" + event.event_id)

    bus.subscribe("github.commit", safe_consumer)
    bus.subscribe("github.commit", mutating_consumer)
    events = [new_event("github.commit", source="github") for _ in range(3)]
    # emit in reverse arrival order: bus must accept all (no ordering requirement)
    for evt in reversed(events):
        assert bus.emit(evt) is True
    assert bus.processed == 3
    calls.clear()
    assert bus.replay(events, read_only=True) == 3
    assert all(not c.startswith("MUTATE") for c in calls)
    assert len(calls) == 3


def test_world_state_temporal_semantics() -> None:
    ws = WorldState()
    ws.assert_fact("alex", "works_on", "project-x", confidence=0.9, provenance={"src": "email"})
    assert len(ws.active_facts("alex")) == 1
    assert ws.retract("alex", "works_on", "project-x") == 1
    assert ws.active_facts("alex") == []
    ws.observe_event("email.received", {"sender": "alex", "project": "project-x"})
    facts = ws.active_facts("alex")
    assert any(f.predicate == "observed_in" for f in facts)


def test_stealth_evaluator_defaults_to_silence() -> None:
    from ghostchimera.stealth.stealth_policy import EvaluationSignals

    evaluator = StealthEvaluator(GhostPolicy.conservative_default())
    decision, _ = evaluator.evaluate(EvaluationSignals(relevance=0.1, confidence=0.2))
    assert decision == Decision.NONE
    # high confidence + high relevance -> PREPARE (never ACT at default L1)
    decision, _ = evaluator.evaluate(
        EvaluationSignals(relevance=0.94, confidence=0.92, user_benefit=0.9, cost=0.1, risk=0.05)
    )
    assert decision in (Decision.PREPARE, Decision.INJECT)
    # secret privacy class denied at hook level; evaluator denies privacy_ok=False
    decision, _ = evaluator.evaluate(
        EvaluationSignals(relevance=0.99, confidence=0.99, user_benefit=1.0, privacy_ok=False)
    )
    assert decision == Decision.NONE
    # external side effect with medium risk -> ASK or STORE, never direct ACT
    policy = GhostPolicy(autonomy=AutonomyLevel.PREPARE)
    decision, _ = StealthEvaluator(policy).evaluate(
        EvaluationSignals(
            relevance=0.9, confidence=0.8, user_benefit=0.8, risk=0.5, external_side_effect=True
        )
    )
    assert decision in (Decision.ASK, Decision.STORE)


def test_intervention_lifecycle_and_illegal_transition() -> None:
    intervention = Intervention(trigger_event_id="evt-1", workflow="meeting_prep", confidence=0.93)
    assert intervention.state == InterventionState.CREATED
    intervention.transition(InterventionState.QUEUED)
    intervention.transition(InterventionState.PREPARING)
    intervention.transition(InterventionState.READY)
    intervention.transition(InterventionState.INJECTED)
    intervention.transition(InterventionState.CONSUMED)
    intervention.record_outcome(InterventionOutcome.USEFUL)
    assert intervention.state == InterventionState.OUTCOME
    assert intervention.explain()["workflow"] == "meeting_prep"
    with pytest.raises(ValueError):
        Intervention().transition(InterventionState.INJECTED)  # CREATED -> INJECTED illegal


def test_stealth_hook_end_to_end_prepare_only() -> None:
    evaluator = StealthEvaluator(GhostPolicy(autonomy=AutonomyLevel.PREPARE, minimum_confidence=0.8))
    registry = StealthHookRegistry(evaluator)

    def recall(event, context):
        return {"recent_correspondence": [event.payload.get("subject", "")]}

    hook = StealthHook(
        name="proposal-preparation",
        event_type="email.received",
        workflow="proposal_preparation",
        min_confidence=0.8,
        actions=[recall],
    )
    registry.register(hook)
    evt = new_event(
        "email.received",
        source="gmail",
        payload={"subject": "Moovsoon proposal", "relevance": 0.95, "confidence": 0.93, "benefit": 0.9},
        confidence=0.93,
    )
    interventions = registry.handle(evt)
    assert len(interventions) == 1
    assert interventions[0].context["recent_correspondence"] == ["Moovsoon proposal"]
    # low confidence event -> silence
    quiet = new_event("email.received", source="gmail", confidence=0.3)
    assert registry.handle(quiet) == []
    # outcome feedback moves confidence
    hook.observe_outcome("useful", useful=True)
    assert hook.outcome_feedback["proposal_preparation"] > 0


def test_define_hook_from_yaml_dict() -> None:
    spec = {
        "hook": {
            "name": "proposal-preparation",
            "when": {"event": "email.received"},
            "detect": {"workflow": "proposal_preparation", "confidence": ">0.85"},
            "inject": {"into": "next_agent_session"},
            "autonomy": {"mode": "prepare_only"},
        }
    }
    hook = define_hook(spec)
    assert hook.name == "proposal-preparation"
    assert hook.event_type == "email.received"
    assert hook.min_confidence == pytest.approx(0.85)
    assert hook.autonomy_mode == "prepare_only"


def test_bus_survives_consumer_exception() -> None:
    bus = EventBus()

    def bad_consumer(event) -> None:
        raise RuntimeError("boom")

    good: list[str] = []
    bus.subscribe("file.modified", bad_consumer)
    bus.subscribe("file.modified", lambda e: good.append(e.event_id))
    assert bus.emit(new_event("file.modified", source="fs")) is True
    assert len(good) == 1
    assert roc2 is read_only_consumer
