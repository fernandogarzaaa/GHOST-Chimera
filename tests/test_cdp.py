"""Tests for the minimal CDP client, using a local fake DevTools endpoint."""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from ghostchimera.stealth.cdp import (
    CdpClient,
    CdpError,
    chrome_remote_debugging_command,
    list_targets,
    page_websocket_url,
    probe,
)

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _FakeCdpHandler:
    def __init__(self, websocket):
        self.websocket = websocket

    async def handle(self) -> None:
        async for raw in self.websocket:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            call_id = message.get("id")
            method = message.get("method", "")
            if method == "Page.navigate":
                await self.websocket.send(json.dumps({"id": call_id, "result": {"loaderId": "1"}}))
                await self.websocket.send(json.dumps({"method": "Page.loadEventFired", "params": {}}))
            elif method == "Page.captureScreenshot":
                await self.websocket.send(
                    json.dumps({"id": call_id, "result": {"data": base64.b64encode(PNG_1X1).decode()}})
                )
            elif method == "Runtime.evaluate":
                expression = str((message.get("params") or {}).get("expression", ""))
                if "document.title" in expression:
                    value = {"title": "Example", "url": "https://example.test", "text": "hello"}
                elif "querySelector" in expression:
                    value = True
                else:
                    value = None
                await self.websocket.send(
                    json.dumps({"id": call_id, "result": {"result": {"type": "object", "value": value}}})
                )
            elif method in ("Page.enable", "DOM.enable", "Runtime.enable"):
                await self.websocket.send(json.dumps({"id": call_id, "result": {}}))
            else:
                await self.websocket.send(
                    json.dumps({"id": call_id, "error": {"code": -32601, "message": "not found"}})
                )


class CdpClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import websockets

        cls.ws_port = _free_port()
        cls.http_port = _free_port()

        async def amain() -> None:
            async def handler(websocket, *args):
                await _FakeCdpHandler(websocket).handle()

            async with websockets.serve(handler, "127.0.0.1", cls.ws_port):
                await asyncio.Future()

        cls.ws_thread = threading.Thread(target=lambda: asyncio.run(amain()), name="ghost-test-cdp-ws", daemon=True)
        cls.ws_thread.start()

        cls.ws_url = f"ws://127.0.0.1:{cls.ws_port}/devtools/page/1"

        class ListHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server signature
                body = json.dumps([{"type": "page", "webSocketDebuggerUrl": cls.ws_url}]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.httpd = HTTPServer(("127.0.0.1", cls.http_port), ListHandler)
        cls.http_thread = threading.Thread(target=cls.httpd.serve_forever, name="ghost-test-cdp-http", daemon=True)
        cls.http_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()

    def test_probe_and_target_discovery(self) -> None:
        self.assertTrue(probe("127.0.0.1", self.http_port))
        self.assertFalse(probe("127.0.0.1", _free_port(), timeout=0.5))
        targets = list_targets("127.0.0.1", self.http_port)
        self.assertEqual(len(targets), 1)
        self.assertEqual(page_websocket_url("127.0.0.1", self.http_port), self.ws_url)

    def test_navigate_describe_click_type_screenshot(self) -> None:
        client = CdpClient(self.ws_url, timeout=10.0)
        try:
            self.assertEqual(client.navigate("https://example.test"), {"url": "https://example.test", "loaded": True})
            description = client.describe()
            self.assertEqual(description["title"], "Example")
            self.assertIn("hello", description["text"])
            self.assertTrue(client.click("#save"))
            self.assertTrue(client.type_text("#name", "alex"))
            self.assertEqual(client.screenshot(), PNG_1X1)
        finally:
            client.close()

    def test_unknown_method_raises_cdp_error(self) -> None:
        client = CdpClient(self.ws_url, timeout=10.0)
        try:
            with self.assertRaises(CdpError):
                client.call("Nope.method")
        finally:
            client.close()

    def test_chrome_command_helper(self) -> None:
        command = chrome_remote_debugging_command(9222)
        self.assertIn("--remote-debugging-port=9222", command)


if __name__ == "__main__":
    unittest.main()
