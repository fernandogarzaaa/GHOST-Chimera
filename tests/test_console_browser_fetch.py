"""Browser tab Fetch passes the policy stamp to http_get (redteam P2-3)."""

from __future__ import annotations

import json

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.safety_layer.ssrf import FetchResult


def _call(server: GatewayServer, url: str) -> dict:
    route = server.routes.find("POST", "/api/console/browser/fetch")
    assert route is not None
    return route.handler(
        {"method": "POST", "path": "/api/console/browser/fetch", "headers": {}, "body": json.dumps({"url": url})}
    )


def test_browser_fetch_works_with_default_fetcher(tmp_path, monkeypatch) -> None:
    import ghostchimera.tool_layer.browser as browser

    seen: list[str] = []

    class FakeDispatcher:
        def fetch(self, url, **kwargs):
            seen.append(url)
            return FetchResult(url=url, status_code=200, body=b"hello page", headers={"content-type": "text/html"})

    monkeypatch.setattr(browser, "_browser_dispatcher", lambda: FakeDispatcher())
    server = GatewayServer()
    register_console_routes(server, state_dir=tmp_path)
    result = _call(server, "https://example.com/")
    assert result == {"ok": True, "url": "https://example.com/", "content": "hello page", "truncated": False}
    assert seen == ["https://example.com/"]


def test_browser_fetch_still_enforces_https_and_ssrf(tmp_path) -> None:
    server = GatewayServer()
    register_console_routes(server, state_dir=tmp_path)
    plain = _call(server, "http://example.com/")
    assert plain["ok"] is False and "HTTPS" in plain["error"]
    internal = _call(server, "https://127.0.0.1/")
    assert internal["ok"] is False and "SSRF" in internal["error"]
