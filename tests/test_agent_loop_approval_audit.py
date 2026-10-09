"""Agent-loop approval decisions are written to the AuditTrail.

The connector write-gate path already audits; this covers the agent-loop
path (AIAgent._execute_tool_calls), which previously made approval
decisions without any audit record.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from ghostchimera.chimera_pilot import agent_loop
from ghostchimera.chimera_pilot.agent_loop import AIAgent
from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.audit_trail import AuditTrail
from ghostchimera.safety_layer.approval import ApprovalResult


def _config(state_dir: Path) -> GhostChimeraConfig:
    return dataclasses.replace(GhostChimeraConfig.from_env(), state_dir=state_dir)


class _MemoryAudit:
    """In-memory stand-in for AuditTrail (dependency injection seam)."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, event: str, *, entity_id: str = "", provider: str = "", detail: Any = None) -> None:
        self.records.append({"event": event, "entity_id": entity_id, "provider": provider, "detail": detail})


class ApprovalAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="ghost-approval-audit-")
        self.state_dir = Path(self._dir.name) / "state"
        self.profile = get_autonomy_profile("supervised")
        assert self.profile.require_approval_for_high_impact

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _agent(self, **kwargs: Any) -> AIAgent:
        return AIAgent(
            model_name="test-model",
            autonomy_profile=self.profile,
            config=_config(self.state_dir),
            **kwargs,
        )

    def _danger_tool(self) -> dict[str, Any]:
        return {
            "name": "danger_write",
            "requires_approval": True,
            "handler": lambda **args: "wrote",
        }

    def _call(self) -> list[dict[str, Any]]:
        return [{"name": "danger_write", "arguments": {"path": "/tmp/x"}, "id": "call-1"}]

    def _audit_lines(self) -> list[dict[str, Any]]:
        path = self.state_dir / "audit" / "connector-audit.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_approved_decision_is_audited(self) -> None:
        agent = self._agent()
        with patch.object(agent_loop, "approve", return_value=ApprovalResult.allow("looks fine", approver="tester")):
            results = agent._execute_tool_calls(self._call(), tools=[self._danger_tool()])
        self.assertEqual(results[0]["status"], "success")
        lines = self._audit_lines()
        self.assertEqual(len(lines), 1)
        entry = lines[0]
        self.assertEqual(entry["event"], "approval_decision")
        self.assertEqual(entry["entity_id"], agent.active_session_id)
        self.assertEqual(entry["provider"], "agent-loop")
        self.assertEqual(entry["detail"]["tool_name"], "danger_write")
        self.assertTrue(entry["detail"]["approved"])
        self.assertEqual(entry["detail"]["approver"], "tester")

    def test_denied_decision_is_audited(self) -> None:
        agent = self._agent()
        with patch.object(agent_loop, "approve", return_value=ApprovalResult.deny("too risky", approver="tester")):
            results = agent._execute_tool_calls(self._call(), tools=[self._danger_tool()])
        # Denial surfaces as a tool error result (PermissionError is caught by
        # the loop's error handling); the audit record must still exist.
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("too risky", results[0]["content"])
        lines = self._audit_lines()
        self.assertEqual(len(lines), 1)
        self.assertFalse(lines[0]["detail"]["approved"])
        self.assertEqual(lines[0]["detail"]["reason"], "too risky")

    def test_tool_without_approval_requirement_writes_nothing(self) -> None:
        agent = self._agent()
        tool = {"name": "safe_read", "requires_approval": False, "handler": lambda **args: "ok"}
        with patch.object(agent_loop, "approve") as mock_approve:
            results = agent._execute_tool_calls([{"name": "safe_read", "arguments": {}, "id": "call-1"}], tools=[tool])
        self.assertEqual(results[0]["status"], "success")
        mock_approve.assert_not_called()
        self.assertEqual(self._audit_lines(), [])

    def test_injected_audit_trail_is_used(self) -> None:
        memory = _MemoryAudit()
        agent = self._agent(audit_trail=memory)
        with patch.object(agent_loop, "approve", return_value=ApprovalResult.allow()):
            agent._execute_tool_calls(self._call(), tools=[self._danger_tool()])
        self.assertEqual(len(memory.records), 1)
        self.assertEqual(memory.records[0]["event"], "approval_decision")
        # No filesystem side effects when injected.
        self.assertEqual(self._audit_lines(), [])

    def test_explicit_state_dir_wins(self) -> None:
        other = self.state_dir.parent / "other-state"
        agent = self._agent(state_dir=other)
        trail = agent._audit_trail_instance()
        self.assertIsInstance(trail, AuditTrail)
        self.assertEqual(trail.path.parent, other / "audit")

    def test_config_state_dir_fallback(self) -> None:
        agent = self._agent()
        trail = agent._audit_trail_instance()
        self.assertEqual(trail.path.parent, self.state_dir / "audit")

    def test_default_state_dir_last_resort(self) -> None:
        agent = AIAgent(
            model_name="test-model",
            autonomy_profile=self.profile,
            config=None,
            state_dir=None,
        )
        # Keep the last-resort ~/.ghostchimera out of the runner's home.
        with patch("pathlib.Path.home", return_value=Path(self._dir.name)):
            trail = agent._audit_trail_instance()
        self.assertTrue(str(trail.path).endswith(".ghostchimera/audit/connector-audit.jsonl"))
        self.assertEqual(trail.path.parent.parent.parent, Path(self._dir.name))

    def test_approval_exception_still_surfaces_as_tool_error(self) -> None:
        agent = self._agent()
        with patch.object(agent_loop, "approve", side_effect=RuntimeError("handler blew up")):
            results = agent._execute_tool_calls(self._call(), tools=[self._danger_tool()])
        # No decision was made, so nothing is audited; the tool reports error.
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("handler blew up", results[0]["content"])
        self.assertEqual(self._audit_lines(), [])

    def test_broken_audit_trail_is_fail_open(self) -> None:
        # CodeRabbit #111: an audit failure must not turn an approved
        # tool call into an error.
        class BrokenAudit:
            def record(self, *args: Any, **kwargs: Any) -> None:
                raise OSError("disk gone")

        agent = self._agent(audit_trail=BrokenAudit())
        with (
            patch.object(agent_loop, "approve", return_value=ApprovalResult.allow()),
            self.assertLogs("ghostchimera.agent_loop", level="ERROR"),
        ):
            results = agent._execute_tool_calls(self._call(), tools=[self._danger_tool()])
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[0]["content"], "wrote")
