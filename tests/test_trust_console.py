from __future__ import annotations

import json
import tempfile
import unittest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.console import register_console_routes


def _ctx(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "method": method,
        "path": path,
        "headers": {},
        "body": json.dumps(body or {}),
        "query": {},
    }


class TrustConsoleRouteTests(unittest.TestCase):
    def test_trust_routes_register_and_summary_is_secret_safe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-console-trust-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp, run_objective=lambda objective: {"ok": True, "echo": objective})

            for method, path in [
                ("GET", "/api/console/trust/summary"),
                ("GET", "/api/console/trust/runs"),
                ("GET", "/api/console/trust/approvals"),
                ("GET", "/api/console/trust/evals"),
                ("GET", "/api/console/trust/eval-cases"),
                ("GET", "/api/console/capability-admission"),
                ("GET", "/api/console/mcp/trust"),
                ("POST", "/api/console/trust/evals/baseline"),
                ("POST", "/api/console/trust/eval-cases/promote"),
                ("POST", "/api/console/capability-admission"),
            ]:
                self.assertIsNotNone(server.routes.find(method, path), f"{method} {path}")

            summary = server.routes.find("GET", "/api/console/trust/summary").handler(
                _ctx("GET", "/api/console/trust/summary")
            )
            self.assertTrue(summary["ok"])
            self.assertIn("journal", summary)
            self.assertNotIn("sk-test-secret", json.dumps(summary).lower())

    def test_console_run_creates_durable_journal_and_trace_export(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-console-run-trust-") as tmp:
            server = GatewayServer()
            register_console_routes(
                server,
                state_dir=tmp,
                run_objective=lambda objective: {"ok": True, "answer": f"done {objective}"},
            )

            run_route = server.routes.find("POST", "/api/console/run")
            result = run_route.handler(_ctx("POST", "/api/console/run", {"objective": "summarize status"}))
            self.assertTrue(result["ok"])
            self.assertIn("trust_run", result)

            runs = server.routes.find("GET", "/api/console/trust/runs").handler(_ctx("GET", "/api/console/trust/runs"))
            self.assertEqual(len(runs["runs"]), 1)
            run_id = runs["runs"][0]["run_id"]

            detail = server.routes.find("GET", f"/api/console/trust/runs/{run_id}").handler(
                _ctx("GET", f"/api/console/trust/runs/{run_id}")
            )
            self.assertTrue(detail["ok"])
            self.assertGreaterEqual(len(detail["steps"]), 2)

            trace = server.routes.find("GET", f"/api/console/trust/traces/{run_id}/export").handler(
                _ctx("GET", f"/api/console/trust/traces/{run_id}/export")
            )
            self.assertTrue(trace["ok"])
            self.assertEqual(trace["bundle"]["run_id"], run_id)
            self.assertIn("gen_ai.agent.name", trace["bundle"]["resource"])

    def test_remote_run_creates_approval_checkpoint_before_execution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-console-remote-trust-") as tmp:
            calls: list[str] = []
            server = GatewayServer()
            register_console_routes(
                server,
                state_dir=tmp,
                run_objective=lambda objective: calls.append(objective) or {"ok": True},
            )
            pair_route = server.routes.find("POST", "/api/console/remote/pairing/create")
            approve_pair_route = server.routes.find("POST", "/api/console/remote/pairing/approve")
            inbound_route = server.routes.find("POST", "/api/console/remote/inbound")

            pairing = pair_route.handler(
                _ctx(
                    "POST",
                    "/api/console/remote/pairing/create",
                    {"channel": "signal", "peer_id": "admin-phone", "display_name": "Admin"},
                )
            )
            approved = approve_pair_route.handler(
                _ctx(
                    "POST",
                    "/api/console/remote/pairing/approve",
                    {"pairing_id": pairing["pairing"]["id"], "code": pairing["pairing"]["pairing_code"]},
                )
            )
            self.assertTrue(approved["ok"])

            inbound = inbound_route.handler(
                _ctx(
                    "POST",
                    "/api/console/remote/inbound",
                    {"channel": "signal", "peer_id": "admin-phone", "text": "/run summarize readiness"},
                )
            )
            self.assertTrue(inbound["ok"])
            self.assertEqual(inbound["mode"], "approval_required")
            self.assertEqual(calls, [])
            self.assertIn("trust_run", inbound)
            self.assertIn("trust_approval", inbound)

            approvals = server.routes.find("GET", "/api/console/trust/approvals").handler(
                _ctx("GET", "/api/console/trust/approvals")
            )
            self.assertEqual(len(approvals["approvals"]), 1)

    def test_trust_approval_and_mcp_trust_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-console-actions-trust-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)

            run_route = server.routes.find("POST", "/api/console/remote/inbound")
            run_route.handler(
                _ctx(
                    "POST",
                    "/api/console/remote/inbound",
                    {"channel": "webhook", "peer_id": "new-admin", "text": "/run needs approval"},
                )
            )
            approvals = server.routes.find("GET", "/api/console/trust/approvals").handler(
                _ctx("GET", "/api/console/trust/approvals")
            )
            pending = approvals.get("approvals", [])
            if pending:
                approval_id = pending[0]["id"]
                resolved = server.routes.find("POST", f"/api/console/trust/approvals/{approval_id}/approve").handler(
                    _ctx("POST", f"/api/console/trust/approvals/{approval_id}/approve")
                )
                self.assertTrue(resolved["ok"])

            approved = server.routes.find("POST", "/api/console/mcp/trust/chimeralang/approve").handler(
                _ctx("POST", "/api/console/mcp/trust/chimeralang/approve", {"risk_ceiling": "medium", "tools": ["read"]})
            )
            self.assertTrue(approved["ok"])
            registry = server.routes.find("GET", "/api/console/mcp/trust").handler(_ctx("GET", "/api/console/mcp/trust"))
            self.assertEqual(registry["servers"][0]["server_id"], "chimeralang")
            self.assertEqual(registry["servers"][0]["status"], "approved")

            revoked = server.routes.find("POST", "/api/console/mcp/trust/chimeralang/revoke").handler(
                _ctx("POST", "/api/console/mcp/trust/chimeralang/revoke")
            )
            self.assertTrue(revoked["ok"])

    def test_trust_eval_case_promotion_route(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-console-eval-cases-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp, run_objective=lambda objective: {"ok": True})
            run_route = server.routes.find("POST", "/api/console/run")
            run_route.handler(_ctx("POST", "/api/console/run", {"objective": "build eval case"}))
            runs = server.routes.find("GET", "/api/console/trust/runs").handler(_ctx("GET", "/api/console/trust/runs"))
            run_id = runs["runs"][0]["run_id"]

            promoted = server.routes.find("POST", "/api/console/trust/eval-cases/promote").handler(
                _ctx("POST", "/api/console/trust/eval-cases/promote", {"run_id": run_id, "label": "console eval", "severity": "P1"})
            )
            cases = server.routes.find("GET", "/api/console/trust/eval-cases").handler(
                _ctx("GET", "/api/console/trust/eval-cases")
            )

            self.assertTrue(promoted["ok"])
            self.assertEqual(cases["count"], 1)
            self.assertEqual(cases["cases"][0]["label"], "console eval")

    def test_capability_admission_routes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-console-admission-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)

            created = server.routes.find("POST", "/api/console/capability-admission").handler(
                _ctx(
                    "POST",
                    "/api/console/capability-admission",
                    {
                        "capability_kind": "model",
                        "name": "openrouter/test-model",
                        "source": "openrouter",
                        "risk_level": "medium",
                        "requested_permissions": ["model.chat"],
                        "metadata": {"api_key": "sk-testsecret123456"},
                    },
                )
            )
            record_id = created["record"]["id"]
            inspected = server.routes.find("POST", f"/api/console/capability-admission/{record_id}/inspect").handler(
                _ctx("POST", f"/api/console/capability-admission/{record_id}/inspect")
            )
            approved = server.routes.find("POST", f"/api/console/capability-admission/{record_id}/approve").handler(
                _ctx("POST", f"/api/console/capability-admission/{record_id}/approve")
            )
            records = server.routes.find("GET", "/api/console/capability-admission").handler(
                _ctx("GET", "/api/console/capability-admission")
            )

            self.assertTrue(created["ok"])
            self.assertEqual(inspected["record"]["status"], "inspected")
            self.assertEqual(approved["record"]["status"], "approved")
            self.assertEqual(records["count"], 1)
            self.assertNotIn("sk-testsecret123456", json.dumps(records))


if __name__ == "__main__":
    unittest.main()
