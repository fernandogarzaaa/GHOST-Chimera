"""Tests for the Hermes-Agent migration: subagent.py and mixture_of_agents.py."""

from __future__ import annotations

import threading
import unittest

from ghostchimera.chimera_pilot.mixture_of_agents import (
    DEFAULT_NUM_AGENTS,
    MixtureOfAgents,
    MoAConfig,
    get_moa,
)
from ghostchimera.chimera_pilot.subagent import (
    DelegationContract,
    DelegationResult,
    SubagentPool,
    SubagentResult,
    SubagentTask,
    delegate,
)


class SubagentTaskTests(unittest.TestCase):
    def test_is_deeper_than_cap_default(self) -> None:
        task = SubagentTask(id="t1", goal="test", depth=0, max_depth=1)
        self.assertFalse(task.is_deeper_than_cap())

    def test_is_deeper_than_cap_exceeded(self) -> None:
        task = SubagentTask(id="t1", goal="test", depth=2, max_depth=1)
        self.assertTrue(task.is_deeper_than_cap())


class SubagentResultTests(unittest.TestCase):
    def test_to_dict(self) -> None:
        result = SubagentResult(
            id="t1", goal="test", result="done", success=True, duration_seconds=1.5, depth=0, turns_taken=3
        )
        d = result.to_dict()
        self.assertEqual(d["id"], "t1")
        self.assertEqual(d["success"], True)
        self.assertEqual(d["duration_seconds"], 1.5)


class DelegationResultTests(unittest.TestCase):
    def test_success_rate(self) -> None:
        results = [
            SubagentResult(id="1", goal="g", result="ok", success=True),
            SubagentResult(id="2", goal="g", result="ok", success=True),
            SubagentResult(id="3", goal="g", result="", success=False, error="fail"),
        ]
        dr = DelegationResult(parent_objective="obj", results=results, successful_count=2, failed_count=1)
        self.assertEqual(dr.success_rate, 2 / 3)
        self.assertEqual(dr.successful_count, 2)
        self.assertEqual(dr.failed_count, 1)

    def test_to_dict(self) -> None:
        dr = DelegationResult(parent_objective="obj", results=[])
        d = dr.to_dict()
        self.assertIn("parent_objective", d)
        self.assertIn("success_rate", d)


class SubagentPoolTests(unittest.TestCase):
    def test_spawn(self) -> None:
        SubagentPool(parent_objective="test objective", max_workers=1)
        # spawn will try to create an AIAgent which needs kernel
        # We test the data structures rather than full execution
        task = SubagentTask(id="t1", goal="test goal", tools=["read_file"], depth=0)
        self.assertFalse(task.is_deeper_than_cap())

    def test_blocked_tools(self) -> None:
        pool = SubagentPool(parent_objective="test", blocked_tools=frozenset(["delegate_task"]))
        self.assertIn("delegate_task", pool.blocked_tools)

    def test_default_depth_cap(self) -> None:
        pool = SubagentPool(parent_objective="test")
        self.assertEqual(pool.depth_cap, 1)

    def test_depth_cap_configurable(self) -> None:
        pool = SubagentPool(parent_objective="test", depth_cap=3)
        self.assertEqual(pool.depth_cap, 3)

    def test_results_collection(self) -> None:
        pool = SubagentPool(parent_objective="test")
        # Verify internal state
        self.assertEqual(len(pool._results), 0)

    def test_delegation_contract_filters_tools_and_clamps_limits(self) -> None:
        pool = SubagentPool(parent_objective="test", max_workers=5, depth_cap=4, timeout=900)
        contract = DelegationContract(
            allowed_tools=["read_file"],
            max_depth=2,
            max_workers=2,
            max_timeout_seconds=60,
        )
        filtered = contract.enforce_tools(["read_file", "delegate_task"], pool.blocked_tools)
        self.assertEqual(filtered, ["read_file"])
        self.assertEqual(contract.clamp_workers(5), 2)
        self.assertEqual(contract.clamp_timeout(900), 60)

    def test_spawn_parallel_with_contract_empty_goals(self) -> None:
        pool = SubagentPool(parent_objective="test", max_workers=5, depth_cap=4, timeout=900)
        contract = DelegationContract(
            allowed_tools=["read_file"],
            max_depth=2,
            max_workers=2,
            max_timeout_seconds=60,
        )
        result = pool.spawn_parallel_with_contract([], contract=contract, tools=["read_file", "delegate_task"])
        self.assertEqual(result.successful_count, 0)
        self.assertEqual(result.failed_count, 0)

    def test_thread_safety(self) -> None:
        pool = SubagentPool(parent_objective="test")
        errors: list[Exception] = []

        def add_results(n: int) -> None:
            for i in range(n):
                try:
                    r = SubagentResult(id=f"t-{i}", goal="test", result=f"result {i}", success=True)
                    with pool._lock:
                        pool._results.append(r)
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=add_results, args=(50,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(pool._results), 250)


