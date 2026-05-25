from __future__ import annotations

import json
import tempfile
import unittest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.control_plane.standing_orders import StandingOrderStore


class StandingOrderStoreTests(unittest.TestCase):
    def test_create_enable_and_run_standing_order_with_real_runner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-standing-orders-") as tmp:
            calls: list[str] = []
            store = StandingOrderStore(tmp)
            created = store.create_order(
                {
                    "title": "Daily repo health",
                    "scope": "engineering",
                    "objective": "Inspect repository health and summarize blockers.",
                    "allowed_actions": ["read repo", "run tests"],
                    "approval_gates": ["source edits require approval"],
                    "delivery_channel": "remote",
                    "delivery_target": "admin-chat",
                }
            )
            order_id = created["order"]["id"]
            disabled = store.run_order(order_id, objective_runner=lambda objective: calls.append(objective) or {"ok": True})
            enabled = store.enable_order(order_id)
            run = store.run_order(order_id, objective_runner=lambda objective: calls.append(objective) or {"ok": True})
            listed = store.list_orders()

            self.assertFalse(disabled["ok"])
            self.assertIn("disabled", disabled["error"])
            self.assertTrue(enabled["ok"])
            self.assertTrue(run["ok"])
            self.assertEqual(run["order"]["run_count"], 1)
            self.assertIn("Standing order: Daily repo health", calls[0])
            self.assertIn("Approval gates", calls[0])
            self.assertEqual(listed["counts"]["enabled"], 1)
            self.assertNotIn("admin-chat", json.dumps(run["result"]).lower())

    def test_console_exposes_standing_order_routes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-standing-console-") as tmp:
            calls: list[str] = []
            server = GatewayServer()
            register_console_routes(
                server,
                state_dir=tmp,
                run_objective=lambda objective: calls.append(objective) or {"ok": True, "objective": objective},
            )
            list_route = server.routes.find("GET", "/api/console/standing-orders")
            create_route = server.routes.find("POST", "/api/console/standing-orders")
            action_route = server.routes.find("POST", "/api/console/standing-orders/example/run")

            self.assertIsNotNone(list_route)
            self.assertIsNotNone(create_route)
            self.assertIsNotNone(action_route)

            created = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/standing-orders",
                    "headers": {},
                    "body": json.dumps({"title": "Readiness", "scope": "ops", "objective": "Check readiness."}),
                    "query": {},
                }
            )
            self.assertTrue(created["ok"])
            order_id = created["order"]["id"]
            enable_route = server.routes.find("POST", f"/api/console/standing-orders/{order_id}/enable")
            run_route = server.routes.find("POST", f"/api/console/standing-orders/{order_id}/run")
            self.assertIsNotNone(enable_route)
            self.assertIsNotNone(run_route)

            enabled = enable_route.handler(
                {
                    "method": "POST",
                    "path": f"/api/console/standing-orders/{order_id}/enable",
                    "headers": {},
                    "body": "",
                    "query": {},
                }
            )
            run = run_route.handler(
                {
                    "method": "POST",
                    "path": f"/api/console/standing-orders/{order_id}/run",
                    "headers": {},
                    "body": "",
                    "query": {},
                }
            )

            self.assertTrue(enabled["ok"])
            self.assertTrue(run["ok"])
            self.assertEqual(calls, ["Standing order: Readiness\nScope: ops\nObjective: Check readiness."])


if __name__ == "__main__":
    unittest.main()
