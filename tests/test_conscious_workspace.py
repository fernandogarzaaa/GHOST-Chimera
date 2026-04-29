from __future__ import annotations

import unittest

from ghostchimera.cognition_layer.workspace import (
    AttentionController,
    ReflectionEngine,
    SelfModel,
    WorkingMemory,
)


class ConsciousWorkspaceTests(unittest.TestCase):
    def test_self_model_records_capabilities_limits_and_goals(self) -> None:
        model = SelfModel(identity="ghost-chimera")
        model.add_capability("cwr", "retrieves local memory with citations")
        model.add_limit("no_proven_consciousness", "does not claim subjective experience")
        model.set_goal("production_ready", "pass release and safety gates")

        snapshot = model.snapshot()

        self.assertEqual(snapshot["identity"], "ghost-chimera")
        self.assertEqual(snapshot["capabilities"]["cwr"], "retrieves local memory with citations")
        self.assertIn("no_proven_consciousness", snapshot["limits"])
        self.assertEqual(snapshot["goals"]["production_ready"], "pass release and safety gates")

    def test_attention_controller_ranks_working_memory_items(self) -> None:
        controller = AttentionController()
        ranked = controller.rank(
            [
                {"content": "old unrelated note", "relevance": 0.1, "trust": 0.5, "recency": 0.1},
                {"content": "trusted current safety policy", "relevance": 0.9, "trust": 0.9, "recency": 0.8},
            ]
        )

        self.assertEqual(ranked[0]["content"], "trusted current safety policy")
        self.assertGreater(ranked[0]["attention_score"], ranked[1]["attention_score"])

    def test_working_memory_tracks_task_evidence_and_reflections(self) -> None:
        memory = WorkingMemory(task="ship safe Ghost Chimera")
        memory.add_evidence("audit", "shell is policy gated", confidence=0.95)
        ReflectionEngine().record(memory, action="implemented safety policy", outcome="tests pass", confidence=0.96)

        snapshot = memory.snapshot()

        self.assertEqual(snapshot["task"], "ship safe Ghost Chimera")
        self.assertEqual(snapshot["evidence"][0]["source"], "audit")
        self.assertEqual(snapshot["reflections"][0]["outcome"], "tests pass")


if __name__ == "__main__":
    unittest.main()
