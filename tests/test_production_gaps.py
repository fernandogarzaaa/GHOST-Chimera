from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.cli import _main
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.production_gaps import scan_production_gaps


class ProductionGapTests(unittest.TestCase):
    def test_scanner_flags_action_required_runtime_placeholders_without_leaking_secrets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-gap-scan-") as tmp:
            root = Path(tmp)
            runtime = root / "ghostchimera"
            docs = root / "docs"
            runtime.mkdir()
            docs.mkdir()
            (runtime / "live.py").write_text(
                "API_KEY = 'sk-secret-should-not-leak'\n"
                "def run():\n"
                "    raise NotImplementedError('real runtime missing')\n",
                encoding="utf-8",
            )
            (docs / "notes.md").write_text("TODO: document this later\n", encoding="utf-8")

            payload = scan_production_gaps(root)

            self.assertFalse(payload["ok"])
            self.assertGreaterEqual(payload["counts"]["action_required"], 1)
            self.assertGreaterEqual(payload["counts"]["non_blocking"], 1)
            self.assertIn("live.py", json.dumps(payload))
            self.assertNotIn("sk-secret-should-not-leak", json.dumps(payload))

    def test_console_exposes_production_gap_scan_route(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-gap-console-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)
            route = server.routes.find("GET", "/api/console/production/gaps")

            self.assertIsNotNone(route)
            payload = route.handler(
                {
                    "method": "GET",
                    "path": "/api/console/production/gaps",
                    "headers": {},
                    "body": "",
                    "query": {},
                }
            )

            self.assertTrue(payload["ok"] in {True, False})
            self.assertIn("counts", payload)
            self.assertIn("gaps", payload)

    def test_cli_production_gaps_command_runs(self) -> None:
        result = _main(["production-gaps", "--limit", "5"])

        self.assertIn(result, {0, 1})


if __name__ == "__main__":
    unittest.main()
