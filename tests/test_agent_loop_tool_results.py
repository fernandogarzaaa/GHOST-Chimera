"""Tool-result content handling in AIAgent._execute_tool_calls.

Covers the JSON-serialization fallback path: non-string tool outputs are
serialized with ensure_ascii=False, and outputs that cannot be serialized
at all fall back to str().
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from ghostchimera.chimera_pilot import agent_loop
from ghostchimera.chimera_pilot.agent_loop import AIAgent
from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile
from ghostchimera.safety_layer.approval import ApprovalResult


def _circular_tuple() -> tuple:
    # A tuple passes the dict/list JSON-normalizer middleware untouched, but
    # json.dumps still chokes on the circular dict inside it.
    inner: dict[str, object] = {}
    inner["self"] = inner
    return (inner,)


class ToolResultContentTests(unittest.TestCase):
    def _agent(self) -> AIAgent:
        return AIAgent(
            model_name="test-model",
            autonomy_profile=get_autonomy_profile("supervised"),
        )

    def _run(self, agent: AIAgent, handler: Any, name: str = "tool") -> list[dict[str, Any]]:
        tool = {"name": name, "handler": handler}
        with patch.object(agent_loop, "approve", return_value=ApprovalResult.allow()):
            return agent._execute_tool_calls([{"name": name, "arguments": {}, "id": "call-1"}], tools=[tool])

    def test_non_string_output_is_json(self) -> None:
        agent = self._agent()
        results = self._run(agent, lambda **args: {"ok": True, "n": 3}, name="jtool")
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[0]["content"], '{"ok": true, "n": 3}')

    def test_unicode_output_is_not_escaped(self) -> None:
        # Tuples bypass the dict/list JSON-normalizer middleware, so this
        # exercises _execute_tool_calls' own ensure_ascii=False path.
        agent = self._agent()
        results = self._run(agent, lambda **args: ("héllo wörld",), name="utool")
        self.assertEqual(results[0]["status"], "success")
        self.assertIn("héllo wörld", results[0]["content"])
        self.assertNotIn("\\u", results[0]["content"])

    def test_unserializable_output_falls_back_to_str(self) -> None:
        agent = self._agent()
        results = self._run(agent, lambda **args: _circular_tuple(), name="btool")
        self.assertEqual(results[0]["status"], "success")
        # Circular structure survived via str(), not JSON.
        self.assertIn("'self': {...}", results[0]["content"])
