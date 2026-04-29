from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.agent_core.core import AgentCore
from ghostchimera.agent_core.memory import MemoryManager
from ghostchimera.chimera_pilot import ChimeraPilotKernel
from ghostchimera.memory_layer.store import MemoryStore
from ghostchimera.safety_layer.gating import ExecutionPolicy


class AgentCorePilotIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="ghostchimera-agent-pilot-test-")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_retrieve_request_uses_chimera_pilot_cwr_backend(self) -> None:
        store = MemoryStore(self.root / "memory.sqlite3")
        store.add_document("goals", "Ghost Chimera should route retrieval through Chimera Pilot.")
        kernel = ChimeraPilotKernel.default(memory_store=store)
        agent = AgentCore(
            memory_manager=MemoryManager(str(self.root / "agent-memory.json")),
            pilot_kernel=kernel,
        )

        result = agent.handle_request("retrieve retrieval through chimera pilot")

        self.assertIn("cwr.local", result)
        self.assertIn("goals", result)
        self.assertIn("Ghost Chimera should route retrieval", result)

    def test_unsupported_legacy_shell_request_still_uses_policy_gate(self) -> None:
        agent = AgentCore(
            memory_manager=MemoryManager(str(self.root / "agent-memory.json")),
            execution_policy=ExecutionPolicy(),
        )

        result = agent.handle_request("run command python --version")

        self.assertIn("Policy denied shell", result)


if __name__ == "__main__":
    unittest.main()
