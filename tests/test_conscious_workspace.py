from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from ghostchimera.cognition_layer.reasoning import linearise_tasks
from ghostchimera.cognition_layer.workspace import (
    AttentionController,
    ReflectionEngine,
    SelfModel,
    WorkingMemory,
)
from ghostchimera.cognition_layer.workspace_state import OperatorWorkspaceStore
from ghostchimera.memory_layer.store import MemoryStore


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

    def test_reasoning_linearises_explicit_task_dependencies(self) -> None:
        tasks = [
            {"id": "deploy", "action": "shell", "depends_on": ["test"]},
            {"id": "build", "action": "shell"},
            {"id": "test", "action": "shell", "depends_on": "build"},
        ]

        ordered = linearise_tasks(tasks)

        self.assertEqual([task["id"] for task in ordered], ["build", "test", "deploy"])

    def test_reasoning_rejects_dependency_cycles(self) -> None:
        tasks = [
            {"id": "a", "action": "shell", "depends_on": "b"},
            {"id": "b", "action": "shell", "depends_on": "a"},
        ]

        with self.assertRaises(ValueError):
            linearise_tasks(tasks)

    def test_operator_workspace_persists_truthful_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-workspace-") as tmp:
            store = OperatorWorkspaceStore(state_dir=tmp)
            initial = store.snapshot()
            self.assertIn("no_subjective_consciousness", initial["self_model"]["limits"])

            store.add_evidence("release-audit", "console routes are registered", confidence=0.92)
            store.add_reflection(
                action="exposed workspace state",
                outcome="operator can inspect evidence without AGI claims",
                confidence=0.88,
            )
            store.set_goal("workspace_visibility", "show current evidence and uncertainty to local operators")

            reloaded = OperatorWorkspaceStore(state_dir=tmp)
            snapshot = reloaded.snapshot()

        self.assertEqual(snapshot["working_memory"]["evidence"][0]["source"], "release-audit")
        self.assertEqual(snapshot["working_memory"]["reflections"][0]["action"], "exposed workspace state")
        self.assertEqual(snapshot["self_model"]["goals"]["workspace_visibility"], "show current evidence and uncertainty to local operators")
        self.assertGreater(snapshot["attention"][0]["attention_score"], 0)
        self.assertLess(snapshot["uncertainty"]["score"], 1.0)

    def test_workspace_cli_reports_and_updates_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-workspace-cli-") as tmp:
            show = subprocess.run(
                [sys.executable, "-m", "ghostchimera.control_plane.cli", "workspace", "show", "--state-dir", tmp],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(show.returncode, 0, show.stderr)
            payload = json.loads(show.stdout)
            self.assertIn("self_model", payload)

            add = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "workspace",
                    "add-evidence",
                    "--state-dir",
                    tmp,
                    "--source",
                    "cli-test",
                    "--content",
                    "workspace command is reachable",
                    "--confidence",
                    "0.91",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            reflect = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "workspace",
                    "reflect",
                    "--state-dir",
                    tmp,
                    "--reflection-action",
                    "ran CLI smoke",
                    "--outcome",
                    "state persisted",
                    "--confidence",
                    "0.89",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(reflect.returncode, 0, reflect.stderr)

            final = json.loads(reflect.stdout)

        self.assertEqual(final["working_memory"]["evidence"][0]["source"], "cli-test")
        self.assertEqual(final["working_memory"]["reflections"][0]["outcome"], "state persisted")

    def test_operator_workspace_syncs_to_memory_store_idempotently(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-workspace-memory-") as tmp:
            memory_db = f"{tmp}/memory.sqlite3"
            store = OperatorWorkspaceStore(state_dir=tmp)
            store.add_evidence("operator-note", "workspace evidence should become CWR retrieval memory", confidence=0.94)
            store.add_reflection(action="sync workspace", outcome="reflection feeds retrieval", confidence=0.91)

            first = store.sync_to_memory(memory_db=memory_db, min_confidence=0.9)
            second = store.sync_to_memory(memory_db=memory_db, min_confidence=0.9)
            results = MemoryStore(memory_db).search("reflection retrieval", limit=5)

        self.assertTrue(first["ok"])
        self.assertEqual(first["synced"], 2)
        self.assertEqual(first["skipped"], 0)
        self.assertEqual(second["synced"], 0)
        self.assertEqual(second["skipped"], 2)
        self.assertEqual({item["metadata"]["workspace_type"] for item in results}, {"evidence", "reflection"})

    def test_workspace_sync_reports_low_confidence_stale_and_conflicting_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-workspace-quality-") as tmp:
            memory_db = f"{tmp}/memory.sqlite3"
            store = OperatorWorkspaceStore(state_dir=tmp)
            store.add_evidence("operator-note", "release gate passed yesterday", confidence=0.95)
            store.add_evidence("operator-note", "release gate failed yesterday", confidence=0.94)
            store.add_evidence("draft-note", "unreviewed low confidence finding", confidence=0.2)
            old_timestamp = (datetime.now(UTC) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
            store.memory.evidence[0]["timestamp"] = old_timestamp
            store.save()

            sync = store.sync_to_memory(memory_db=memory_db, min_confidence=0.8, stale_after_days=30)
            results = MemoryStore(memory_db).search("release gate yesterday", limit=5)

        self.assertEqual(sync["synced"], 2)
        self.assertEqual(sync["filtered"], 1)
        self.assertEqual(sync["quality"]["filtered_low_confidence"], 1)
        self.assertEqual(sync["quality"]["stale"], 1)
        self.assertEqual(sync["quality"]["conflicting"], 2)
        self.assertEqual(sync["filtered_documents"][0]["workspace_type"], "evidence")
        self.assertIn("low_confidence", sync["filtered_documents"][0]["quality_flags"])
        flags_by_content = {item["content"]: set(item["metadata"]["workspace_quality_flags"]) for item in results}
        self.assertIn("stale", flags_by_content["Workspace evidence from operator-note: release gate passed yesterday"])
        self.assertIn("conflicting", flags_by_content["Workspace evidence from operator-note: release gate passed yesterday"])
        self.assertEqual(flags_by_content["Workspace evidence from operator-note: release gate failed yesterday"], {"conflicting"})

    def test_workspace_cli_syncs_to_memory_db(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-workspace-cli-memory-") as tmp:
            memory_db = f"{tmp}/memory.sqlite3"
            add = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "workspace",
                    "add-evidence",
                    "--state-dir",
                    tmp,
                    "--source",
                    "cli-sync",
                    "--content",
                    "workspace sync command feeds retrieval",
                    "--confidence",
                    "0.95",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            sync = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "workspace",
                    "sync-memory",
                    "--state-dir",
                    tmp,
                    "--memory-db",
                    memory_db,
                    "--min-confidence",
                    "0.9",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(sync.returncode, 0, sync.stderr)
            payload = json.loads(sync.stdout)
            results = MemoryStore(memory_db).search("feeds retrieval", limit=3)

        self.assertEqual(payload["synced"], 1)
        self.assertEqual(results[0]["metadata"]["workspace_type"], "evidence")


if __name__ == "__main__":
    unittest.main()
