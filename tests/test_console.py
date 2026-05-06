"""Tests for the browser-based Ghost Console control surface."""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from ghostchimera.chimera_pilot.gateway_server import GatewayServer, HttpResponse
from ghostchimera.control_plane.cli import _main
from ghostchimera.control_plane.console import register_console_routes, run_console


class FakeBrowserWorkspace:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def status(self) -> dict[str, object]:
        return {"available": True, "binary": "agent-browser", "detail": "ready"}

    def open(self, url: str, *, session: str = "default") -> dict[str, object]:
        self.calls.append(("open", {"url": url, "session": session}))
        return {"ok": True, "action": "open", "url": url, "session": session}

    def snapshot(self, *, url: str = "", session: str = "default", interactive: bool = True) -> dict[str, object]:
        self.calls.append(("snapshot", {"url": url, "session": session}))
        return {"ok": True, "action": "snapshot", "output": "@e1 [heading] Example", "session": session}


class ConsoleRouteTests(unittest.TestCase):
    def test_console_registers_browser_ui_and_status_routes(self) -> None:
        server = GatewayServer()
        register_console_routes(server)

        root = server.routes.find("GET", "/")
        status = server.routes.find("GET", "/api/console/status")

        self.assertIsNotNone(root)
        self.assertIsNotNone(status)
        self.assertEqual(root.auth, "open")
        self.assertEqual(status.auth, "open")

        root_response = root.handler({"method": "GET", "path": "/", "headers": {}, "body": "", "query": {}})
        self.assertIsInstance(root_response, HttpResponse)
        self.assertEqual(root_response.content_type, "text/html; charset=utf-8")
        self.assertIn("Ghost Console", root_response.body)

        status_payload = status.handler({"method": "GET", "path": "/api/console/status", "headers": {}, "body": "", "query": {}})
        self.assertTrue(status_payload["ok"])
        self.assertIn("gateway", status_payload)
        self.assertIn("autonomy", status_payload)
        self.assertIn("profiles", status_payload)

    def test_console_browser_route_exposes_existing_https_fetch_tool(self) -> None:
        calls: list[str] = []

        def fetcher(url: str) -> str:
            calls.append(url)
            return "<title>Example</title>"

        server = GatewayServer()
        register_console_routes(server, fetch_url=fetcher)
        route = server.routes.find("POST", "/api/console/browser/fetch")
        self.assertIsNotNone(route)

        missing = route.handler({"method": "POST", "path": "/api/console/browser/fetch", "headers": {}, "body": "{}", "query": {}})
        self.assertFalse(missing["ok"])
        self.assertIn("url", missing["error"])

        result = route.handler(
            {
                "method": "POST",
                "path": "/api/console/browser/fetch",
                "headers": {},
                "body": json.dumps({"url": "https://example.com"}),
                "query": {},
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], "<title>Example</title>")
        self.assertEqual(calls, ["https://example.com"])

    def test_console_registers_browser_workspace_routes(self) -> None:
        workspace = FakeBrowserWorkspace()
        server = GatewayServer()
        register_console_routes(server, browser_workspace=workspace)

        status_route = server.routes.find("GET", "/api/console/browser/status")
        open_route = server.routes.find("POST", "/api/console/browser/open")
        snapshot_route = server.routes.find("POST", "/api/console/browser/snapshot")

        self.assertIsNotNone(status_route)
        self.assertIsNotNone(open_route)
        self.assertIsNotNone(snapshot_route)
        self.assertTrue(status_route.handler({"method": "GET", "path": "/api/console/browser/status", "headers": {}, "body": "", "query": {}})["available"])

        opened = open_route.handler(
            {
                "method": "POST",
                "path": "/api/console/browser/open",
                "headers": {},
                "body": json.dumps({"url": "https://example.com", "session": "demo"}),
                "query": {},
            }
        )
        self.assertTrue(opened["ok"])

        snapshot = snapshot_route.handler(
            {
                "method": "POST",
                "path": "/api/console/browser/snapshot",
                "headers": {},
                "body": json.dumps({"url": "https://example.com", "session": "demo"}),
                "query": {},
            }
        )
        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["output"], "@e1 [heading] Example")
        self.assertEqual(workspace.calls[0][0], "open")
        self.assertEqual(workspace.calls[1][0], "snapshot")

    def test_console_run_route_validates_objective_and_delegates_to_runner(self) -> None:
        calls: list[str] = []

        def runner(objective: str) -> dict[str, object]:
            calls.append(objective)
            return {"ok": True, "executions": [{"objective": objective, "ok": True}]}

        server = GatewayServer()
        register_console_routes(server, run_objective=runner)
        route = server.routes.find("POST", "/api/console/run")
        self.assertIsNotNone(route)

        missing = route.handler({"method": "POST", "path": "/api/console/run", "headers": {}, "body": "{}", "query": {}})
        self.assertFalse(missing["ok"])
        self.assertIn("objective", missing["error"])
        self.assertEqual(calls, [])

        result = route.handler(
            {
                "method": "POST",
                "path": "/api/console/run",
                "headers": {},
                "body": json.dumps({"objective": "summarize runtime status"}),
                "query": {},
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["summarize runtime status"])
        self.assertEqual(result["executions"][0]["objective"], "summarize runtime status")

    def test_console_registers_autonomy_job_routes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)

            list_route = server.routes.find("GET", "/api/console/autonomy/jobs")
            create_route = server.routes.find("POST", "/api/console/autonomy/jobs")
            detail_route = server.routes.find("GET", "/api/console/autonomy/jobs/job-missing")
            cancel_route = server.routes.find("POST", "/api/console/autonomy/jobs/job-missing/cancel")

            self.assertIsNotNone(list_route)
            self.assertIsNotNone(create_route)
            self.assertIsNotNone(detail_route)
            self.assertIsNotNone(cancel_route)

            listed = list_route.handler({"method": "GET", "path": "/api/console/autonomy/jobs", "headers": {}, "body": "", "query": {}})
            self.assertIn("available_jobs", listed)
            self.assertEqual(listed["history"], [])

            created = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/autonomy/jobs",
                    "headers": {},
                    "body": json.dumps({"job": "repair-preview", "profile": "supervised", "execute": False}),
                    "query": {},
                }
            )
            self.assertTrue(created["ok"])
            self.assertEqual(created["job"]["status"], "preview")

            rejected = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/autonomy/jobs",
                    "headers": {},
                    "body": json.dumps({"job": "test-regression", "profile": "supervised", "execute": True}),
                    "query": {},
                }
            )
            self.assertFalse(rejected["ok"])
            self.assertEqual(rejected["type"], "policy")

    def test_console_registers_schedule_routes_that_use_autonomy_jobs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)

            list_route = server.routes.find("GET", "/api/console/autonomy/schedules")
            create_route = server.routes.find("POST", "/api/console/autonomy/schedules")

            self.assertIsNotNone(list_route)
            self.assertIsNotNone(create_route)

            created = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/autonomy/schedules",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "name": "daily audit",
                            "cron_expression": "0 9 * * *",
                            "job": "self-audit",
                            "profile": "autonomous",
                            "enabled": False,
                        }
                    ),
                    "query": {},
                }
            )
            self.assertTrue(created["ok"])
            schedule_id = created["schedule"]["id"]

            run_now = server.routes.find("POST", f"/api/console/autonomy/schedules/{schedule_id}/run-now")
            self.assertIsNotNone(run_now)
            result = run_now.handler(
                {
                    "method": "POST",
                    "path": f"/api/console/autonomy/schedules/{schedule_id}/run-now",
                    "headers": {},
                    "body": "",
                    "query": {},
                }
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["job"]["name"], "self-audit")

            disabled = list_route.handler({"method": "GET", "path": "/api/console/autonomy/schedules", "headers": {}, "body": "", "query": {}})
            self.assertEqual(disabled["schedules"][0]["enabled"], False)

    def test_console_readiness_route_returns_release_runbook(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("GET", "/api/console/readiness")

        self.assertIsNotNone(route)
        payload = route.handler({"method": "GET", "path": "/api/console/readiness", "headers": {}, "body": "", "query": {}})

        commands = [check["command"] for check in payload["checks"]]
        self.assertIn("python scripts/validate_release.py", commands)
        self.assertIn("python -m ghostchimera.evals run --suite safety", commands)


class ConsoleCliTests(unittest.TestCase):
    def test_run_console_registers_routes_without_blocking(self) -> None:
        server = run_console(host="127.0.0.1", port=0, http_port=0, open_browser=False, block=False)
        try:
            self.assertIsNotNone(server.routes.find("GET", "/"))
            self.assertIsNotNone(server.routes.find("GET", "/api/console/status"))
        finally:
            server.stop()

    def test_cli_console_dispatches_to_run_console(self) -> None:
        with patch("ghostchimera.control_plane.console.run_console") as mocked:
            mocked.return_value = object()
            result = _main(
                [
                    "console",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "9001",
                    "--http-port",
                    "9002",
                    "--state-dir",
                    "C:/tmp/ghost-state",
                    "--no-open",
                ]
            )

        self.assertEqual(result, 0)
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 9001)
        self.assertEqual(kwargs["http_port"], 9002)
        self.assertEqual(kwargs["state_dir"], "C:/tmp/ghost-state")
        self.assertFalse(kwargs["open_browser"])
        self.assertTrue(kwargs["block"])


if __name__ == "__main__":
    unittest.main()
