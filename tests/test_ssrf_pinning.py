"""SSRF: DNS-rebinding pinning, scheme allow-list, non-global ranges (redteam P1-1, P1-2)."""

from __future__ import annotations

import http.server
import socket
import threading

import pytest

from ghostchimera.safety_layer import ssrf
from ghostchimera.safety_layer.ssrf import NetworkDispatcher, SSRFPolicy, SSRFViolation


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def internal_service():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b"SECRET-INTERNAL-SERVICE"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return None

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()


def test_redteam_poc_dns_rebinding_cannot_reach_loopback(internal_service, monkeypatch) -> None:
    port = internal_service
    real = socket.getaddrinfo
    answers = iter(["93.184.216.34"])

    def rebinding(host, *args, **kwargs):
        if host == "rebind.attacker.test":
            # First answer (policy check) is public, every later answer is loopback.
            ip = next(answers, "127.0.0.1")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding)
    dispatcher = NetworkDispatcher(SSRFPolicy(default_allow=True, block_private_ranges=True))
    try:
        result = dispatcher.fetch(f"http://rebind.attacker.test:{port}/")
    except SSRFViolation:
        return
    assert "SECRET-INTERNAL-SERVICE" not in result.text
    assert result.status_code == 0


def test_connection_goes_to_the_vetted_address_only(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_vetted(host, port):
        calls.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", port))]

    connected: list = []

    class FakeSock:
        def __init__(self, *a, **k):
            pass

        def settimeout(self, t):
            pass

        def connect(self, addr):
            connected.append(addr)
            raise OSError("stop here")

        def close(self):
            pass

    monkeypatch.setattr(ssrf, "resolve_vetted_addresses", fake_vetted)
    monkeypatch.setattr(ssrf.socket, "socket", FakeSock)
    with pytest.raises(OSError):
        ssrf._connect_vetted("example.com", 80, 5)
    assert connected == [("192.0.2.1", 80)] and calls == [("example.com", 80)]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/", "data:,hi"])
def test_non_http_schemes_are_refused(url) -> None:
    permitted, reason = SSRFPolicy(default_allow=True).is_permitted(url)
    assert permitted is False and "Scheme" in reason
    with pytest.raises(SSRFViolation):
        NetworkDispatcher(SSRFPolicy(default_allow=True)).fetch(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://100.64.0.1/",
        "http://100.100.100.100/",
        "http://192.0.0.8/",
        "http://198.18.0.1/",
        "http://[::ffff:100.64.0.1]/",
        "http://[2002:7f00:1::]/",
        "http://127.0.0.1/",
        "http://169.254.169.254/",
    ],
)
def test_non_global_addresses_are_blocked(url) -> None:
    assert SSRFPolicy(default_allow=True).is_permitted(url)[0] is False


def test_public_literal_still_allowed() -> None:
    assert SSRFPolicy(default_allow=True).is_permitted("https://93.184.216.34/")[0] is True
