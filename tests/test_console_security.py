"""Console request hardening: cross-site, DNS-rebinding and simple-request
attacks against the Ghost Console HTTP API must be refused.

Reproduces the audit finding: with no ``--auth-token`` a web page could POST
``text/plain`` to ``/api/console/host-execution/settings`` (arm host mode with
the public phrase) and then ``/api/console/host-execution/run`` (``id``).
"""

from __future__ import annotations

import http.client
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from ghostchimera.control_plane.console import run_console
from ghostchimera.control_plane.console_security import (
    ConsoleRequestGuard,
    is_loopback_host_header,
    parse_extra_hosts,
    split_host_port,
)

SETTINGS_PATH = "/api/console/host-execution/settings"
ARM_BODY = {"unrestricted_host_mode": True, "confirmation_phrase": "I ACCEPT HOST EXECUTION RISK"}


class GuardUnitTests(unittest.TestCase):
    def test_host_header_parsing(self) -> None:
        self.assertEqual(split_host_port("127.0.0.1:8766"), ("127.0.0.1", "8766"))
        self.assertEqual(split_host_port("[::1]:9"), ("::1", "9"))
        self.assertEqual(split_host_port("::1"), ("::1", ""))
        self.assertEqual(split_host_port(" LocalHost "), ("localhost", ""))
        self.assertTrue(is_loopback_host_header("localhost:3000"))
        self.assertTrue(is_loopback_host_header("[::1]:8766"))
        self.assertFalse(is_loopback_host_header("127.0.0.1.evil.example"))
        self.assertFalse(is_loopback_host_header("evil.example:8766"))
        self.assertFalse(is_loopback_host_header("[::2]:80"))

    def test_extra_hosts_parsing(self) -> None:
        self.assertEqual(
            parse_extra_hosts(["ghost.example.com, 10.0.0.5:8766", "https://Box.LAN:8443"]),
            ["ghost.example.com", "10.0.0.5", "box.lan"],
        )

    def test_guard_matrix(self) -> None:
        guard = ConsoleRequestGuard(bind_host="0.0.0.0", extra_hosts=["ghost.example.com"])
        ok_post = {"host": "127.0.0.1:8766", "origin": "http://127.0.0.1:8766", "content-type": "application/json"}
        self.assertIsNone(guard.check("POST", "/api/x", ok_post))
        self.assertIsNone(guard.check("POST", "/api/x", {**ok_post, "origin": "http://localhost:8766"}))
        self.assertIsNone(guard.check("POST", "/api/x", {**ok_post, "content-type": "application/json; charset=utf-8"}))
        self.assertIsNone(guard.check("GET", "/api/x", {"host": "ghost.example.com"}))
        # wildcard bind host is never itself an allowed Host
        self.assertEqual(guard.check("GET", "/", {"host": "0.0.0.0:8766"}).status, 403)
        self.assertEqual(guard.check("GET", "/", {}).status, 403)
        self.assertEqual(guard.check("POST", "/api/x", {**ok_post, "origin": "http://localhost:3000"}).status, 403)
        self.assertEqual(guard.check("POST", "/api/x", {**ok_post, "origin": "http://user@127.0.0.1:8766"}).status, 403)
        self.assertEqual(guard.check("POST", "/api/x", {**ok_post, "sec-fetch-site": "cross-site"}).status, 403)
        self.assertEqual(guard.check("POST", "/api/x", {**ok_post, "content-type": ""}).status, 415)
        # signed webhook deliveries keep their vendor content types
        self.assertIsNone(
            guard.check(
                "POST",
                "/api/webhooks/slack",
                {"host": "127.0.0.1", "content-type": "application/x-www-form-urlencoded"},
            )
        )


