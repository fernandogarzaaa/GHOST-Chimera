from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.kernel import ChimeraPilotKernel
from ghostchimera.chimera_pilot.task_ir import TaskKind
from ghostchimera.memory_layer.store import MemoryStore


class PersonalContextTests(unittest.TestCase):
    def test_kernel_injects_personal_context_into_reasoning_system(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-context-") as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite3")
            store.add_document("notes", "The user's preferred stack is Python and SQLite.")
            kernel = ChimeraPilotKernel.default(
                include_deterministic_backend=True,
                memory_store=store,
                enable_personal_context=True,
                enable_minimind_personal_context=False,
            )
            tasks = kernel.compile("What is my preferred stack?")
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].kind, TaskKind.REASONING)
            self.assertIn("personal_context", tasks[0].constraints)
            self.assertIn("preferred stack", str(tasks[0].inputs.get("system") or ""))

    def test_kernel_injects_personal_context_into_web_research_context_field(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-context-") as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite3")
            store.add_document("notes", "We use Kubernetes for container orchestration.")
            kernel = ChimeraPilotKernel.default(
                include_deterministic_backend=True,
                memory_store=store,
                enable_personal_context=True,
                enable_minimind_personal_context=False,
            )
            # WEB_RESEARCH task
            tasks = kernel.compile("research latest Kubernetes security patches")
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].kind, TaskKind.WEB_RESEARCH)
            self.assertIn("personal_context", tasks[0].constraints)
            # Context field injected (not query)
            self.assertIn("context", tasks[0].inputs)
            self.assertIn("Kubernetes", tasks[0].inputs["context"])

    def test_personal_context_stored_in_constraints_for_all_kinds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-context-") as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite3")
            store.add_document("notes", "PostgreSQL is used for all primary data storage.")
            kernel = ChimeraPilotKernel.default(
                include_deterministic_backend=True,
                memory_store=store,
                enable_personal_context=True,
                enable_minimind_personal_context=False,
            )
            # Use an objective that matches the stored document via FTS
            tasks = kernel.compile("What database do we use for primary storage?")
            self.assertTrue(len(tasks) > 0)
            # At least one task should have personal_context injected
            # (FTS must return the PostgreSQL document for a db-related query)
            tasks_with_ctx = [t for t in tasks if "personal_context" in t.constraints]
            self.assertGreater(len(tasks_with_ctx), 0)
            for task in tasks_with_ctx:
                self.assertIn("PostgreSQL", task.constraints["personal_context"])

    def test_personal_context_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-personal-context-") as tmp:
            store = MemoryStore(Path(tmp) / "memory.sqlite3")
            store.add_document("notes", "Secret internal data.")
            kernel = ChimeraPilotKernel.default(
                include_deterministic_backend=True,
                memory_store=store,
                # enable_personal_context defaults to False
            )
            tasks = kernel.compile("What is my preferred stack?")
            self.assertTrue(len(tasks) > 0)
            # No personal_context should be present
            for task in tasks:
                self.assertNotIn("personal_context", task.constraints)


