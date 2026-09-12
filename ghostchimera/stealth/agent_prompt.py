"""Stealth BPO/VA agent prompt: persona, boundaries, and machine-readable output.

Renders the system prompt for a stealth autonomous assistant operating
under a human VA/BPO agent's identity, then parses and policy-gates the
agent's JSON output:

- AUTONOMOUS_EXECUTE -> ACT only when policy allows; else ASK (draft path).
- DRAFT_FOR_APPROVAL -> PREPARE (stage draft + flag for human review).
- NO_ACTION_NEEDED   -> NONE (silence is success).

The host model stays replaceable: this module owns the contract, never
the inference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .stealth_policy import AutonomyLevel, Decision, GhostPolicy

SYSTEM_PROMPT_TEMPLATE = """# SYSTEM PROMPT: STEALTH BPO & VA AUTONOMOUS AGENT

## ROLE & PERSONA
You are an invisible, hyper-efficient AI co-pilot operating on behalf of a Virtual Assistant / BPO Operations Agent.
- Your job is to monitor incoming events (emails, messages, helpdesk tickets), assess intent, and autonomously draft or execute precise responses and workflow actions.
- You operate under the persona and identity of the human agent. NEVER reveal, imply, or mention that you are an AI, bot, language model, or automated system.
- Match the communication style, tone, and professional standard expected in BPO/VA operations (clear, helpful, concise, empathetic).

## OPERATIONAL GUIDELINES & BOUNDARIES
1. STEALTH & DISCREETNESS: All outbound communications (emails, Slack updates, ticket replies) must sound completely natural and human-authored.
2. HIGH-CONFIDENCE EXECUTION:
   - If an inbound event requires standard operational handling (e.g., meeting scheduling, status updates, routing tickets, answering standard FAQs), execute the required API actions directly.
   - If an inbound event involves financial transactions, sensitive account changes, or ambiguous/angry customer escalations, prepare a draft response and flag it for human agent review.
3. EFFICIENCY FIRST: Avoid filler language. Focus directly on solving the inbound request or updating the record.

## CONTEXT & STATE
- Human Agent Name: {{HUMAN_AGENT_NAME}}
- Connected Services: {{CONNECTED_INTEGRATIONS}}
- Current Task Context: {{INBOUND_EVENT_PAYLOAD}}

## INSTRUCTIONS FOR EVENT PROCESSING
1. Analyze the `INBOUND_EVENT_PAYLOAD` to identify:
   - Sender & Platform (Gmail, Slack, Zendesk, etc.)
   - Primary Intent / Action Needed
   - Urgency & Sentiment
2. Formulate the response strategy based on your operational domain.
3. Output your response as a structured JSON object containing both your reasoning chain and the platform actions to trigger.

## OUTPUT FORMAT (JSON ONLY)
Respond strictly in valid JSON with no conversational preamble:

{
  "event_summary": "Brief 1-sentence summary of the inbound event.",
  "confidence_score": 0.95,
  "action_type": "AUTONOMOUS_EXECUTE",
  "actions": [
    {
      "provider": "google-mail",
      "endpoint": "/users/me/messages/send",
      "payload": {
        "to": "client@example.com",
        "subject": "Re: Inquiry",
        "body": "Hi John,\\n\\nI have updated your schedule as requested.\\n\\nBest regards,\\n{{HUMAN_AGENT_NAME}}"
      }
    }
  ]
}

action_type options: "AUTONOMOUS_EXECUTE" | "DRAFT_FOR_APPROVAL" | "NO_ACTION_NEEDED"
"""


class AgentActionType(StrEnum):
    AUTONOMOUS_EXECUTE = "AUTONOMOUS_EXECUTE"
    DRAFT_FOR_APPROVAL = "DRAFT_FOR_APPROVAL"
    NO_ACTION_NEEDED = "NO_ACTION_NEEDED"


@dataclass
class AgentAction:
    event_summary: str
    confidence_score: float
    action_type: AgentActionType
    actions: list[dict[str, Any]] = field(default_factory=list)


def render_system_prompt(*, agent_name: str, integrations: list[str], event_payload: dict[str, Any]) -> str:
    """Fill the template. Values are JSON-rendered where structured."""
    return (
        SYSTEM_PROMPT_TEMPLATE.replace("{{HUMAN_AGENT_NAME}}", agent_name)
        .replace("{{CONNECTED_INTEGRATIONS}}", ", ".join(integrations))
        .replace("{{INBOUND_EVENT_PAYLOAD}}", json.dumps(event_payload))
    )


def parse_agent_output(text: str) -> AgentAction:
    """Strict-parse agent JSON output. Raises ValueError on any violation."""
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Agent output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Agent output must be a JSON object")
    try:
        action_type = AgentActionType(str(data["action_type"]))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid action_type: {data.get('action_type')!r}") from exc
    try:
        confidence = float(data.get("confidence_score", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence_score must be a number") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence_score must be between 0.0 and 1.0")
    actions = data.get("actions", [])
    if not isinstance(actions, list):
        raise ValueError("actions must be a list")
    for action in actions:
        if not isinstance(action, dict) or "provider" not in action or "endpoint" not in action:
            raise ValueError(f"Malformed action entry: {action!r}")
    if action_type == AgentActionType.AUTONOMOUS_EXECUTE and not actions:
        raise ValueError("AUTONOMOUS_EXECUTE requires at least one action")
    return AgentAction(
        event_summary=str(data.get("event_summary", "")),
        confidence_score=confidence,
        action_type=action_type,
        actions=actions,
    )


def gate_agent_action(action: AgentAction, policy: GhostPolicy | None = None) -> Decision:
    """Map agent intent through Ghost autonomy policy (spec: silent agency).

    The agent proposes; Ghost disposes. L3 ACT allows autonomous execute,
    anything lower downgrades external side effects to ASK (human review),
    drafts always PREPARE, and NO_ACTION stays silent.
    """
    policy = policy or GhostPolicy.conservative_default()
    if action.action_type == AgentActionType.NO_ACTION_NEEDED:
        return Decision.NONE
    if action.action_type == AgentActionType.DRAFT_FOR_APPROVAL:
        return Decision.PREPARE if policy.allows(Decision.PREPARE) else Decision.STORE
    # AUTONOMOUS_EXECUTE: external side effect — requires explicit L3.
    if policy.autonomy >= AutonomyLevel.ACT:
        return Decision.ACT
    return Decision.ASK


__all__ = [
    "AgentAction",
    "AgentActionType",
    "SYSTEM_PROMPT_TEMPLATE",
    "gate_agent_action",
    "parse_agent_output",
    "render_system_prompt",
]
