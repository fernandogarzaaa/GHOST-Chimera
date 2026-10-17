"""codeaudit F7: MoA re-vote assigned to the read-only AIAgent.session property.

Runs the real ``MixtureOfAgents._revote_agent`` / ``vote_with_revote`` and the
real ``AIAgent`` loop. The only stand-in is the model endpoint: a local router
that answers deterministically (what a provider would do over the network).
"""

from __future__ import annotations

import threading

import pytest

from ghostchimera.chimera_pilot.agent_loop import SessionState
from ghostchimera.chimera_pilot.mixture_of_agents import MixtureOfAgents, MoAConfig


class LocalRouter:
    """Deterministic in-process model endpoint with AIAgent's router interface."""

    def __init__(self, answer_for) -> None:
        self.answer_for = answer_for
        self.calls: list[list[dict]] = []
        self._lock = threading.Lock()

    def complete(self, *, model, messages, tools, max_tokens):
        with self._lock:
            self.calls.append(list(messages))
        return {"content": self.answer_for(messages), "finish_reason": "stop"}


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(tmp_path / ".ghostchimera"))


def test_revote_agent_runs_and_continues_the_original_session() -> None:
    router = LocalRouter(lambda messages: "The answer is 4 because 2 plus 2 equals 4.")
    moa = MixtureOfAgents(model_router=router)
    original = SessionState(session_id="moa-agent-0-test", system_prompt="be precise")
    moa._sessions[original.session_id] = original

    result = moa._revote_agent(
        {"agent_output": "5", "session_id": original.session_id, "prompt_style": "skeptic", "agent_index": 0},
        "Reconsider: what is 2+2?",
    )

    assert result["success"] is True, result.get("error")
    assert "4" in result["agent_output"]
    assert result["is_revote"] is True
    assert result["session_id"] == original.session_id  # same conversation continued
    assert any(m.content == "Reconsider: what is 2+2?" for m in original.messages)


def test_revote_without_a_known_session_starts_a_fresh_one() -> None:
    moa = MixtureOfAgents(model_router=LocalRouter(lambda messages: "Four (4)."))
    result = moa._revote_agent({"agent_output": "five"}, "Reconsider: what is 2+2?")
    assert result["success"] is True, result.get("error")
    assert result["session_id"].startswith("moa-revote-")


def test_vote_with_revote_revises_each_disagreeing_agent_once() -> None:
    # First round: two styles disagree with the majority; on re-vote everyone agrees.
    def answer(messages):
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        last = messages[-1]["content"]
        if "Reconsider" in last:
            return "The capital of France is Paris, a city of about 2 million people."
        if "contrarian" in system.lower() or "devil" in system.lower():
            return "Lyon is the capital, population 500000, founded 43 BC."
        return "The capital of France is Paris, a city of about 2 million people."

    router = LocalRouter(answer)
    prompts = [
        "Answer directly.",
        "Answer as a careful analyst.",
        "Answer as a contrarian.",
        "Answer as devil's advocate.",
    ]
    moa = MixtureOfAgents(config=MoAConfig(num_agents=4, reasoning_prompt_prefixes=prompts), model_router=router)
    first = moa.vote("What is the capital of France?")
    disagreeing = [v for v in first.votes if not v.get("agrees_with_consensus", False)]
    assert disagreeing, first.votes

    result = moa.vote_with_revote("What is the capital of France?", max_rounds=2, confidence_threshold=0.99)
    revotes = [v for v in result.votes if v.get("is_revote")]
    assert revotes, result.votes
    assert all(v["success"] for v in revotes), revotes
    # No duplicated revisions: one vote per agent.
    assert result.num_agents == len(first.votes)
