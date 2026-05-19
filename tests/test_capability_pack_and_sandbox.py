from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ghostchimera.capability_pack import call_capability_tool, list_capability_tools
from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.sandbox.journey import run_sandbox_journey

ROOT = Path(__file__).resolve().parents[1]


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ghostchimera", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


class CapabilityPackTests(unittest.TestCase):
    def test_builtin_capability_pack_is_available_without_external_mcp(self) -> None:
        tools = list_capability_tools()
        ids = {tool.id for tool in tools}

        self.assertIn("ghost.guard", ids)
        self.assertIn("ghost.compress", ids)
        self.assertIn("ghost.local_model_inventory", ids)
        self.assertTrue(all(tool.external_dependency_required is False for tool in tools))

    def test_capability_pack_guard_and_compress_tools_execute(self) -> None:
        guarded = call_capability_tool("ghost.guard", {"confidence": 0.92, "variance": 0.01})
        compressed = call_capability_tool(
            "ghost.compress",
            {"text": "latency latency latency matters\n\nlatency matters", "focus": "latency", "budget_tokens": 20},
        )

        self.assertTrue(guarded["ok"])
        self.assertTrue(guarded["result"]["passed"])
        self.assertTrue(compressed["ok"])
        self.assertLessEqual(compressed["result"]["compressed_tokens"], compressed["result"]["original_tokens"])

    def test_capability_pack_cli_lists_tools(self) -> None:
        result = _run_cli(["capability-pack", "list"])
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("ghost.guard", {tool["id"] for tool in payload["tools"]})


class SandboxJourneyTests(unittest.TestCase):
    def test_sandbox_journey_preserves_findings_and_step_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-sandbox-") as tmp:
            report = run_sandbox_journey(state_dir=tmp, include_console=False)

        self.assertTrue(report.ok)
        self.assertGreaterEqual(len(report.steps), 3)
        self.assertIn("summary", report.to_dict())
        self.assertIn("findings", report.to_dict())
        self.assertTrue(all("status" in step for step in report.to_dict()["steps"]))

    def test_sandbox_cli_outputs_json_report(self) -> None:
        result = _run_cli(["sandbox", "journey"])
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("steps", payload)


class ConsoleNativeAbsorptionRouteTests(unittest.TestCase):
    def test_console_registers_native_absorption_routes(self) -> None:
        server = GatewayServer()
        register_console_routes(server)

        for method, path in [
            ("GET", "/api/console/capability-pack"),
            ("POST", "/api/console/capability-pack/run"),
            ("GET", "/api/console/local-models/inventory"),
            ("POST", "/api/console/local-models/resolve"),
            ("GET", "/api/console/cognition/trace"),
            ("POST", "/api/console/cognition/guard"),
            ("GET", "/api/console/sandbox/journey"),
        ]:
            with self.subTest(path=path):
                self.assertIsNotNone(server.routes.find(method, path))

    def test_console_capability_route_never_exposes_secrets(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("POST", "/api/console/capability-pack/run")
        payload = route.handler(
            {
                "method": "POST",
                "path": "/api/console/capability-pack/run",
                "headers": {},
                "body": json.dumps(
                    {
                        "tool_id": "ghost.normalize_mcp",
                        "arguments": {
                            "server_id": "secret-server",
                            "details": {"command": "python", "api_key": "raw-secret-token"},
                        },
                    }
                ),
                "query": {},
            }
        )

        self.assertTrue(payload["ok"])
        self.assertNotIn("raw-secret-token", json.dumps(payload))

