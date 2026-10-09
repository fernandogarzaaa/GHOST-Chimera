"""Verification tests for policy-controlled approval gates.

These tests pin the safety-critical default: with a fresh process and no
explicit opt-in, a ``requires_approval`` tool MUST be blocked until approved.
If the default ever silently auto-approved, the gates would be theater.

Covers:
  * default handler selection (non-interactive -> deny, TTY -> console,
    GHOSTCHIMERA_AUTO_APPROVE=1 -> auto-approve explicit opt-in)
  * selective gating (trusted tools pass, blocked patterns denied even
    under auto-approve)
  * end-to-end through AIAgent._execute_tool_calls: denial blocks the tool
    handler and surfaces PermissionError; approval unblocks it
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import ghostchimera.safety_layer.approval as approval_mod
from ghostchimera.chimera_pilot.agent_loop import AIAgent
from ghostchimera.safety_layer.approval import (
    ApprovalHandler,
    ApprovalPolicy,
    ApprovalRequest,
    AutoApproveHandler,
    AutoDenyHandler,
    ConsoleApprovalHandler,
    approve,
    get_default_handler,
    set_default_handler,
)

AUTO_APPROVE_ENV = "GHOSTCHIMERA_AUTO_APPROVE"


def _reset_singleton():
    approval_mod._default_handler = None


def _clear_auto_approve_env():
    return mock.patch.dict(os.environ, {AUTO_APPROVE_ENV: ""})


class DefaultHandlerSelectionTests(unittest.TestCase):
    """The fresh-process default must be deny-by-default, never auto-approve."""

    def setUp(self):
        self._saved_handler = approval_mod._default_handler
        self._saved_env = os.environ.get(AUTO_APPROVE_ENV)
        _reset_singleton()

    def tearDown(self):
        approval_mod._default_handler = self._saved_handler
        if self._saved_env is None:
            os.environ.pop(AUTO_APPROVE_ENV, None)
        else:
            os.environ[AUTO_APPROVE_ENV] = self._saved_env

    def test_noninteractive_defaults_to_deny(self):
        """No TTY and no opt-in env -> AutoDenyHandler."""
        os.environ.pop(AUTO_APPROVE_ENV, None)
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            handler = get_default_handler()
        self.assertIsInstance(handler, AutoDenyHandler)

    def test_noninteractive_denies_untrusted_tool(self):
        """The exact call the agent loop makes must deny without approval."""
        os.environ.pop(AUTO_APPROVE_ENV, None)
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            result = approve("shell_exec", {"command": "rm -rf /"}, requester="s1")
        self.assertFalse(result.approved)
        self.assertIn("denied", result.reason.lower())

    def test_auto_approve_requires_explicit_env(self):
        """Auto-approve only via explicit GHOSTCHIMERA_AUTO_APPROVE=1."""
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            with mock.patch.dict(os.environ, {AUTO_APPROVE_ENV: "1"}):
                handler = get_default_handler()
        self.assertIsInstance(handler, AutoApproveHandler)

    def test_tty_defaults_to_console_prompt(self):
        """Interactive TTY -> human console prompt, not auto-approve."""
        os.environ.pop(AUTO_APPROVE_ENV, None)
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            handler = get_default_handler()
        self.assertIsInstance(handler, ConsoleApprovalHandler)

    def test_default_handler_is_cached_singleton(self):
        os.environ.pop(AUTO_APPROVE_ENV, None)
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            first = get_default_handler()
            second = get_default_handler()
        self.assertIs(first, second)

    def test_trusted_tools_still_allowed_under_default_deny(self):
        """Deny-by-default is selective: the trusted set passes without prompt."""
        os.environ.pop(AUTO_APPROVE_ENV, None)
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            result = approve("read_file", {"path": "/tmp/x"}, requester="s1")
        self.assertTrue(result.approved)

    def test_blocked_pattern_denied_even_under_auto_approve(self):
        """Policy-level block short-circuits before any auto-approve handler."""
        set_default_handler(AutoApproveHandler(ApprovalPolicy()))
        try:
            result = approve("delete_customer_database", {}, requester="s1")
        finally:
            _reset_singleton()
        self.assertFalse(result.approved)
        self.assertIn("blocked", result.reason.lower())


def _make_agent(require_approval: bool = True) -> AIAgent:
    """Bare AIAgent driving only the real _execute_tool_calls gate code."""
    agent = AIAgent.__new__(AIAgent)
    agent.autonomy_profile = SimpleNamespace(require_approval_for_high_impact=require_approval)
    agent._active_session_id = "test-session"
    agent._session = SimpleNamespace(session_id="sess-1")
    agent.kernel = SimpleNamespace(hooks=SimpleNamespace(fire=lambda *a, **k: None))
    return agent


class AgentLoopGateTests(unittest.TestCase):
    """End-to-end through the real gate in AIAgent._execute_tool_calls."""

    def setUp(self):
        self._saved_handler = approval_mod._default_handler
        self.calls: list[dict] = []

        def fake_handler(**kwargs):
            self.calls.append(kwargs)
            return "executed"

        self.tool_def = {
            "name": "shell_exec",
            "requires_approval": True,
            "handler": fake_handler,
        }

    def tearDown(self):
        approval_mod._default_handler = self._saved_handler

    def _run(self, handler: ApprovalHandler) -> list[dict]:
        set_default_handler(handler)
        agent = _make_agent()
        return agent._execute_tool_calls(
            [{"name": "shell_exec", "arguments": {"command": "rm -rf /"}, "id": "c1"}],
            tools=[self.tool_def],
        )

    def test_denied_tool_never_executes(self):
        results = self._run(AutoDenyHandler(ApprovalPolicy()))
        self.assertEqual(self.calls, [], "denied tool handler must not run")
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("denied", results[0]["content"].lower())

    def test_approved_tool_executes(self):
        results = self._run(AutoApproveHandler(ApprovalPolicy()))
        self.assertEqual(len(self.calls), 1, "approved tool handler must run once")
        self.assertEqual(results[0]["status"], "success")

    def test_callback_approval_controls_execution(self):
        from ghostchimera.safety_layer.approval import CallbackApprovalHandler

        results = self._run(CallbackApprovalHandler(lambda req: False, ApprovalPolicy()))
        self.assertEqual(self.calls, [])
        self.assertEqual(results[0]["status"], "error")

        results = self._run(CallbackApprovalHandler(lambda req: True, ApprovalPolicy()))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(results[0]["status"], "success")

    def test_gate_respects_profile_opt_out(self):
        """require_approval_for_high_impact=False disables the gate (explicit)."""
        set_default_handler(AutoDenyHandler(ApprovalPolicy()))
        agent = _make_agent(require_approval=False)
        results = agent._execute_tool_calls(
            [{"name": "shell_exec", "arguments": {}, "id": "c1"}],
            tools=[self.tool_def],
        )
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(results[0]["status"], "success")

    def test_non_approval_tools_skip_gate(self):
        """Tools not declaring requires_approval run without hitting the gate."""
        seen: list[ApprovalRequest] = []

        class SpyDeny(AutoDenyHandler):
            def handle(self, request):  # noqa: N802 - signature match
                seen.append(request)
                return super().handle(request)

        set_default_handler(SpyDeny(ApprovalPolicy()))
        agent = _make_agent()
        plain_tool = {"name": "read_file", "handler": lambda **k: "ok"}
        results = agent._execute_tool_calls(
            [{"name": "read_file", "arguments": {"path": "x"}, "id": "c1"}],
            tools=[plain_tool],
        )
        self.assertEqual(seen, [], "gate must not fire for non-approval tools")
        self.assertEqual(results[0]["status"], "success")


if __name__ == "__main__":
    unittest.main()
