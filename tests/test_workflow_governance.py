"""Tests for workflow maturity and dynamic autonomy governance."""

from __future__ import annotations

from ghostchimera.stealth import (
    MaturityThresholds,
    StealthLoop,
    WorkflowAutonomyGovernor,
    WorkflowMaturity,
    WorkflowMaturityTracker,
    new_event,
)
from ghostchimera.stealth.stealth_policy import Decision


def _tracker() -> WorkflowMaturityTracker:
    return WorkflowMaturityTracker(
        MaturityThresholds(
            candidate_proposals=2,
            validating_assists=2,
            confirmed_successes=2,
            autonomous_successes=3,
            degraded_failures=2,
            suspended_failures=3,
        )
    )


def _strong_file_event() -> object:
    return new_event(
        "file.modified",
        source="fs",
        actor="alex",
        payload={"relevance": 0.9, "confidence": 0.9, "benefit": 0.9},
        session_id="governance-check",
        confidence=0.9,
    )


def test_maturity_advances_from_proposals_assists_and_successes() -> None:
    tracker = _tracker()

    assert tracker.state("invoice").maturity == WorkflowMaturity.OBSERVED
    tracker.note_proposal("invoice")
    assert tracker.note_proposal("invoice") == WorkflowMaturity.CANDIDATE
    tracker.note_assistance("invoice")
    assert tracker.note_assistance("invoice") == WorkflowMaturity.VALIDATING
    tracker.note_success("invoice")
    assert tracker.note_success("invoice") == WorkflowMaturity.CONFIRMED
    assert tracker.note_approval("invoice") == WorkflowMaturity.APPROVED
    assert tracker.note_success("invoice") == WorkflowMaturity.AUTONOMOUS


def test_maturity_degrades_recovers_and_suspends_on_rejection() -> None:
    tracker = _tracker()

    tracker.note_proposal("deploy")
    tracker.note_failure("deploy")
    assert tracker.note_failure("deploy") == WorkflowMaturity.DEGRADED
    assert tracker.note_failure("deploy") == WorkflowMaturity.SUSPENDED
    assert tracker.reinstate("deploy") == WorkflowMaturity.VALIDATING
    assert tracker.note_rejection("deploy") == WorkflowMaturity.SUSPENDED


def test_governor_constrains_decisions_by_maturity() -> None:
    governor = WorkflowAutonomyGovernor(_tracker())

    assert governor.govern(Decision.ACT, "new").decision == Decision.PREPARE
    governor.tracker.note_proposal("assisted")
    governor.tracker.note_proposal("assisted")
    governor.tracker.note_assistance("assisted")
    governor.tracker.note_assistance("assisted")
    assert governor.govern(Decision.ACT, "assisted").decision == Decision.INJECT
    assert governor.govern(Decision.ASK, "assisted").decision == Decision.STORE
    governor.tracker.note_success("assisted")
    governor.tracker.note_success("assisted")
    governor.tracker.note_approval("assisted")
    assert governor.govern(Decision.ACT, "assisted").decision == Decision.ACT
    governor.tracker.note_failure("blocked")
    governor.tracker.note_failure("blocked")
    assert governor.govern(Decision.PREPARE, "blocked").decision == Decision.STORE
    governor.tracker.note_rejection("blocked")
    assert governor.govern(Decision.STORE, "blocked").decision == Decision.NONE


def test_suspended_workflow_is_silent_in_loop() -> None:
    loop = StealthLoop()
    try:
        loop.emit(_strong_file_event())
        first = loop.last_result
        assert first is not None
        assert first.decision == Decision.PREPARE
        assert first.intervention_id != ""
        workflow = loop.interventions[first.intervention_id].workflow

        loop.maturity.note_rejection(workflow)
        loop.emit(_strong_file_event())
        second = loop.last_result
        assert second is not None
        assert second.decision == Decision.NONE
        assert second.intervention_id == ""
        assert second.trace["governance"]["maturity"] == WorkflowMaturity.SUSPENDED.value
    finally:
        loop.close()
