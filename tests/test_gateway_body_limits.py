"""Gateway HTTP: auth before body read, size cap, bad Content-Length -> 400 (codeaudit F17)."""

from __future__ import annotations

import http.client
import json
import socket

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer

TOKEN = "gw-test-token-0123456789"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("GHOSTCHIMERA_MAX_HTTP_BODY_BYTES", "4096")
    srv = GatewayServer(host="127.0.0.1", port=0, http_port=0)
    seen: list[dict] = []

    def echo(ctx):
        seen.append(ctx)
        return {"ok": True, "len": len(ctx["body"]), "query": ctx["query"]}

    srv.routes.register("/secure", echo, method="POST", auth="token", token=TOKEN)
    srv.routes.register("/open", echo, method="POST", auth="open")
    srv.start()
    try:
        yield srv._http_server.server_address[1], seen  # type: ignore[union-attr]
    finally:
        srv.stop()


def _raw(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(request)
        chunks = []
        while True:
            try:
                data = sock.recv(65536)
            except TimeoutError:
                break
            if not data:
                break
            chunks.append(data)
        return b"".join(chunks)


def test_unauthenticated_huge_body_is_refused_before_reading(server) -> None:
    port, seen = server
    # Claims 1 GiB but sends nothing: the old code blocked reading it before auth.
    reply = _raw(port, b"POST /secure HTTP/1.1\r\nHost: x\r\nContent-Length: 1073741824\r\n\r\n")
    assert b" 401 " in reply.split(b"\r\n", 1)[0]
    assert seen == []


def test_oversized_body_is_413(server) -> None:
    port, seen = server
    reply = _raw(
        port,
        b"POST /secure HTTP/1.1\r\nHost: x\r\nX-Gateway-Token: "
        + TOKEN.encode()
        + b"\r\nContent-Length: 999999\r\n\r\n",
    )
    assert b" 413 " in reply.split(b"\r\n", 1)[0]
    assert seen == []


@pytest.mark.parametrize("value", [b"abc", b"-5", b"1e3"])
def test_bad_content_length_is_400_not_a_traceback(server, value) -> None:
    port, _ = server
    reply = _raw(port, b"POST /open HTTP/1.1\r\nHost: x\r\nContent-Length: " + value + b"\r\n\r\n")
    assert b" 400 " in reply.split(b"\r\n", 1)[0]


def test_normal_request_and_query_decoding(server) -> None:
    port, _ = server
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/secure?q=a+b&x=%2F", body=b'{"a":1}', headers={"X-Gateway-Token": TOKEN})
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    assert resp.status == 200 and data["len"] == 7
    assert data["query"] == {"q": "a b", "x": "/"}
