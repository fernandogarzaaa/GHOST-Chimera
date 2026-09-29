"""Tests for the always-on Ghost Console routes."""

from __future__ import annotations

import json
import tempfile
import unittest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.console import register_console_routes


def _ctx(method: str, path: str, body: dict | None = None) -> dict:
    return {
        "method": method,
        "path": path,
        "headers": {},
        "body": json.dumps(body or {}),
        "query": {},
    }


def _call(server: GatewayServer, method: str, path: str, body: dict | None = None) -> dict:
    route = server.routes.find(method, path)
    assert route is not None, f"route missing: {method} {path}"
    return route.handler(_ctx(method, path, body))


class AlwaysOnConsoleRouteTests(unittest.TestCase):
    def _server(self, tmp: str) -> GatewayServer:
        server = GatewayServer()
        register_console_routes(server, state_dir=tmp)
        return server

    def test_agents_route_lists_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ao-") as tmp:
            server = self._server(tmp)
            result = _call(server, "GET", "/api/console/always-on/agents")
            self.assertTrue(result["ok"])
            self.assertEqual(result["agents"], [])
            # After a wake, the agent row appears with its lifecycle state.
            wake = _call(server, "POST", "/api/console/always-on/wake", {"objective": "say hi"})
            self.assertTrue(wake["ok"])
            agents = _call(server, "GET", "/api/console/always-on/agents")
            self.assertTrue(agents["ok"])
            self.assertEqual(len(agents["agents"]), 1)
            self.assertIn(agents["agents"][0]["lifecycle_state"], {"sleeping", "queued", "awake", "completed"})

    def test_wake_requires_objective(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ao-") as tmp:
            server = self._server(tmp)
            result = _call(server, "POST", "/api/console/always-on/wake", {"objective": "   "})
            self.assertFalse(result["ok"])
            self.assertIn("objective", result["error"].lower())

    def test_webhook_register_trigger_delete(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ao-") as tmp:
            server = self._server(tmp)
            registered = _call(
                server,
                "POST",
                "/api/console/always-on/webhooks",
                {"name": "ci-done", "objective_template": "verify build {build}", "description": "CI"},
            )
            self.assertTrue(registered["ok"])
            self.assertEqual(registered["webhook"]["name"], "ci-done")

            listed = _call(server, "GET", "/api/console/always-on/webhooks")
            self.assertTrue(listed["ok"])
            self.assertEqual(len(listed["webhooks"]), 1)
            self.assertTrue(listed["webhooks"][0]["has_handler"])

            triggered = _call(
                server,
                "POST",
                "/api/console/always-on/webhooks/ci-done/trigger",
                {"payload": {"build": "42"}},
            )
            self.assertTrue(triggered["ok"])
            self.assertEqual(triggered["wake"]["objective"], "verify build 42")

            deleted = _call(server, "POST", "/api/console/always-on/webhooks/ci-done/delete", {})
            self.assertTrue(deleted["ok"])
            self.assertEqual(_call(server, "GET", "/api/console/always-on/webhooks")["webhooks"], [])

    def test_webhook_register_requires_template(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ao-") as tmp:
            server = self._server(tmp)
            result = _call(server, "POST", "/api/console/always-on/webhooks", {"name": "x"})
            self.assertFalse(result["ok"])

    def test_trigger_unknown_webhook_errors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ao-") as tmp:
            server = self._server(tmp)
            result = _call(server, "POST", "/api/console/always-on/webhooks/nope/trigger", {})
            self.assertFalse(result["ok"])

    def test_schedule_create_list_action(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ao-") as tmp:
            server = self._server(tmp)
            created = _call(
                server,
                "POST",
                "/api/console/always-on/schedules",
                {"name": "nightly", "cron_expression": "0 3 * * *", "objective": "nightly check"},
            )
            self.assertTrue(created["ok"])
            schedule_id = created["schedule"]["id"]

            listed = _call(server, "GET", "/api/console/always-on/schedules")
            self.assertTrue(listed["ok"])
            self.assertEqual(len(listed["schedules"]), 1)

            disabled = _call(server, "POST", f"/api/console/always-on/schedules/{schedule_id}/disable", {})
            self.assertTrue(disabled["ok"])
            self.assertFalse(disabled["schedule"]["enabled"])

            enabled = _call(server, "POST", f"/api/console/always-on/schedules/{schedule_id}/enable", {})
            self.assertTrue(enabled["ok"])
            self.assertTrue(enabled["schedule"]["enabled"])

            run_now = _call(server, "POST", f"/api/console/always-on/schedules/{schedule_id}/run-now", {})
            self.assertTrue(run_now["ok"])
            self.assertEqual(run_now["wake"]["objective"], "nightly check")

            deleted = _call(server, "POST", f"/api/console/always-on/schedules/{schedule_id}/delete", {})
            self.assertTrue(deleted["ok"])
            self.assertEqual(_call(server, "GET", "/api/console/always-on/schedules")["schedules"], [])

    def test_schedule_create_rejects_bad_cron(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ao-") as tmp:
            server = self._server(tmp)
            result = _call(
                server,
                "POST",
                "/api/console/always-on/schedules",
                {"name": "bad", "cron_expression": "not a cron", "objective": "x"},
            )
            self.assertFalse(result["ok"])
            self.assertIn("cron", result["error"].lower())

    def test_approval_list_and_decide(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ao-") as tmp:
            from ghostchimera.chimera_pilot.always_on.approvals import ApprovalStore

            store = ApprovalStore(tmp)
            ticket = store.create("shell", {"command": "ls"}, requester="agent-1")

            server = self._server(tmp)
            listed = _call(server, "GET", "/api/console/always-on/approvals")
            self.assertTrue(listed["ok"])
            self.assertEqual(len(listed["pending"]), 1)

            decided = _call(
                server,
                "POST",
                f"/api/console/always-on/approvals/{ticket.ticket_id}/approve",
                {"decided_by": "test-operator"},
            )
            self.assertTrue(decided["ok"])
            self.assertEqual(decided["ticket"]["status"], "approved")
            self.assertEqual(_call(server, "GET", "/api/console/always-on/approvals")["pending"], [])

            # Deciding twice is an error, not a silent no-op.
            again = _call(server, "POST", f"/api/console/always-on/approvals/{ticket.ticket_id}/deny", {})
            self.assertFalse(again["ok"])

    def test_approval_unknown_action_errors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ao-") as tmp:
            server = self._server(tmp)
            result = _call(server, "POST", "/api/console/always-on/approvals/approval-x/maybe", {})
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
