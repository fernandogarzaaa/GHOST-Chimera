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

