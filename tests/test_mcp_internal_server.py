"""codeaudit F5: MCPServer.start() always raised TypeError.

Real server on an ephemeral port, real HTTP requests over loopback.
"""

from __future__ import annotations

import http.client
import json

import pytest

from ghostchimera.mcp.server import MCPServer


@pytest.fixture
def server():
    srv = MCPServer(host="127.0.0.1", port=0, auth_token="test-token-123")
    srv.register_tool("add", "Add two numbers", lambda args: args["a"] + args["b"])

    def _boom(_args):
        raise RuntimeError("secret detail")

    srv.register_tool("boom", "Always fails", _boom)
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()


def _post(srv: MCPServer, payload, token: str | None = "test-token-123", raw: bytes | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")
    conn.request("POST", "/", body=body, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, data


def test_start_binds_and_serves_discover_and_call(server) -> None:
    assert server.port > 0
    status, data = _post(server, {"action": "discover"})
    assert status == 200
    assert {tool["name"] for tool in data["tools"]} == {"add", "boom"}
    status, data = _post(server, {"action": "call", "name": "add", "arguments": {"a": 2, "b": 3}})
    assert status == 200
    assert data == {"name": "add", "result": 5}


def test_requests_without_the_token_are_rejected(server) -> None:
    assert _post(server, {"action": "discover"}, token=None)[0] == 401
    assert _post(server, {"action": "call", "name": "add", "arguments": {"a": 1, "b": 1}}, token="wrong")[0] == 401


def test_errors_are_reported_not_crashing_the_server(server) -> None:
    assert _post(server, {"action": "call", "name": "missing"})[0] == 404
    status, data = _post(server, {"action": "call", "name": "boom"})
    assert status == 500
    assert "secret detail" not in json.dumps(data)
    assert _post(server, {"action": "nope"})[0] == 400
    assert _post(server, None, raw=b"{not json")[0] == 400
    # Still serving after the failures.
    assert _post(server, {"action": "discover"})[0] == 200


def test_generated_token_when_none_given_and_restartable() -> None:
    srv = MCPServer(port=0)
    assert len(srv.auth_token) >= 32
    srv.start()
    try:
        assert _post(srv, {"action": "discover"}, token=srv.auth_token)[0] == 200
    finally:
        srv.stop()
    srv.start()  # stop() fully resets, so the server can start again
    try:
        assert _post(srv, {"action": "discover"}, token=srv.auth_token)[0] == 200
    finally:
        srv.stop()