class MoAConfigTests(unittest.TestCase):
    def test_default_config(self) -> None:
        config = MoAConfig()
        self.assertEqual(config.num_agents, DEFAULT_NUM_AGENTS)
        self.assertEqual(config.temperature, 0.7)
        self.assertEqual(config.voting_strategy, "majority")

    def test_custom_config(self) -> None:
        config = MoAConfig(num_agents=5, temperature=0.9, voting_strategy="weighted")
        self.assertEqual(config.num_agents, 5)
        self.assertEqual(config.temperature, 0.9)


class MixtureOfAgentsTests(unittest.TestCase):
    def test_create_instance(self) -> None:
        moa = MixtureOfAgents()
        self.assertEqual(moa.config.num_agents, DEFAULT_NUM_AGENTS)

    def test_score_output_specificity(self) -> None:
        moa = MixtureOfAgents()
        specific = "The answer is 42 with 95% confidence in 2024"
        vague = "I think it might be something"
        self.assertGreater(moa.score_output(specific, "test query"), moa.score_output(vague, "test query"))

    def test_score_output_hedge_penalty(self) -> None:
        moa = MixtureOfAgents()
        hedged = "Perhaps it might possibly be unclear"
        confident = "The answer is definitively yes"
        self.assertGreater(moa.score_output(confident, "test"), moa.score_output(hedged, "test"))

    def test_jaccard_similarity_identical(self) -> None:
        moa = MixtureOfAgents()
        sim = moa._jaccard_similarity("hello world test", "hello world test")
        self.assertEqual(sim, 1.0)

    def test_jaccard_similarity_empty(self) -> None:
        moa = MixtureOfAgents()
        sim = moa._jaccard_similarity("", "hello")
        self.assertEqual(sim, 0.0)

    def test_find_consensus_empty(self) -> None:
        moa = MixtureOfAgents()
        answer, pct = moa._find_consensus([])
        self.assertEqual(answer, "")
        self.assertEqual(pct, 0.0)

    def test_status(self) -> None:
        moa = MixtureOfAgents()
        status = moa.status()
        self.assertEqual(status["voting_strategy"], "majority")
        self.assertIn("run_count", status)

    def test_spawn_agents(self) -> None:
        moa = MixtureOfAgents()
        agents = moa._spawn_agents("test query", ["You are analytical"])
        self.assertEqual(len(agents), 1)
        self.assertIn("agent", agents[0])
        self.assertEqual(agents[0]["query"], "test query")

    def test_score_outputs_all(self) -> None:
        moa = MixtureOfAgents()
        results = [
            {"agent_output": "specific answer with 42 numbers", "success": True, "agent_index": 0},
            {"agent_output": "", "success": False, "agent_index": 1},
        ]
        scored = moa._score_outputs(results, "query")
        self.assertEqual(len(scored), 2)
        self.assertGreater(scored[0]["score"], 0)
        self.assertEqual(scored[1]["score"], 0.0)

    def test_get_moa(self) -> None:
        moa = get_moa(num_agents=5)
        self.assertEqual(moa.config.num_agents, 5)


class DelegateFunctionTests(unittest.TestCase):
    def test_delegate_creates_pool(self) -> None:
        result = delegate(
            objective="test objective",
            goals=["goal1", "goal2"],
            max_workers=2,
            depth_cap=1,
        )
        # delegate() calls spawn_parallel which needs AIAgent execution
        # We verify the function exists and accepts the right params
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
