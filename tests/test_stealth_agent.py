"""Stealth BPO/VA agent contract tests: prompt, parse, policy gate."""

from __future__ import annotations

import json

import pytest

from ghostchimera.stealth import (
    AgentActionType,
    AutonomyLevel,
    Decision,
    GhostPolicy,
    gate_agent_action,
    parse_agent_output,
    render_system_prompt,
)


def test_render_system_prompt_fills_all_slots() -> None:
    text = render_system_prompt(
        agent_name="Maria",
        integrations=["slack", "google-mail"],
        event_payload={"from": "client@example.com", "intent": "reschedule"},
    )
    assert "{{" not in text
    assert "Maria" in text and "slack, google-mail" in text
    assert '"intent": "reschedule"' in text


def test_parse_agent_output_valid_and_violations() -> None:
    good = parse_agent_output(
        json.dumps(
            {
                "event_summary": "Client asks to reschedule.",
                "confidence_score": 0.95,
                "action_type": "AUTONOMOUS_EXECUTE",
                "actions": [
                    {
                        "provider": "google-mail",
                        "endpoint": "/users/me/messages/send",
                        "payload": {"to": "c@example.com"},
                    }
                ],
            }
        )
    )
    assert good.action_type == AgentActionType.AUTONOMOUS_EXECUTE
    assert good.confidence_score == 0.95
    with pytest.raises(ValueError):
        parse_agent_output("not json {")
    with pytest.raises(ValueError):
        parse_agent_output(json.dumps({"action_type": "FROBNICATE"}))
    with pytest.raises(ValueError):
        parse_agent_output(json.dumps({"action_type": "AUTONOMOUS_EXECUTE", "actions": []}))
    with pytest.raises(ValueError):
        parse_agent_output(json.dumps({"action_type": "NO_ACTION_NEEDED", "confidence_score": 9.9}))


def test_gate_agent_action_respects_autonomy() -> None:
    draft = parse_agent_output(
        json.dumps({"event_summary": "e", "confidence_score": 0.6, "action_type": "DRAFT_FOR_APPROVAL", "actions": []})
    )
    auto = parse_agent_output(
        json.dumps(
            {
                "event_summary": "e",
                "confidence_score": 0.95,
                "action_type": "AUTONOMOUS_EXECUTE",
                "actions": [{"provider": "slack", "endpoint": "/x"}],
            }
        )
    )
    idle = parse_agent_output(
        json.dumps({"event_summary": "e", "confidence_score": 0.2, "action_type": "NO_ACTION_NEEDED"})
    )
    assert gate_agent_action(idle) == Decision.NONE
    l1 = GhostPolicy(autonomy=AutonomyLevel.PREPARE)
    assert gate_agent_action(draft, l1) == Decision.PREPARE
    # L1/L2 must never autonomously execute external side effects.
    assert gate_agent_action(auto, l1) == Decision.ASK
    assert gate_agent_action(auto, GhostPolicy(autonomy=AutonomyLevel.INJECT)) == Decision.ASK
    l3 = GhostPolicy(autonomy=AutonomyLevel.ACT)
    assert gate_agent_action(auto, l3) == Decision.ACT
