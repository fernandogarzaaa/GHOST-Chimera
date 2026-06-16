from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot import ChimeraPilotKernel, TaskKind, TaskSpec
from ghostchimera.chimera_pilot.backends.cwr import CWRBackend
from ghostchimera.memory_layer.store import MemoryStore
from ghostchimera.memory_layer.temporal_graph import TemporalGraphStore


class ConsciousWorkspaceRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="ghostchimera-cwr-test-")
        self.db_path = Path(self.tmp.name) / "memory.sqlite3"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_memory_store_indexes_and_searches_documents(self) -> None:
        store = MemoryStore(self.db_path)
        store.add_document(
            source="project-note",
            content="Ghost Chimera should use Conscious Workspace Retrieval for memory-backed reasoning.",
            metadata={"kind": "note"},
        )

        results = store.search("workspace retrieval")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "project-note")
        self.assertIn("Conscious Workspace Retrieval", results[0]["content"])
        self.assertGreater(results[0]["score"], 0)

    def test_cwr_backend_executes_rag_query_with_citations(self) -> None:
        store = MemoryStore(self.db_path)
        store.add_document("architecture", "Chimera Pilot should run retrieval through a real backend.")
        backend = CWRBackend(store=store)
        task = TaskSpec.create(kind=TaskKind.RAG_QUERY, objective="retrieve chimera pilot backend")

        result = backend.execute(task)

        self.assertTrue(result.ok)
        self.assertEqual(result.backend_id, "cwr.local")
        self.assertEqual(result.output["query"], "retrieve chimera pilot backend")
        self.assertEqual(result.output["citations"], ["architecture"])
        self.assertIn("Chimera Pilot", result.output["results"][0]["content"])

    def test_cwr_without_graph_has_no_facts_key(self) -> None:
        store = MemoryStore(self.db_path)
        store.add_document("architecture", "Chimera Pilot runs retrieval through a real backend.")
        backend = CWRBackend(store=store)
        result = backend.execute(
            TaskSpec.create(kind=TaskKind.RAG_QUERY, objective="chimera pilot backend")
        )
        self.assertNotIn("facts", result.output)
        self.assertEqual(result.metrics["retrieval"], "sqlite_fts")

    def test_cwr_fuses_temporal_graph_facts(self) -> None:
        store = MemoryStore(self.db_path)
        store.add_document("note", "Globex onboarding chat about benefits and tooling.")
        graph = TemporalGraphStore(Path(self.tmp.name) / "graph.sqlite3")
        graph.add_fact("Globex", "located_in", obj="Springfield", confidence=0.9)
        graph.add_fact("Globex", "industry", obj="energy", confidence=0.8)
        backend = CWRBackend(store=store, graph=graph)

        result = backend.execute(
            TaskSpec.create(kind=TaskKind.RAG_QUERY, objective="what about Globex")
        )

        self.assertTrue(result.ok)
        self.assertIn("facts", result.output)
        predicates = {f["predicate"] for f in result.output["facts"]}
        self.assertEqual(predicates, {"located_in", "industry"})
        self.assertEqual(result.metrics["retrieval"], "sqlite_fts+temporal_graph")
        self.assertTrue(any(c.startswith("graph:Globex/") for c in result.output["citations"]))
        # Highest-confidence fact ranks first.
        self.assertEqual(result.output["facts"][0]["predicate"], "located_in")

    def test_cwr_graph_ignores_stopword_only_query(self) -> None:
        store = MemoryStore(self.db_path)
        store.add_document("note", "some content")
        graph = TemporalGraphStore(Path(self.tmp.name) / "graph2.sqlite3")
        graph.add_fact("Globex", "located_in", obj="Springfield")
        backend = CWRBackend(store=store, graph=graph)
        result = backend.execute(TaskSpec.create(kind=TaskKind.RAG_QUERY, objective="what is it"))
        self.assertNotIn("facts", result.output)

    def test_memory_store_records_orchestration_outcomes(self) -> None:
        store = MemoryStore(self.db_path)
        row_id = store.record_outcome(
            backend_id="cwr.local",
            task_kind="rag_query",
            success=True,
            latency_ms=12.5,
            verifier_score=1.0,
            policy_warnings=["none"],
        )
        self.assertGreater(row_id, 0)
        outcomes = store.recent_outcomes(limit=5)
        self.assertGreaterEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["backend_id"], "cwr.local")

    def test_kernel_prefers_real_cwr_backend_over_deterministic_fallback(self) -> None:
        store = MemoryStore(self.db_path)
        store.add_document("memory", "Ghost Chimera remembers project goals through CWR.")
        kernel = ChimeraPilotKernel.default(include_deterministic_backend=True, memory_store=store)

        execution = kernel.run("retrieve project goals")[0]

        self.assertTrue(execution.ok)
        self.assertEqual(execution.result.backend_id, "cwr.local")
        self.assertNotEqual(execution.result.output, "ok")
        self.assertEqual(execution.result.output["citations"], ["memory"])
        outcomes = store.recent_outcomes(limit=1)
        self.assertEqual(outcomes[0]["backend_id"], "cwr.local")

    def test_cli_can_add_search_and_run_against_memory_db(self) -> None:
        add = subprocess.run(
            [
                sys.executable,
                "-m",
                "ghostchimera.chimera_pilot.cli",
                "memory-add",
                "--memory-db",
                str(self.db_path),
                "--source",
                "goals",
                "--content",
                "Ghost Chimera production readiness depends on CWR memory.",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(add.returncode, 0, add.stderr)
        self.assertEqual(json.loads(add.stdout)["source"], "goals")

        search = subprocess.run(
            [
                sys.executable,
                "-m",
                "ghostchimera.chimera_pilot.cli",
                "memory-search",
                "--memory-db",
                str(self.db_path),
                "production readiness",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(search.returncode, 0, search.stderr)
        self.assertEqual(json.loads(search.stdout)["results"][0]["source"], "goals")

        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "ghostchimera.chimera_pilot.cli",
                "run",
                "retrieve production readiness",
                "--memory-db",
                str(self.db_path),
                "--include-deterministic-backend",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual(payload[0]["backend_id"], "cwr.local")
        self.assertEqual(payload[0]["output"]["citations"], ["goals"])


if __name__ == "__main__":
    unittest.main()
