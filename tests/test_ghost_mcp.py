from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ghostchimera.mcp.ghost_adapter import GhostMCPAdapter
from ghostchimera.mcp.runtime import create_ghost_mcp
from ghostchimera.sdk import GhostClient


class GhostMCPAdapterTests(unittest.TestCase):
    def _adapter(self, tmp: str) -> GhostMCPAdapter:
        client = GhostClient(state_dir=tmp, config_path=Path(tmp) / "config.json", enable_personal_context=False)
        return GhostMCPAdapter(state_dir=tmp, config_path=Path(tmp) / "config.json", client=client)

    def test_status_returns_normalized_envelope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-mcp-") as tmp, patch.dict(
            "os.environ",
            {"HOME": tmp, "GHOSTCHIMERA_STATE_DIR": tmp},
            clear=False,
        ):
            result = self._adapter(tmp).invoke({"action": "status"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "status")
        self.assertIn("summary", result)
        self.assertIn("trust_state", result)
        self.assertIn("providers", result["output"])

    def test_memory_action_can_ingest_and_search(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-mcp-") as tmp, patch.dict(
            "os.environ",
            {"HOME": tmp, "GHOSTCHIMERA_STATE_DIR": tmp},
            clear=False,
        ):
            adapter = self._adapter(tmp)
            ingested = adapter.invoke(
                {
                    "action": "memory",
                    "mode": "ingest_document",
                    "source": "notes",
                    "text": "Ghost MCP should compress execution and memory into one tool.",
                }
            )
            result = adapter.invoke({"action": "memory", "mode": "search", "query": "compress execution"})
        self.assertTrue(ingested["ok"])
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result["output"]), 1)

    def test_run_action_uses_ghost_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-mcp-") as tmp, patch.dict(
            "os.environ",
            {"HOME": tmp, "GHOSTCHIMERA_STATE_DIR": tmp},
            clear=False,
        ):
            adapter = self._adapter(tmp)
            adapter.invoke(
                {
                    "action": "memory",
                    "mode": "ingest_document",
                    "source": "notes",
                    "text": "The migration should keep one external tool called ghost.",
                }
            )
            result = adapter.invoke({"action": "run", "objective": "retrieve notes"})
        self.assertEqual(result["action"], "run")
        self.assertTrue(result["ok"])
        self.assertIn("run", result["details"])

    def test_teach_and_train_local_action(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-mcp-") as tmp, patch.dict(
            "os.environ",
            {"HOME": tmp, "GHOSTCHIMERA_STATE_DIR": tmp},
            clear=False,
        ):
            adapter = self._adapter(tmp)
            taught = adapter.invoke(
                {
                    "action": "teach",
                    "records": [
                        {"prompt": "What is Ghost MCP?", "response": "A compressed Ghost Chimera capability runtime."}
                    ],
                }
            )
            trained = adapter.invoke({"action": "train", "mode": "local"})
        self.assertTrue(taught["ok"])
        self.assertTrue(trained["ok"])
        self.assertEqual(trained["output"]["mode"], "local")


class GhostMCPRuntimeTests(unittest.TestCase):
    def test_runtime_exposes_single_ghost_tool(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-mcp-") as tmp, patch.dict(
            "os.environ",
            {"HOME": tmp, "GHOSTCHIMERA_STATE_DIR": tmp},
            clear=False,
        ):
            server = create_ghost_mcp(state_dir=tmp, config_path=Path(tmp) / "config.json")
            tools = asyncio.run(server.list_tools())
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "ghost")

    def test_runtime_ghost_tool_returns_json_envelope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-mcp-") as tmp, patch.dict(
            "os.environ",
            {"HOME": tmp, "GHOSTCHIMERA_STATE_DIR": tmp},
            clear=False,
        ):
            server = create_ghost_mcp(state_dir=tmp, config_path=Path(tmp) / "config.json")
            content = asyncio.run(server.call_tool("ghost", {"action": "status"}))
        self.assertEqual(len(content), 1)
        payload = json.loads(content[0].text)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "status")
