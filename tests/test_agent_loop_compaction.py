"""Regression tests for auto-compaction in the agent run loop.

Live-verified 2026-10-10: a scripted 2x-context-budget run through the real
``AIAgent.run`` loop (fake model backend only) confirmed compression fires,
``compression_count`` increments, the message list shrinks, and salient facts
survive. These tests pin that behavior so it cannot silently regress.

They also cover a real defect found by that live run: ``_compress_session``
dropped the preserved head (first 3 messages) instead of keeping it, so early
facts were lost on the second compaction. The head must survive verbatim.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from ghostchimera.chimera_pilot.agent_loop import (
    AIAgent,
    Message,
    SessionState,
)

CANARY = "the blue whale migrates in autumn"


class FakeRouter:
    """Model backend stub with realistic growing token usage (no network)."""

    def __init__(self, step: int = 40) -> None:
        self.calls = 0
        self.step = step

    def complete(self, model, messages, tools, max_tokens):
        self.calls += 1
        total = 100 + self.calls * self.step
        return {
            "content": f"ack {self.calls}",
            "finish_reason": "stop",
            "usage": {
                "prompt_tokens": total - 10,
                "completion_tokens": 10,
                "total_tokens": total,
            },
        }


def make_agent(max_tokens: int = 200) -> AIAgent:
    kernel = SimpleNamespace(hooks=SimpleNamespace(fire=lambda *a, **k: None))
    session = SessionState(session_id="compaction-test", max_tokens=max_tokens)
    return AIAgent(
        kernel=kernel,
        router=FakeRouter(),
        fallback_chain=["fake-model"],
        max_tool_rounds=3,
        session=session,
    )


def drive(agent: AIAgent, turns: int, canary_turns: int = 3) -> None:
    for i in range(1, turns + 1):
        text = f"turn {i} note"
        if i <= canary_turns:
            text += f" CANARY: {CANARY}"
        agent.run(text)


class NoCompressionBelowThresholdTests(unittest.TestCase):
    def test_no_compression_on_short_session(self) -> None:
        agent = make_agent()
        drive(agent, 5)
        self.assertEqual(agent.session.compression_count, 0)
        self.assertEqual(len(agent.session.messages), 10)

    def test_no_compression_when_under_token_threshold(self) -> None:
        agent = make_agent(max_tokens=10_000_000)
        drive(agent, 20)
        self.assertEqual(agent.session.compression_count, 0)

    def test_compress_session_guard_under_10_messages(self) -> None:
        agent = make_agent()
        drive(agent, 3)
        before = list(agent.session.messages)
        agent._compress_session()
        self.assertEqual(agent.session.compression_count, 0)
        self.assertEqual(agent.session.messages, before)


class CompressionTriggerTests(unittest.TestCase):
    def test_compression_fires_past_threshold(self) -> None:
        agent = make_agent()
        drive(agent, 16)
        self.assertGreaterEqual(agent.session.compression_count, 1)

    def test_message_list_shrinks_after_compression(self) -> None:
        agent = make_agent()
        drive(agent, 16)
        # 32 messages compress to head(3) + summary(1) + tail(6) = 10,
        # plus the in-flight assistant reply of the triggering turn.
        self.assertLessEqual(len(agent.session.messages), 12)

    def test_trigger_boundary_exactly_30_messages(self) -> None:
        agent = make_agent()
        drive(agent, 15)  # 30 messages: armed but not over the >30 trigger
        self.assertEqual(agent.session.compression_count, 0)
        agent.run("turn 16 pushes past the trigger")
        self.assertEqual(agent.session.compression_count, 1)

    def test_compression_count_increments_per_event(self) -> None:
        agent = make_agent()
        drive(agent, 30)
        self.assertGreaterEqual(agent.session.compression_count, 2)


class HeadPreservationTests(unittest.TestCase):
    def test_head_messages_survive_verbatim(self) -> None:
        agent = make_agent()
        drive(agent, 5)
        head_before = [(m.role, m.content) for m in agent.session.messages[:3]]
        drive(agent, 11)  # crosses the trigger; exactly one compression
        self.assertEqual(agent.session.compression_count, 1)
        head_after = [(m.role, m.content) for m in agent.session.messages[:3]]
        self.assertEqual(head_after, head_before)

    def test_summary_sits_between_head_and_tail(self) -> None:
        agent = make_agent()
        drive(agent, 16)
        messages = agent.session.messages
        summaries = [m for m in messages if m.role == "system" and "[CONTEXT COMPACTION]" in str(m.content)]
        self.assertEqual(len(summaries), 1)
        self.assertGreater(messages.index(summaries[0]), 2)

    def test_middle_content_covered_by_summary(self) -> None:
        agent = make_agent()
        drive(agent, 16)
        summaries = [
            m for m in agent.session.messages if m.role == "system" and "[CONTEXT COMPACTION]" in str(m.content)
        ]
        self.assertEqual(len(summaries), 1)
        # A middle turn (turn 8) must appear in the summary text.
        self.assertIn("turn 8 note", str(summaries[0].content))


class CanarySurvivalTests(unittest.TestCase):
    def test_canary_survives_single_compaction(self) -> None:
        agent = make_agent()
        drive(agent, 16)
        blob = "\n".join(str(m.content) for m in agent.session.messages)
        self.assertIn(CANARY, blob)

    def test_canary_survives_multiple_compactions(self) -> None:
        agent = make_agent()
        drive(agent, 30)
        self.assertGreaterEqual(agent.session.compression_count, 2)
        blob = "\n".join(str(m.content) for m in agent.session.messages)
        self.assertIn(CANARY, blob)

    def test_two_x_budget_run_completes(self) -> None:
        agent = make_agent(max_tokens=200)
        drive(agent, 30)
        threshold = 200 * 0.75
        self.assertGreater(agent.session.total_tokens, 2 * threshold)
        self.assertGreaterEqual(agent.session.compression_count, 1)


class CompressSessionBoundaryTests(unittest.TestCase):
    """Pin the exact slicing/guard constants of _compress_session (mutation-hardened)."""

    def _agent_with(self, n: int) -> AIAgent:
        agent = make_agent()
        agent.session.messages = [
            Message(role="user" if i % 2 == 0 else "assistant", content=f"marker-{i}") for i in range(n)
        ]
        return agent

    def test_guard_fires_at_exactly_10_messages(self) -> None:
        agent = self._agent_with(10)
        agent._compress_session()
        self.assertEqual(agent.session.compression_count, 1)

    def test_guard_skips_below_10_messages(self) -> None:
        agent = self._agent_with(9)
        before = list(agent.session.messages)
        agent._compress_session()
        self.assertEqual(agent.session.compression_count, 0)
        self.assertEqual(agent.session.messages, before)

    def test_head_is_exactly_first_three(self) -> None:
        agent = self._agent_with(12)
        agent._compress_session()
        messages = agent.session.messages
        # Mutant head=messages[:4] would put original marker-3 at index 3.
        self.assertEqual([m.content for m in messages[:3]], ["marker-0", "marker-1", "marker-2"])
        self.assertIn("[CONTEXT COMPACTION]", str(messages[3].content))

    def test_tail_is_exactly_last_six(self) -> None:
        agent = self._agent_with(12)
        agent._compress_session()
        messages = agent.session.messages
        # Mutant tail=messages[-7:] would shift the summary one slot left.
        self.assertEqual(
            [m.content for m in messages[-6:]],
            [f"marker-{i}" for i in range(6, 12)],
        )
        self.assertIn("[CONTEXT COMPACTION]", str(messages[-7].content))

    def test_middle_starts_at_index_3(self) -> None:
        agent = self._agent_with(12)
        agent._compress_session()
        summary = str(agent.session.messages[3].content)
        # Mutant middle=messages[4:-6] would drop marker-3 from the summary.
        self.assertIn("marker-3", summary)

    def test_middle_ends_at_index_minus_7(self) -> None:
        agent = self._agent_with(12)
        agent._compress_session()
        summary = str(agent.session.messages[3].content)
        # Mutant middle=messages[3:-7] would drop marker-5 from the summary.
        self.assertIn("marker-5", summary)

    def test_summary_depth_capped_at_50_middle_messages(self) -> None:
        agent = self._agent_with(60)  # middle = indices 3..53 (51 messages)
        agent._compress_session()
        summary = str(agent.session.messages[3].content)
        self.assertIn("marker-52", summary)  # 50th middle message kept
        self.assertNotIn("marker-53", summary)  # 51st middle message cut

    def test_list_content_with_non_dict_part(self) -> None:
        agent = self._agent_with(12)
        agent.session.messages[4] = Message(role="user", content=[{"text": "kept-text"}, "raw-string-part"])
        agent._compress_session()  # mutant `or` would raise AttributeError here
        summary = str(agent.session.messages[3].content)
        self.assertIn("kept-text", summary)


if __name__ == "__main__":
    unittest.main()