class LiveConsoleSecurityTests(unittest.TestCase):
    """Drive a real console over HTTP, exactly as a browser or attacker would."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.state_dir = Path(cls._tmp.name)
        cls.server = run_console(
            host="127.0.0.1", port=0, http_port=0, state_dir=cls.state_dir, open_browser=False, block=False
        )
        cls.port = int(cls.server._http_server.server_address[1])
        cls.origin = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls._tmp.cleanup()

    def auth_headers(self) -> dict[str, str]:
        return {}

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
        host: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            payload = body if isinstance(body, (bytes, str)) or body is None else json.dumps(body)
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host if host is not None else f"127.0.0.1:{self.port}")
            data = payload.encode() if isinstance(payload, str) else (payload or b"")
            for name, value in (headers or {}).items():
                conn.putheader(name, value)
            conn.putheader("Content-Length", str(len(data)))
            conn.endheaders(data)
            resp = conn.getresponse()
            raw = resp.read()
            try:
                parsed = json.loads(raw or b"{}")
            except ValueError:
                parsed = {"raw": raw.decode("utf-8", "replace")}
            return resp.status, parsed if isinstance(parsed, dict) else {"value": parsed}
        finally:
            conn.close()

    def json_post_headers(self, **extra: str) -> dict[str, str]:
        return {"Content-Type": "application/json", "Origin": self.origin, **self.auth_headers(), **extra}

    def assert_not_armed(self) -> None:
        status, payload = self.request("GET", SETTINGS_PATH, headers=self.auth_headers())
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["settings"]["unrestricted_host_mode"])

    def test_forged_cross_site_post_is_rejected(self) -> None:
        status, payload = self.request(
            "POST", SETTINGS_PATH, body=ARM_BODY, headers=self.json_post_headers(Origin="https://evil.example")
        )
        self.assertEqual(status, 403, payload)
        self.assertIn("origin", payload["error"])
        self.assert_not_armed()

    def test_cross_site_fetch_metadata_is_rejected(self) -> None:
        status, _ = self.request(
            "POST", SETTINGS_PATH, body=ARM_BODY, headers=self.json_post_headers(**{"Sec-Fetch-Site": "cross-site"})
        )
        self.assertEqual(status, 403)
        self.assert_not_armed()

    def test_dns_rebinding_host_is_rejected(self) -> None:
        # A rebinding attack reaches 127.0.0.1 but the browser still sends the attacker's hostname.
        status, payload = self.request("GET", SETTINGS_PATH, headers=self.auth_headers(), host="evil.example")
        self.assertEqual(status, 403, payload)
        self.assertIn("host", payload["error"])
        status, _ = self.request("GET", "/", host=f"rebind.evil.example:{self.port}")
        self.assertEqual(status, 403)
        status, _ = self.request(
            "POST",
            SETTINGS_PATH,
            body=ARM_BODY,
            headers=self.json_post_headers(Origin=f"http://evil.example:{self.port}"),
            host=f"evil.example:{self.port}",
        )
        self.assertEqual(status, 403)
        self.assert_not_armed()

    def test_null_origin_is_rejected(self) -> None:
        status, payload = self.request(
            "POST", SETTINGS_PATH, body=ARM_BODY, headers=self.json_post_headers(Origin="null")
        )
        self.assertEqual(status, 403, payload)
        self.assert_not_armed()

    def test_text_plain_body_is_rejected(self) -> None:
        # text/plain is a CORS "simple request": no preflight, so any page can send it.
        headers = self.json_post_headers(**{"Content-Type": "text/plain;charset=UTF-8"})
        status, payload = self.request("POST", SETTINGS_PATH, body=json.dumps(ARM_BODY), headers=headers)
        self.assertEqual(status, 415, payload)
        headers = {"Origin": self.origin, **self.auth_headers()}
        status, _ = self.request("POST", SETTINGS_PATH, body=json.dumps(ARM_BODY), headers=headers)
        self.assertEqual(status, 415)
        self.assert_not_armed()

    def test_correct_local_request_passes(self) -> None:
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"):
            status, payload = self.request("GET", "/api/console/status", headers=self.auth_headers(), host=host)
            self.assertEqual(status, 200, (host, payload))
        status, payload = self.request(
            "POST",
            SETTINGS_PATH,
            body={"unrestricted_host_mode": False},
            headers=self.json_post_headers(),
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"], payload)
        # Non-browser clients (CLI, curl) send no Origin and still work.
        headers = {"Content-Type": "application/json", **self.auth_headers()}
        status, payload = self.request("POST", SETTINGS_PATH, body={"unrestricted_host_mode": False}, headers=headers)
        self.assertEqual(status, 200, payload)


if __name__ == "__main__":
    unittest.main()
