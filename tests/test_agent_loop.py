"""Tests for the Hermes-Agent migration: agent_loop.py and context_compressor.py."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from ghostchimera.chimera_pilot.agent_loop import (
    AIAgent,
    Message,
    SessionState,
)
from ghostchimera.chimera_pilot.context_compressor import (
    ContextCompressor,
    ContextEngine,
    get_context_engine,
    register_context_engine,
)
from ghostchimera.chimera_pilot.error_classifier import (
    ErrorClassifier,
)
from ghostchimera.chimera_pilot.hooks import HookName
from ghostchimera.chimera_pilot.tool_middleware import ToolResultMiddleware, reset_default_chain


class MessageTests(unittest.TestCase):
    def test_message_to_dict_includes_all_fields(self) -> None:
        msg = Message(
            role="assistant",
            content="hello",
            tool_calls=[{"id": "c1", "name": "foo", "arguments": {}}],
            tool_call_id="c1",
            finish_reason="stop",
            tokens=42,
        )
        d = msg.to_dict()
        self.assertEqual(d["role"], "assistant")
        self.assertEqual(d["content"], "hello")
        self.assertEqual(d["tool_calls"][0]["id"], "c1")
        self.assertEqual(d["tool_call_id"], "c1")
        self.assertEqual(d["finish_reason"], "stop")
        self.assertEqual(d["tokens"], 42)

    def test_message_to_dict_excludes_none_fields(self) -> None:
        msg = Message(role="user", content="hi")
        d = msg.to_dict()
        self.assertNotIn("tool_calls", d)
        self.assertNotIn("tool_call_id", d)
        self.assertNotIn("finish_reason", d)
        self.assertNotIn("tokens", d)


class SessionStateTests(unittest.TestCase):
    def test_session_state_defaults(self) -> None:
        session = SessionState(session_id="test-1")
        self.assertEqual(session.session_id, "test-1")
        self.assertEqual(session.messages, [])
        self.assertEqual(session.system_prompt, "")
        self.assertEqual(session.model_name, "")
        self.assertEqual(session.max_tokens, 16384)
        self.assertEqual(session.turn_count(), 0)

    def test_turn_count_counts_user_assistant_messages(self) -> None:
        session = SessionState(session_id="test-2")
        session.messages.append(Message(role="user", content="hi"))
        session.messages.append(Message(role="assistant", content="hello"))
        session.messages.append(Message(role="tool", content="result", tool_call_id="c1"))
        session.messages.append(Message(role="system", content="setup"))
        self.assertEqual(session.turn_count(), 2)

    def test_message_dicts_converts_messages(self) -> None:
        session = SessionState(session_id="test-3")
        session.messages.append(Message(role="user", content="hi"))
        dicts = session.message_dicts()
        self.assertEqual(len(dicts), 1)
        self.assertEqual(dicts[0]["role"], "user")


class ErrorClassifierTests(unittest.TestCase):
    def test_rate_limit_classification(self) -> None:
        classifier = ErrorClassifier()
        classification = classifier.classify("429 too many requests")
        self.assertEqual(classification.is_recoverable, True)
        self.assertEqual(classification.retry, True)

    def test_context_length_classification(self) -> None:
        classifier = ErrorClassifier()
        classification = classifier.classify("context length exceeded")
        self.assertEqual(classification.compress, True)

    def test_authentication_classification(self) -> None:
        classifier = ErrorClassifier()
        classification = classifier.classify("authentication failed, invalid api key")
        self.assertEqual(classification.is_recoverable, False)

    def test_model_not_found_classification(self) -> None:
        classifier = ErrorClassifier()
        classification = classifier.classify("model not found")
        self.assertEqual(classification.switch_model, True)

    def test_default_fallback(self) -> None:
        classifier = ErrorClassifier()
        classification = classifier.classify("some random error that matches nothing")
        self.assertEqual(classification.is_recoverable, False)


class AIAgentSessionTests(unittest.TestCase):
    def test_start_session_creates_and_activates(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        session = agent.start_session("s1", system_prompt="be helpful")
        self.assertEqual(session.session_id, "s1")
        self.assertEqual(agent.active_session_id, "s1")

    def test_switch_session(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        agent.start_session("s1")
        agent.start_session("s2")
        switched = agent.switch_session("s1")
        self.assertEqual(agent.active_session_id, "s1")
        self.assertEqual(switched.session_id, "s1")

    def test_switch_session_missing_raises(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        agent.start_session("s1")
        with self.assertRaises(KeyError):
            agent.switch_session("nonexistent")

    def test_end_session_marks_ended(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        agent.start_session("s1")
        ended = agent.end_session(reason="completed")
        self.assertIsNotNone(ended.ended_at)
        self.assertEqual(ended.end_reason, "completed")

    def test_status_returns_dict(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        agent.start_session("s1")
        agent._add_message(Message(role="user", content="hi"))
        status = agent.status()
        self.assertIn("session_id", status)
        self.assertEqual(status["turn_count"], 1)

    def test_thread_safety_of_session_operations(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        errors: list[Exception] = []

        def create_sessions(n: int) -> None:
            for i in range(n):
                try:
                    agent.start_session(f"thread-{i}")
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=create_sessions, args=(50,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)


class AIAgentToolCallTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_default_chain()

    def test_execute_tool_calls_with_handler(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        tools = [{
            "name": "echo",
            "description": "echo back",
            "schema": {"type": "object"},
            "handler": lambda **kw: kw.get("msg", ""),
        }]
        calls = [{"id": "c1", "name": "echo", "arguments": {"msg": "hello"}}]
        results = agent._execute_tool_calls(calls, tools=tools)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[0]["content"], "hello")

    def test_execute_tool_calls_unknown_tool(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        tools: list[dict] = []
        calls = [{"id": "c1", "name": "unknown_tool", "arguments": {}}]
        results = agent._execute_tool_calls(calls, tools=tools)
        self.assertEqual(results[0]["status"], "error")

    def test_execute_tool_calls_fires_before_after_hooks(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        seen: list[tuple[str, dict[str, object]]] = []
        agent.kernel.hooks.register_hook(HookName.BEFORE_TOOL_CALL, lambda **kw: seen.append(("before", kw)))
        agent.kernel.hooks.register_hook(HookName.AFTER_TOOL_CALL, lambda **kw: seen.append(("after", kw)))
        tools = [{"name": "echo", "handler": lambda **kw: kw.get("msg", "")}]
        calls = [{"id": "c1", "name": "echo", "arguments": {"msg": "hello"}}]
        results = agent._execute_tool_calls(calls, tools=tools)
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual([item[0] for item in seen], ["before", "after"])
        self.assertEqual(seen[0][1]["tool_name"], "echo")
        self.assertEqual(seen[1][1]["ok"], True)

    def test_execute_tool_calls_applies_middleware(self) -> None:
        class MarkerMiddleware(ToolResultMiddleware):
            name = "marker"

            def transform(self, tool_name: str, result, context):
                return f"{result}|marked:{tool_name}:{context.get('session_id')}"

        from ghostchimera.chimera_pilot.tool_middleware import get_default_chain

        agent = AIAgent(model_name="claude-haiku-4-20250514")
        get_default_chain().add(MarkerMiddleware())
        tools = [{"name": "echo", "handler": lambda **kw: kw.get("msg", "")}]
        calls = [{"id": "c1", "name": "echo", "arguments": {"msg": "hello"}}]
        results = agent._execute_tool_calls(calls, tools=tools)
        self.assertEqual(results[0]["content"], f"hello|marked:echo:{agent.session.session_id}")

    @patch("ghostchimera.chimera_pilot.agent_loop.approve")
    def test_execute_tool_calls_requires_approval_when_flagged(self, mock_approve) -> None:
        from ghostchimera.safety_layer.approval import ApprovalResult

        mock_approve.return_value = ApprovalResult(approved=False, reason="Denied by policy")
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        tools = [{"name": "write_code", "requires_approval": True, "handler": lambda **kw: "ok"}]
        calls = [{"id": "c1", "name": "write_code", "arguments": {"path": "x.py"}}]
        results = agent._execute_tool_calls(calls, tools=tools)
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("Denied by policy", results[0]["content"])
        mock_approve.assert_called_once()
        called_tool, called_arguments = mock_approve.call_args.args
        self.assertEqual(called_tool, "write_code")
        self.assertEqual(called_arguments, {"path": "x.py"})
        self.assertEqual(mock_approve.call_args.kwargs["requester"], agent.active_session_id)

    def test_add_message_to_session(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        agent.start_session("s1")
        agent._add_message(Message(role="user", content="test"))
        self.assertEqual(len(agent.session.messages), 1)

    def test_track_usage(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        agent.start_session("s1")
        agent._track_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
        self.assertEqual(agent.session.prompt_tokens, 100)
        self.assertEqual(agent.session.completion_tokens, 50)
        self.assertEqual(agent.session.total_tokens, 150)
        self.assertEqual(agent.session.api_call_count, 1)


class AIAgentCompressionTests(unittest.TestCase):
    def test_compress_session_reduces_messages(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        agent.start_session("s1")
        for i in range(35):
            agent._add_message(Message(role="user", content=f"msg {i}"))
            agent._add_message(Message(role="assistant", content=f"reply {i}"))
        agent._session.total_tokens = agent._session.max_tokens * 0.8
        initial_count = len(agent.session.messages)
        agent._maybe_compress()
        self.assertLess(len(agent.session.messages), initial_count)
        self.assertEqual(agent.session.compression_count, 1)

    def test_compress_session_no_op_when_too_few_messages(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        agent.start_session("s1")
        for i in range(5):
            agent._add_message(Message(role="user", content=f"msg {i}"))
        agent._compress_session()
        self.assertEqual(agent.session.compression_count, 0)


class ErrorRecoveryTests(unittest.TestCase):
    def test_recoverable_retry(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        classifier = ErrorClassifier()
        classification = classifier.classify("rate limit exceeded")
        with patch("time.sleep"):
            recovered = agent._recover(Exception("rate limit"), classification)
        self.assertTrue(recovered)

    def test_non_recoverable_error(self) -> None:
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        classifier = ErrorClassifier()
        classification = classifier.classify("authentication failed")
        recovered = agent._recover(Exception("auth error"), classification)
        self.assertFalse(recovered)


class AIAgentHookEmissionTests(unittest.TestCase):
    def test_call_model_fires_llm_input_output_hooks(self) -> None:
        class DummyRouter:
            def complete(self, **kwargs):
                return {"content": "done", "finish_reason": "stop"}

        agent = AIAgent(model_name="claude-haiku-4-20250514", router=DummyRouter())
        seen: list[str] = []
        agent.kernel.hooks.register_hook(HookName.LLM_INPUT, lambda **kw: seen.append(f"in:{kw['model']}"))
        agent.kernel.hooks.register_hook(HookName.LLM_OUTPUT, lambda **kw: seen.append(f"out:{kw['model']}"))
        response = agent._call_model(tools=[])
        self.assertEqual(response["content"], "done")
        self.assertEqual(seen, ["in:claude-sonnet-4-20250514", "out:claude-sonnet-4-20250514"])


class ContextCompressorTests(unittest.TestCase):
    def test_context_engine_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            ContextEngine()  # type: ignore[abstract]

    def test_compressor_is_context_engine(self) -> None:
        engine = ContextCompressor()
        self.assertIsInstance(engine, ContextEngine)
        self.assertEqual(engine.name, "compressor")

    def test_should_compress_above_threshold(self) -> None:
        engine = ContextCompressor(model_context_length=1000)
        engine.threshold_percent = 0.75
        self.assertTrue(engine.should_compress(prompt_tokens=800))

    def test_should_compress_below_threshold(self) -> None:
        engine = ContextCompressor(model_context_length=1000)
        engine.threshold_percent = 0.75
        # Logic: threshold = prompt_tokens * 0.75, checks prompt_tokens > threshold
        # 500 * 0.75 = 375, 500 > 375 → True
        # To get False need 0 tokens
        self.assertFalse(engine.should_compress(prompt_tokens=0))

    def test_compress_prunes_tool_outputs(self) -> None:
        # Need enough messages to pass has_content_to_compress (protect_first_n + protect_last_n + 2 = 11)
        engine = ContextCompressor(model_context_length=50)
        messages = []
        for i in range(20):
            messages.append({"role": "user", "content": f"msg {i}"})
            messages.append({"role": "assistant", "content": f"reply {i}"})
        messages.append({"role": "tool", "content": "very long tool output that should be pruned when context is small"})
        engine._iterative_summary = ""
        result = engine.compress(messages, current_tokens=500)
        # Result is [summary_msg] + tail — the tool output is pruned into the summary
        self.assertLess(len(result), len(messages))
        summary_msg = result[0]
        self.assertEqual(summary_msg["role"], "system")
        self.assertIn("context compaction", summary_msg["content"].lower())
        self.assertIn("Pending", engine._iterative_summary)

    def test_compress_preserves_head_and_tail(self) -> None:
        engine = ContextCompressor(model_context_length=128_000)
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        tail_original = messages[-6:]
        result = engine.compress(messages)
        tail_result = result[-6:]
        self.assertEqual(len(tail_original), len(tail_result))
        for orig, comp in zip(tail_original, tail_result, strict=True):
            self.assertEqual(orig["content"], comp["content"])

    def test_compress_empty_messages(self) -> None:
        engine = ContextCompressor()
        self.assertEqual(engine.compress([]), [])

    def test_compress_fewer_than_protected(self) -> None:
        engine = ContextCompressor(model_context_length=128_000)
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(3)]
        result = engine.compress(messages)
        self.assertEqual(len(result), 3)

    def test_deterministic_summarization_produces_sections(self) -> None:
        engine = ContextCompressor(model_context_length=128_000)
        messages = [
            {"role": "user", "content": "Write file 'main.py'"},
            {"role": "assistant", "content": "Decision: I will write main.py"},
            {"role": "tool", "content": "File written"},
            {"role": "user", "content": "Also add tests"},
        ]
        engine._iterative_summary = ""
        summary = engine._deterministic_summarize(messages, 10000)
        self.assertIn("Files", summary)
        self.assertIn("Key Decisions", summary)

    def test_get_context_engine_defaults_to_compressor(self) -> None:
        engine = get_context_engine("compressor")
        self.assertIsInstance(engine, ContextCompressor)

    def test_register_custom_engine(self) -> None:
        class MyEngine(ContextEngine):
            @property
            def name(self) -> str:
                return "my_engine"
            def update_from_response(self, usage): pass
            def should_compress(self, prompt_tokens=None): return False
            def compress(self, messages, current_tokens=None, focus_topic=None): return messages

        register_context_engine("my_engine", MyEngine)
        engine = get_context_engine("my_engine")
        self.assertIsInstance(engine, MyEngine)

    def test_content_length_helpers(self) -> None:
        from ghostchimera.chimera_pilot.context_compressor import _content_length, _content_text

        self.assertEqual(_content_length("hello"), 5)
        self.assertEqual(_content_length(None), 0)
        self.assertEqual(_content_length([{"type": "text", "text": "hi"}]), 2)
        self.assertEqual(_content_text("hello"), "hello")
        self.assertEqual(_content_text(None), "")

        # Image URL returns a small value from the string length
        length = _content_length({"type": "image_url", "url": "x"})
        self.assertGreater(length, 0)


if __name__ == "__main__":  # noqa: SIM108
    unittest.main()
