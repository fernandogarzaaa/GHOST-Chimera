"""Tests for managed debuggable Chrome and its console routes."""

from __future__ import annotations

import json
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.browser_debug import (
    ChromeDebugManager,
    find_chrome,
)
from ghostchimera.control_plane.console import register_console_routes


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class FakeJsonListServer:
    def __init__(self) -> None:
        self.port = _free_port()

        class ListHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server signature
                body = json.dumps([{"type": "page", "webSocketDebuggerUrl": "ws://x/1"}]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                del args

        self.httpd = HTTPServer(("127.0.0.1", self.port), ListHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()


class FindChromeTests(unittest.TestCase):
    def test_env_override_wins(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "chrome"
            binary.write_bytes(b"x")
            with mock.patch.dict("os.environ", {"GHOSTCHIMERA_CHROME_BINARY": str(binary)}):
                self.assertEqual(find_chrome(), str(binary))

    def test_env_override_missing_returns_none(self) -> None:
        with mock.patch.dict("os.environ", {"GHOSTCHIMERA_CHROME_BINARY": "/no/such/chrome"}):
            self.assertIsNone(find_chrome())

    def test_well_known_miss_returns_none(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=False),
            mock.patch("shutil.which", return_value=None),
            mock.patch("pathlib.Path.is_file", return_value=False),
        ):
            self.assertIsNone(find_chrome())


class ChromeDebugManagerTests(unittest.TestCase):
    def test_port_validation(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manager = ChromeDebugManager(tmp)
            self.assertEqual(manager._check_port(9222), 9222)
            self.assertEqual(manager._check_port("9333"), 9333)
            for bad in (0, 70000, "nope", None, True):
                with self.assertRaises(ValueError):
                    manager._check_port(bad)

    def test_status_shape(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            status = ChromeDebugManager(tmp).status()
            self.assertIn("installed", status)
            self.assertIn("managed_running", status)
            self.assertIn("debug_port", status)
            self.assertFalse(status["managed_running"])
            self.assertTrue(Path(status["profile_dir"]).is_dir())

    def test_launch_uses_already_open_endpoint(self) -> None:
        import tempfile

        server = FakeJsonListServer()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                manager = ChromeDebugManager(tmp)
                result = manager.launch(port=server.port, timeout=5.0)
                self.assertTrue(result["ok"])
                self.assertTrue(result["already_running"])
                self.assertIsNone(manager._process)
                self.assertTrue(manager.debug_open(server.port))
        finally:
            server.close()

    def test_launch_fails_fast_when_binary_exits(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manager = ChromeDebugManager(tmp)
            with (
                mock.patch.dict("os.environ", {"GHOSTCHIMERA_CHROME_BINARY": sys.executable}),
                self.assertRaises(RuntimeError),
            ):
                manager.launch(port=_free_port(), timeout=3.0)
            self.assertFalse(manager.is_managed_running())

    def test_stop_without_launch_is_noop(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = ChromeDebugManager(tmp).stop()
            self.assertEqual(result, {"ok": True, "was_running": False})

    def test_websocket_url_raises_when_closed(self) -> None:
        import tempfile

        from ghostchimera.stealth.cdp import CdpError

        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(CdpError):
            ChromeDebugManager(tmp).debug_websocket_url(port=_free_port())


class FakeDebugManager:
    def __init__(self) -> None:
        self.calls: list = []
        self.default_port = 9222

    def status(self) -> dict:
        self.calls.append(("status",))
        return {"installed": True, "managed_running": True, "debug_open": True}

    def launch(self, port=None, *, headless=True, timeout=30.0) -> dict:
        self.calls.append(("launch", port, headless))
        return {"ok": True, "already_running": False, "port": port or 9222, "pid": 4242}

    def stop(self) -> dict:
        self.calls.append(("stop",))
        return {"ok": True, "was_running": True}


def _ctx(method: str, path: str, body: object = "") -> dict:
    import json as _json

    return {
        "method": method,
        "path": path,
        "headers": {},
        "body": _json.dumps(body) if not isinstance(body, str) else body,
        "query": {},
    }


class BrowserDebugRouteTests(unittest.TestCase):
    def _server(self, tmp: str, manager=None):
        server = GatewayServer()
        if manager is None:
            register_console_routes(server, state_dir=tmp)
        else:
            register_console_routes(server, state_dir=tmp, browser_debug=manager)
        return server

    def test_routes_registered(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ghost-browser-debug-") as tmp:
            server = self._server(tmp)
            for method, path in [
                ("GET", "/api/console/browser/debug"),
                ("POST", "/api/console/browser/debug/launch"),
                ("POST", "/api/console/browser/debug/stop"),
            ]:
                self.assertIsNotNone(server.routes.find(method, path))

    def test_status_launch_stop_flow(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ghost-browser-debug-") as tmp:
            manager = FakeDebugManager()
            server = self._server(tmp, manager)

            status = server.routes.find("GET", "/api/console/browser/debug").handler(
                _ctx("GET", "/api/console/browser/debug")
            )
            self.assertTrue(status["ok"])
            self.assertTrue(status["managed_running"])

            launch = server.routes.find("POST", "/api/console/browser/debug/launch").handler(
                _ctx("POST", "/api/console/browser/debug/launch", {"port": 9333, "headless": False})
            )
            self.assertTrue(launch["ok"])
            self.assertEqual(launch["port"], 9333)
            self.assertIn(("launch", 9333, False), manager.calls)

            stop = server.routes.find("POST", "/api/console/browser/debug/stop").handler(
                _ctx("POST", "/api/console/browser/debug/stop")
            )
            self.assertTrue(stop["ok"])
            self.assertTrue(stop["was_running"])

    def test_launch_reports_manager_errors(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ghost-browser-debug-") as tmp:
            manager = FakeDebugManager()
            with mock.patch.object(manager, "launch", side_effect=RuntimeError("no chrome")):
                server = self._server(tmp, manager)
                payload = server.routes.find("POST", "/api/console/browser/debug/launch").handler(
                    _ctx("POST", "/api/console/browser/debug/launch")
                )
            self.assertFalse(payload["ok"])
            self.assertIn("no chrome", payload["error"])

    def test_default_manager_status_route(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ghost-browser-debug-") as tmp:
            server = self._server(tmp)
            payload = server.routes.find("GET", "/api/console/browser/debug").handler(
                _ctx("GET", "/api/console/browser/debug")
            )
            self.assertTrue(payload["ok"])
            self.assertIn("installed", payload)


if __name__ == "__main__":
    unittest.main()
