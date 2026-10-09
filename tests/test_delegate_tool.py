"""Tests for the model-callable delegate tool (v1.0 subagent delegation).

All model backends are faked: no network, no credentials, no real LLM calls.
Recursion is simulated via mock factories, never real unbounded recursion.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from ghostchimera.chimera_pilot.delegate_tool import (
    DEFAULT_MAX_DEPTH,
    TOOL_NAME,
    DelegateTool,
    DelegationBudget,
    register_delegate_toolset,
)
from ghostchimera.chimera_pilot.toolsets import ToolsetManager, ToolsetRegistry


class FakeSession:
    def __init__(self, session_id: str = "child-s1", turns: int = 3, tokens: int = 150) -> None:
        self.session_id = session_id
        self._turns = turns
        self.total_tokens = tokens

    def turn_count(self) -> int:
        return self._turns


class FakeAgent:
    """Scripted stand-in for AIAgent: no model calls."""

    _USE_DEFAULT_SESSION = object()

    def __init__(
        self,
        text: str = "fake result",
        session: FakeSession | None | object = _USE_DEFAULT_SESSION,
        block: threading.Event | None = None,
        block_seconds: float = 8.0,
        raise_exc: Exception | None = None,
    ) -> None:
        self.text = text
        self.session = FakeSession() if session is FakeAgent._USE_DEFAULT_SESSION else session
        self.block = block
        self.block_seconds = block_seconds
        self.raise_exc = raise_exc
        self.ran_with: tuple | None = None
        self.max_tool_rounds: int | None = None

    def run(self, objective: str, tools: list | None = None) -> str:
        self.ran_with = (objective, tools)
        if self.block is not None:
            self.block.wait(self.block_seconds)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.text


def make_tool(
    *,
    depth: int = 0,
    max_depth: int = DEFAULT_MAX_DEPTH,
    audit_file: str | None = None,
    factory=None,
    tool_registry: dict | None = None,
    default_budget: DelegationBudget | None = None,
    parent_session_id: str = "parent-s1",
) -> tuple[DelegateTool, list]:
    from ghostchimera.safety_layer.audit import AuditLog

    calls: list = []

    def spy_factory(**kwargs):
        calls.append(kwargs)
        if factory is not None:
            return factory(**kwargs)
        agent = FakeAgent()
        agent.max_tool_rounds = kwargs.get("max_steps")
        return agent

    audit = AuditLog(audit_file=audit_file) if audit_file else None
    tool = DelegateTool(
        parent_objective="parent objective",
        parent_session_id=parent_session_id,
        depth=depth,
        max_depth=max_depth,
        default_budget=default_budget,
        tool_registry=tool_registry,
        agent_factory=spy_factory,
        audit_log=audit,
    )
    return tool, calls


class DelegateToolDefinitionTests(unittest.TestCase):
    def test_tool_name(self) -> None:
        self.assertEqual(TOOL_NAME, "delegate")
        self.assertEqual(DelegateTool.TOOL_NAME, "delegate")

    def test_tool_definition_schema(self) -> None:
        definition = DelegateTool.tool_definition()
        self.assertEqual(definition.name, "delegate")
        self.assertTrue(definition.requires_approval)
        self.assertIn("objective", definition.schema["properties"])
        self.assertIn("objective", definition.schema["required"])

    def test_tool_dict_shape(self) -> None:
        tool, _ = make_tool()
        tool_dict = tool.as_tool_dict()
        self.assertEqual(tool_dict["name"], "delegate")
        self.assertTrue(tool_dict["requires_approval"])
        self.assertTrue(callable(tool_dict["handler"]))

    def test_registered_in_toolset_manager(self) -> None:
        registry = ToolsetRegistry()
        register_delegate_toolset(registry)
        self.assertIsNotNone(registry.get("delegation"))
        self.assertIn("delegate", registry.get("delegation").tool_names)

    def test_needs_approval_via_manager(self) -> None:
        registry = ToolsetRegistry()
        register_delegate_toolset(registry)
        manager = ToolsetManager(registry=registry)
        manager._active_toolsets = ["delegation"]
        manager._rebuild_disclosure()
        self.assertTrue(manager.needs_approval("delegate"))
        self.assertIn("delegate", [t.name for t in manager.active_tools])


class DelegateBudgetTests(unittest.TestCase):
    def test_clamped_defaults(self) -> None:
        budget = DelegationBudget.clamped()
        self.assertEqual((budget.max_steps, budget.timeout_seconds, budget.max_tokens), (20, 300, 16000))

    def test_clamped_bounds(self) -> None:
        budget = DelegationBudget.clamped(max_steps=0, timeout_seconds=99999, max_tokens=-5)
        self.assertEqual(budget.max_steps, 1)
        self.assertEqual(budget.timeout_seconds, 3600)
        self.assertEqual(budget.max_tokens, 256)

    def test_clamp_exact_bound_values(self) -> None:
        self.assertEqual(DelegationBudget.clamped(max_steps=10**9).max_steps, 100)
        self.assertEqual(DelegationBudget.clamped(max_steps=-(10**9)).max_steps, 1)
        self.assertEqual(DelegationBudget.clamped(timeout_seconds=-(10**9)).timeout_seconds, 5)
        self.assertEqual(DelegationBudget.clamped(timeout_seconds=10**9).timeout_seconds, 3600)
        self.assertEqual(DelegationBudget.clamped(max_tokens=10**9).max_tokens, 200000)
        self.assertEqual(DelegationBudget.clamped(max_tokens=-(10**9)).max_tokens, 256)
        self.assertEqual(DEFAULT_MAX_DEPTH, 2)

    def test_clamped_overrides_win(self) -> None:
        budget = DelegationBudget.clamped(max_steps=7, timeout_seconds=60, max_tokens=4000)
        self.assertEqual((budget.max_steps, budget.timeout_seconds, budget.max_tokens), (7, 60, 4000))

    def test_clamp_non_integer_falls_back_to_minimum(self) -> None:
        from ghostchimera.chimera_pilot.delegate_tool import _clamp

        self.assertEqual(_clamp("abc", 1, 100), 1)
        self.assertEqual(_clamp(None, 2, 50), 2)
        self.assertEqual(_clamp(3.99, 1, 100), 3)


class DelegateExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        os.environ["GHOSTCHIMERA_AUDIT_KEY"] = "test-key-for-delegate-tool"
        self.audit_file = str(Path(self.tmpdir) / "audit.json")

    def tearDown(self) -> None:
        os.environ.pop("GHOSTCHIMERA_AUDIT_KEY", None)

    def _audit_entries(self) -> list:
        with open(self.audit_file, encoding="utf-8") as f:
            return json.load(f)

    def test_success_within_budget(self) -> None:
        tool, calls = make_tool(audit_file=self.audit_file)
        receipt = tool.delegate(objective="summarize this", max_steps=5, max_tokens=1000)
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["result"], "fake result")
        self.assertEqual(receipt["turns_taken"], 3)
        self.assertEqual(receipt["tokens_used"], 150)
        self.assertEqual(receipt["depth"], 1)
        self.assertIsNone(receipt["budget_breach"])
        self.assertLess(receipt["duration_seconds"], 60)
        self.assertTrue(receipt["subagent_id"].startswith("subagent-d1-"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["depth"], 1)
        self.assertEqual(calls[0]["max_steps"], 5)
        # isolated child session recorded in audit trail
        entries = self._audit_entries()
        actions = [e["action"] for e in entries]
        self.assertIn("delegate.spawn", actions)
        self.assertIn("delegate.result", actions)
        spawn = next(e for e in entries if e["action"] == "delegate.spawn")
        self.assertEqual(spawn["details"]["parent_session_id"], "parent-s1")
        self.assertEqual(spawn["details"]["child_run_id"], receipt["subagent_id"])
        self.assertEqual(spawn["details"]["depth"], 1)
        self.assertNotEqual(spawn["details"]["child_run_id"], "parent-s1")

    def test_abandoned_worker_is_daemon(self) -> None:
        block = threading.Event()
        agent = FakeAgent(block=block, block_seconds=30.0)
        tool, _ = make_tool(audit_file=self.audit_file, factory=lambda **kw: agent)
        receipt = tool.delegate(objective="hang", timeout_seconds=5)
        self.assertEqual(receipt["budget_breach"], "timeout_seconds")
        workers = [t for t in threading.enumerate() if t.name.startswith("delegate-")]
        self.assertTrue(workers)
        self.assertTrue(all(t.daemon for t in workers))

    def test_timeout_breach_terminates(self) -> None:
        block = threading.Event()
        agent = FakeAgent(block=block, block_seconds=30.0)
        tool, _ = make_tool(audit_file=self.audit_file, factory=lambda **kw: agent)
        receipt = tool.delegate(objective="hang forever", timeout_seconds=5)
        self.assertFalse(receipt["success"])
        self.assertEqual(receipt["budget_breach"], "timeout_seconds")
        self.assertIn("wall-time budget exceeded", receipt["error"])
        entries = self._audit_entries()
        result = next(e for e in entries if e["action"] == "delegate.result")
        self.assertEqual(result["details"]["budget_breach"], "timeout_seconds")

    def test_token_breach_reported(self) -> None:
        agent = FakeAgent(session=FakeSession(tokens=99999))
        tool, _ = make_tool(audit_file=self.audit_file, factory=lambda **kw: agent)
        receipt = tool.delegate(objective="verbose", max_tokens=1000)
        self.assertFalse(receipt["success"])
        self.assertEqual(receipt["budget_breach"], "max_tokens")
        self.assertIn("token budget exceeded", receipt["error"])
        # partial result is still returned to the parent
        self.assertEqual(receipt["result"], "fake result")

    def test_child_failure_captured(self) -> None:
        agent = FakeAgent(raise_exc=RuntimeError("boom"))
        tool, _ = make_tool(audit_file=self.audit_file, factory=lambda **kw: agent)
        receipt = tool.delegate(objective="fail please")
        self.assertFalse(receipt["success"])
        self.assertIn("boom", receipt["error"])

    def test_factory_failure_returns_error_receipt(self) -> None:
        def bad_factory(**kwargs):
            raise RuntimeError("no agent for you")

        tool, _ = make_tool(audit_file=self.audit_file, factory=bad_factory)
        receipt = tool.delegate(objective="spawn me")
        self.assertFalse(receipt["success"])
        self.assertIn("child agent creation failed", receipt["error"])
        with open(self.audit_file, encoding="utf-8") as f:
            entries = json.load(f)
        result = next(e for e in entries if e["action"] == "delegate.result")
        self.assertFalse(result["details"]["success"])
        self.assertIn("child agent creation failed", result["details"]["error"])

    def test_broken_session_stats_default_to_zero(self) -> None:
        class BrokenSession:
            session_id = "broken-s1"

            def turn_count(self):
                raise RuntimeError("no stats")

            @property
            def total_tokens(self):
                raise RuntimeError("no stats")

        agent = FakeAgent(session=BrokenSession())
        tool, _ = make_tool(audit_file=self.audit_file, factory=lambda **kw: agent)
        receipt = tool.delegate(objective="statsless")
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["turns_taken"], 0)
        self.assertEqual(receipt["tokens_used"], 0)

    def test_no_session_defaults_stats_to_zero(self) -> None:
        agent = FakeAgent(session=None)
        tool, _ = make_tool(audit_file=self.audit_file, factory=lambda **kw: agent)
        receipt = tool.delegate(objective="sessionless")
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["turns_taken"], 0)
        self.assertEqual(receipt["tokens_used"], 0)

    def test_token_budget_exact_limit_no_breach(self) -> None:
        agent = FakeAgent(session=FakeSession(tokens=1000))
        tool, _ = make_tool(audit_file=self.audit_file, factory=lambda **kw: agent)
        receipt = tool.delegate(objective="exact", max_tokens=1000)
        self.assertTrue(receipt["success"])
        self.assertIsNone(receipt["budget_breach"])

    def test_zero_tokens_stays_zero(self) -> None:
        agent = FakeAgent(session=FakeSession(tokens=0))
        tool, _ = make_tool(audit_file=self.audit_file, factory=lambda **kw: agent)
        receipt = tool.delegate(objective="silent", max_tokens=1000)
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["tokens_used"], 0)

    def test_empty_objective_no_spawn(self) -> None:
        tool, calls = make_tool(audit_file=self.audit_file)
        receipt = tool.delegate(objective="   ")
        self.assertFalse(receipt["success"])
        self.assertIn("objective is required", receipt["error"])
        self.assertEqual(receipt["turns_taken"], 0)
        self.assertEqual(receipt["tokens_used"], 0)
        self.assertEqual(receipt["duration_seconds"], 0.0)
        self.assertEqual(calls, [])

    def test_depth_cap_refused_without_spawning(self) -> None:
        tool, calls = make_tool(audit_file=self.audit_file, depth=2, max_depth=2)
        receipt = tool.delegate(objective="recurse")
        self.assertFalse(receipt["success"])
        self.assertIn("depth cap", receipt["error"])
        self.assertEqual(receipt["turns_taken"], 0)
        self.assertEqual(receipt["tokens_used"], 0)
        self.assertEqual(calls, [])
        entries = self._audit_entries()
        refused = next(e for e in entries if e["action"] == "delegate.refused")
        self.assertEqual(refused["details"]["depth"], 2)

    def test_constructor_defaults(self) -> None:
        from ghostchimera.config import GhostChimeraConfig
        from ghostchimera.safety_layer.audit import AuditLog

        cfg = GhostChimeraConfig.from_env()
        tool = DelegateTool(
            parent_objective="x",
            config=cfg,
            audit_log=AuditLog(audit_file=str(Path(self.tmpdir) / "a.json")),
            agent_factory=lambda **kw: FakeAgent(),
        )
        self.assertEqual(tool.depth, 0)
        self.assertEqual(tool.max_depth, DEFAULT_MAX_DEPTH)
        self.assertIs(tool.config, cfg)

    def test_negative_max_depth_clamped_to_zero(self) -> None:
        tool, _ = make_tool(max_depth=-3)
        self.assertEqual(tool.max_depth, 0)


class DelegateDepthTests(unittest.TestCase):
    def test_child_tool_offered_below_cap(self) -> None:
        tool, _ = make_tool(depth=0, max_depth=2)
        nested = tool.child_tool()
        self.assertIsNotNone(nested)
        self.assertEqual(nested.depth, 1)

    def test_child_tool_none_at_cap(self) -> None:
        tool, _ = make_tool(depth=1, max_depth=2)
        self.assertIsNone(tool.child_tool())

    def test_nested_two_levels_simulated(self) -> None:
        # No real recursion: verify the depth-tracked tool chain by hand.
        parent, parent_calls = make_tool(depth=0, max_depth=2)
        child_tools = parent.build_child_tools()
        delegate_dicts = [t for t in child_tools if t["name"] == "delegate"]
        self.assertEqual(len(delegate_dicts), 1)
        nested = parent.child_tool()
        assert nested is not None
        # nested handler spawns at depth 1 with its own factory spy
        nested_calls: list = []

        def nested_factory(**kwargs):
            nested_calls.append(kwargs)
            return FakeAgent(text="nested done")

        nested.agent_factory = nested_factory
        receipt = nested.delegate(objective="level two")
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["depth"], 2)
        self.assertEqual(nested_calls[0]["depth"], 2)
        # grandchild gets no delegate tool: chain ends here
        grandchild_tools = nested.build_child_tools()
        self.assertEqual([t for t in grandchild_tools if t["name"] == "delegate"], [])

    def test_blocked_tools_filtered(self) -> None:
        registry = {"read_file": {"name": "read_file", "handler": lambda **kw: "x"}}
        tool, _ = make_tool(depth=0, max_depth=2, tool_registry=registry)
        child_tools = tool.build_child_tools(allowed_tools=["delegate", "delegate_task", "read_file"])
        names = [t["name"] for t in child_tools]
        # exactly one delegate tool: the depth-tracked nested one, not the raw names
        self.assertEqual(names.count("delegate"), 1)
        self.assertIn("read_file", names)
        self.assertNotIn("delegate_task", names)


class DelegateApprovalTests(unittest.TestCase):
    @patch("ghostchimera.chimera_pilot.agent_loop.approve")
    def test_denied_approval_blocks_handler(self, mock_approve) -> None:
        from ghostchimera.chimera_pilot.agent_loop import AIAgent
        from ghostchimera.safety_layer.approval import ApprovalResult

        mock_approve.return_value = ApprovalResult(approved=False, reason="Denied by policy")
        tool, calls = make_tool()
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        tools = [tool.as_tool_dict()]
        results = agent._execute_tool_calls(
            [{"id": "c1", "name": "delegate", "arguments": {"objective": "sensitive work"}}],
            tools=tools,
        )
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("Denied by policy", results[0]["content"])
        self.assertEqual(calls, [])
        mock_approve.assert_called_once()

    @patch("ghostchimera.chimera_pilot.agent_loop.approve")
    def test_allowed_approval_runs_delegation(self, mock_approve) -> None:
        from ghostchimera.chimera_pilot.agent_loop import AIAgent
        from ghostchimera.safety_layer.approval import ApprovalResult

        mock_approve.return_value = ApprovalResult(approved=True, reason="ok")
        tool, calls = make_tool()
        agent = AIAgent(model_name="claude-haiku-4-20250514")
        tools = [tool.as_tool_dict()]
        results = agent._execute_tool_calls(
            [{"id": "c1", "name": "delegate", "arguments": {"objective": "do it"}}],
            tools=tools,
        )
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(len(calls), 1)
        content = json.loads(results[0]["content"])
        self.assertTrue(content["success"])


class DelegateHardeningTests(unittest.TestCase):
    """Kill surviving mutants: truncation, rounding, depth arithmetic, audit failure."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        os.environ["GHOSTCHIMERA_AUDIT_KEY"] = "test-key-for-delegate-tool"
        self.audit_file = str(Path(self.tmpdir) / "audit.json")

    def tearDown(self) -> None:
        os.environ.pop("GHOSTCHIMERA_AUDIT_KEY", None)

    def test_nested_delegate_inherits_narrowed_allowance(self) -> None:
        # CodeRabbit #110: the nested delegate tool must not widen the
        # child's narrowed tool allowance back to the parent's full list.
        registry = {
            "read_file": {"name": "read_file", "handler": lambda **kw: "r"},
            "write_file": {"name": "write_file", "handler": lambda **kw: "w"},
        }
        tool, _ = make_tool(tool_registry=registry)
        child_tools = tool.build_child_tools(allowed_tools=["read_file"])
        nested_dict = next(t for t in child_tools if t["name"] == "delegate")
        nested_tool = nested_dict["handler"].__self__
        self.assertEqual(nested_tool.allowed_tools, ["read_file"])
        self.assertNotIn("write_file", nested_tool.allowed_tools)

    def test_timed_out_child_tools_refuse_after_cancel(self) -> None:
        # CodeRabbit #110: after a wall-time breach, the abandoned child
        # must not be able to start new tool calls.
        block = threading.Event()
        seen_tools: list = []

        def slow_factory(**kwargs):
            agent = FakeAgent(block=block, block_seconds=30.0)

            def run(objective, tools=None):
                seen_tools.append(list(tools or []))
                return agent.__class__.run(agent, objective, tools)

            agent.run = run
            return agent

        registry = {"read_file": {"name": "read_file", "handler": lambda **kw: "r"}}
        # MIN_TIMEOUT_SECONDS is 5; the child blocks 30s so the wait always breaches.
        budget = DelegationBudget(timeout_seconds=5)
        tool, _ = make_tool(factory=slow_factory, tool_registry=registry, default_budget=budget)
        receipt = tool.delegate(objective="slow", allowed_tools=["read_file"])
        self.assertFalse(receipt["success"])
        self.assertIn("wall-time", receipt["error"])
        block.set()
        handler = next(t["handler"] for t in seen_tools[0] if t["name"] == "read_file")
        with self.assertRaises(RuntimeError):
            handler()

    def test_result_truncated_at_8000_chars(self) -> None:
        agent = FakeAgent(text="x" * 9000)
        tool, _ = make_tool(audit_file=self.audit_file, factory=lambda **kw: agent)
        receipt = tool.delegate(objective="long output")
        self.assertEqual(len(receipt["result"]), 8000)
        self.assertTrue(receipt["success"])

    def test_duration_rounded_to_two_decimals(self) -> None:
        import time as _time

        tool, _ = make_tool(audit_file=self.audit_file)
        budget = DelegationBudget()
        receipt = tool._record_result("c1", "obj", budget, 0.0, success=True, error=None, duration_seconds=1.23456)
        self.assertEqual(receipt["duration_seconds"], 1.23)
        self.assertEqual(receipt["turns_taken"], 0)
        self.assertEqual(receipt["tokens_used"], 0)
        with open(self.audit_file, encoding="utf-8") as f:
            entries = json.load(f)
        result = next(e for e in entries if e["action"] == "delegate.result")
        self.assertEqual(result["details"]["duration_seconds"], 1.23)
        # fallback path: duration measured from start when not supplied
        receipt2 = tool._record_result("c2", "obj", budget, _time.time() - 5, success=True, error=None)
        self.assertLess(receipt2["duration_seconds"], 60)

    def test_failure_receipt_depth_is_parent_plus_one(self) -> None:
        tool, _ = make_tool(audit_file=self.audit_file, depth=1, max_depth=5)
        receipt = tool.delegate(objective="   ")
        self.assertFalse(receipt["success"])
        self.assertEqual(receipt["depth"], 2)

    def test_audit_result_details_carry_depth(self) -> None:
        tool, _ = make_tool(audit_file=self.audit_file)
        tool.delegate(objective="check depth audit")
        with open(self.audit_file, encoding="utf-8") as f:
            entries = json.load(f)
        result = next(e for e in entries if e["action"] == "delegate.result")
        self.assertEqual(result["details"]["depth"], 1)

    def test_audit_failure_does_not_break_delegation(self) -> None:
        class BadAudit:
            def record(self, action, details):
                raise OSError("disk gone")

        tool, calls = make_tool(audit_file=self.audit_file)
        tool.audit_log = BadAudit()
        with self.assertLogs("ghostchimera.delegate_tool", level="WARNING") as logs:
            receipt = tool.delegate(objective="still works")
        self.assertTrue(receipt["success"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(any("audit write failed" in message for message in logs.output))

    def test_default_agent_factory_builds_isolated_child(self) -> None:
        from ghostchimera.chimera_pilot.delegate_tool import _default_agent_factory
        from ghostchimera.config import GhostChimeraConfig

        agent = _default_agent_factory(
            objective="do the thing",
            parent_objective="parent obj",
            depth=1,
            max_steps=7,
            tools=[{"name": "read_file"}],
            config=GhostChimeraConfig.from_env(),
        )
        self.assertEqual(agent.max_tool_rounds, 7)
        self.assertTrue(agent.session.session_id.startswith("subagent-d1-"))
        self.assertIn("parent obj", agent.session.system_prompt)


class DelegateBuiltinRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self._old_state_dir = os.environ.get("GHOSTCHIMERA_STATE_DIR")
        os.environ["GHOSTCHIMERA_STATE_DIR"] = self.tmpdir

    def tearDown(self) -> None:
        if self._old_state_dir is None:
            os.environ.pop("GHOSTCHIMERA_STATE_DIR", None)
        else:
            os.environ["GHOSTCHIMERA_STATE_DIR"] = self._old_state_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_builtin_toolsets_include_delegation(self) -> None:
        registry = ToolsetRegistry()
        registry.register_builtin_toolsets()
        delegation = registry.get("delegation")
        self.assertIsNotNone(delegation)
        self.assertIn("delegate", delegation.tool_names)
        tool_def = next(t for t in delegation.tools if t.name == "delegate")
        self.assertTrue(tool_def.requires_approval)

    def test_builtin_coding_toolset_approvals_intact(self) -> None:
        registry = ToolsetRegistry()
        registry.register_builtin_toolsets()
        coding = registry.get("coding")
        self.assertIsNotNone(coding)
        by_name = {t.name: t for t in coding.tools}
        self.assertTrue(by_name["write_file"].requires_approval)
        self.assertTrue(by_name["shell"].requires_approval)
        self.assertFalse(by_name["read_file"].requires_approval)

    def test_builtin_research_toolset_registered(self) -> None:
        registry = ToolsetRegistry()
        registry.register_builtin_toolsets()
        research = registry.get("research")
        self.assertIsNotNone(research)
        by_name = {t.name: t for t in research.tools}
        self.assertEqual(set(by_name), {"http_get", "web_research", "code_search", "rag_query"})
        self.assertTrue(by_name["http_get"].requires_approval)
        self.assertTrue(by_name["web_research"].requires_approval)
        self.assertFalse(by_name["code_search"].requires_approval)
        self.assertFalse(by_name["rag_query"].requires_approval)

    def test_builtin_safety_toolset_registered(self) -> None:
        registry = ToolsetRegistry()
        registry.register_builtin_toolsets()
        safety = registry.get("safety")
        self.assertIsNotNone(safety)
        by_name = {t.name: t for t in safety.tools}
        self.assertEqual(set(by_name), {"safety_check", "hallucination_detect"})
        self.assertFalse(by_name["safety_check"].requires_approval)

    def test_builtin_devops_toolset_registered(self) -> None:
        registry = ToolsetRegistry()
        registry.register_builtin_toolsets()
        devops = registry.get("devops")
        self.assertIsNotNone(devops)
        by_name = {t.name: t for t in devops.tools}
        self.assertEqual(set(by_name), {"test_run", "lint", "build"})
        self.assertTrue(by_name["test_run"].requires_approval)
        self.assertTrue(by_name["build"].requires_approval)
        self.assertFalse(by_name["lint"].requires_approval)

    def test_builtin_toolset_permissions(self) -> None:
        registry = ToolsetRegistry()
        registry.register_builtin_toolsets()
        self.assertEqual(
            registry.get("coding").permissions,
            {"allow_shell": True, "allow_file_write": True, "allow_file_read": True},
        )
        self.assertEqual(registry.get("research").permissions, {"allow_network": True})
        self.assertEqual(registry.get("devops").permissions, {"allow_shell": True})

    def test_builtin_mcp_toolset_registered_when_tools_available(self) -> None:
        from unittest.mock import patch

        registry = ToolsetRegistry()
        fake_tools = [
            {"name": "mcp_search", "description": "search", "inputSchema": {"type": "object"}},
            {"name": "mcp_fetch", "description": "fetch", "inputSchema": {"type": "object"}},
        ]
        with patch("ghostchimera.chimera_pilot.toolsets.list_available_tools", return_value=fake_tools):
            registry.register_builtin_toolsets()
        mcp = registry.get("mcp")
        self.assertIsNotNone(mcp)
        self.assertEqual(set(mcp.tool_names), {"mcp_search", "mcp_fetch"})
        self.assertEqual(mcp.permissions, {"allow_network": True})

    def test_builtin_mcp_toolset_truncates_at_fifty_tools(self) -> None:
        from unittest.mock import patch

        registry = ToolsetRegistry()
        fake_tools = [{"name": f"mcp_tool_{i}", "description": "d", "inputSchema": {}} for i in range(60)]
        with patch("ghostchimera.chimera_pilot.toolsets.list_available_tools", return_value=fake_tools):
            registry.register_builtin_toolsets()
        mcp = registry.get("mcp")
        self.assertIsNotNone(mcp)
        self.assertEqual(mcp.tool_count, 50)

    def test_builtin_toolsets_survive_mcp_discovery_failure(self) -> None:
        from unittest.mock import patch

        registry = ToolsetRegistry()
        with (
            patch("ghostchimera.chimera_pilot.toolsets.list_available_tools", side_effect=RuntimeError("mcp down")),
            self.assertLogs("ghostchimera.toolsets", level="DEBUG") as logs,
        ):
            registry.register_builtin_toolsets()
        self.assertIsNotNone(registry.get("delegation"))
        self.assertIsNotNone(registry.get("coding"))
        self.assertIsNone(registry.get("mcp"))
        self.assertTrue(any("MCP toolset discovery failed" in message for message in logs.output))

    def test_get_mcp_tools_survives_discovery_failure(self) -> None:
        from unittest.mock import patch

        registry = ToolsetRegistry()
        with patch("ghostchimera.chimera_pilot.toolsets.list_available_tools", side_effect=RuntimeError("mcp down")):
            self.assertEqual(registry.get_mcp_tools(), [])

    def test_load_active_corrupt_json_falls_back_to_default(self) -> None:
        state_file = Path(self.tmpdir) / "active_toolsets.json"
        state_file.write_text("{not valid json", encoding="utf-8")
        manager = ToolsetManager(registry=ToolsetRegistry())
        self.assertEqual(manager._active_toolsets, ["coding", "delegation"])

    def test_load_active_missing_key_falls_back_to_default(self) -> None:
        state_file = Path(self.tmpdir) / "active_toolsets.json"
        state_file.write_text(json.dumps({"other": []}), encoding="utf-8")
        manager = ToolsetManager(registry=ToolsetRegistry())
        self.assertEqual(manager._active_toolsets, ["coding", "delegation"])


if __name__ == "__main__":
    unittest.main()
