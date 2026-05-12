"""Unit tests for workspace_context_for_objective and kernel workspace injection."""

from __future__ import annotations

import tempfile
import unittest

from ghostchimera.chimera_pilot.kernel import ChimeraPilotKernel
from ghostchimera.cognition_layer.workspace_state import OperatorWorkspaceStore


class WorkspaceContextForObjectiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="gc-ws-ctx-test-")
        self.ws = OperatorWorkspaceStore(state_dir=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_returns_relevant_evidence_for_matching_objective(self) -> None:
        self.ws.add_evidence("policy-doc", "shell execution must be policy-gated for all deployments", confidence=0.95)
        items = self.ws.workspace_context_for_objective("policy gated shell execution", min_confidence=0.5)
        self.assertTrue(items)
        self.assertEqual(items[0]["type"], "evidence")
        self.assertIn("source", items[0])
        self.assertIn("content", items[0])
        self.assertIn("confidence", items[0])
        self.assertIn("relevance_hint", items[0])

    def test_returns_empty_list_when_no_match(self) -> None:
        self.ws.add_evidence("ui-notes", "the button should be blue", confidence=0.9)
        items = self.ws.workspace_context_for_objective("quantum simulation kinematics", min_confidence=0.5)
        self.assertEqual(items, [])

    def test_filters_by_min_confidence(self) -> None:
        self.ws.add_evidence("low-conf", "policy might need review possibly", confidence=0.3)
        items = self.ws.workspace_context_for_objective("policy review", min_confidence=0.8)
        self.assertEqual(items, [])
        items_low_threshold = self.ws.workspace_context_for_objective("policy review", min_confidence=0.2)
        self.assertTrue(items_low_threshold)

    def test_includes_reflections(self) -> None:
        self.ws.add_reflection(
            action="policy-test",
            outcome="policy gates passed all integration tests",
            confidence=0.92,
        )
        items = self.ws.workspace_context_for_objective("policy integration tests", min_confidence=0.5)
        types = {item["type"] for item in items}
        self.assertIn("reflection", types)

    def test_respects_limit(self) -> None:
        for i in range(10):
            self.ws.add_evidence(f"doc-{i}", f"memory retrieval test item number {i}", confidence=0.9)
        items = self.ws.workspace_context_for_objective("memory retrieval test", limit=3)
        self.assertLessEqual(len(items), 3)

    def test_sorted_by_relevance_descending(self) -> None:
        self.ws.add_evidence("partial", "retrieval", confidence=0.9)
        self.ws.add_evidence("exact", "memory retrieval quality test", confidence=0.9)
        items = self.ws.workspace_context_for_objective("memory retrieval quality test")
        if len(items) >= 2:
            self.assertGreaterEqual(items[0]["relevance_hint"], items[-1]["relevance_hint"])

    def test_empty_workspace_returns_empty(self) -> None:
        items = self.ws.workspace_context_for_objective("anything at all", min_confidence=0.0)
        # Default workspace has no user evidence yet (seeded goals/capabilities are in self_model, not memory)
        # Only user-added evidence/reflections count
        self.assertEqual(items, [])


class KernelWorkspaceInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="gc-kernel-ws-test-")
        self.ws = OperatorWorkspaceStore(state_dir=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_compile_injects_workspace_context_when_relevant(self) -> None:
        self.ws.add_evidence(
            "release-audit",
            "shell execution policy gates passed on 2026-01-01",
            confidence=0.95,
        )
        kernel = ChimeraPilotKernel(workspace_store=self.ws)
        tasks = kernel.compile("retrieve policy shell execution audit logs")
        context_items = tasks[0].constraints.get("workspace_context", [])
        self.assertGreater(len(context_items), 0)
        self.assertEqual(context_items[0]["type"], "evidence")

    def test_compile_does_not_inject_unrelated_context(self) -> None:
        self.ws.add_evidence("color-notes", "the dashboard should use dark blue", confidence=0.9)
        kernel = ChimeraPilotKernel(workspace_store=self.ws)
        tasks = kernel.compile("rag quantum simulation for orbital mechanics")
        context_items = tasks[0].constraints.get("workspace_context", [])
        self.assertEqual(len(context_items), 0)

    def test_compile_without_workspace_store_has_no_context(self) -> None:
        kernel = ChimeraPilotKernel()
        tasks = kernel.compile("retrieve local memory documents")
        context_items = tasks[0].constraints.get("workspace_context", [])
        self.assertEqual(len(context_items), 0)

    def test_workspace_context_does_not_break_task_structure(self) -> None:
        self.ws.add_evidence("test-note", "CWR retrieval is working correctly", confidence=0.9)
        kernel = ChimeraPilotKernel(workspace_store=self.ws)
        tasks = kernel.compile("retrieve CWR data")
        for task in tasks:
            self.assertIsNotNone(task.id)
            self.assertIsNotNone(task.kind)
            self.assertIsInstance(task.constraints, dict)

    def test_workspace_store_stored_on_kernel(self) -> None:
        kernel = ChimeraPilotKernel(workspace_store=self.ws)
        self.assertIs(kernel.workspace_store, self.ws)

    def test_no_workspace_store_is_none(self) -> None:
        kernel = ChimeraPilotKernel()
        self.assertIsNone(kernel.workspace_store)


if __name__ == "__main__":
    unittest.main()
