"""SSRF guard edge cases (written from testteeth survivors).

Covers the IPv6 transition forms that hide an IPv4 address, the DNS
fail-closed paths of ``SSRFPolicy.is_permitted``, ``resolve_vetted_addresses``,
the post-connect peer re-check in ``_connect_vetted``, redirect re-validation
and the pinned opener end to end against a local server.
"""

from __future__ import annotations

import http.server
import ipaddress
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator

import pytest

from ghostchimera.safety_layer import ssrf
from ghostchimera.safety_layer.ssrf import (
    FetchResult,
    NetworkDispatcher,
    SSRFPolicy,
    SSRFViolation,
    resolve_vetted_addresses,
)

V4 = ipaddress.IPv4Address
V6 = ipaddress.IPv6Address


# ---------------------------------------------------------------------------
# Address classification
# ---------------------------------------------------------------------------


def test_v4_embedded_forms_extracts_mapped_6to4_and_teredo() -> None:
    assert ssrf._v4_embedded_forms(V6("::ffff:10.1.2.3")) == [V4("10.1.2.3")]
    # 6to4: 2002:VVVV:VVVV::/48 carries 192.168.1.1
    assert ssrf._v4_embedded_forms(V6("2002:c0a8:0101::1")) == [V4("192.168.1.1")]
    # Teredo: client v4 is the bit-inverted last 32 bits (here 192.0.2.45 -> inverted)
    teredo = V6("2001:0:4136:e378:8000:63bf:3fff:fdd2")
    assert ssrf._v4_embedded_forms(teredo) == [teredo.teredo[1]]
    assert ssrf._v4_embedded_forms(V6("2606:4700::1111")) == []
    assert ssrf._v4_embedded_forms(V4("8.8.8.8")) == []
    # 2003::/16 is not 6to4 (prefix match must be exact).
    assert ssrf._v4_embedded_forms(V6("2003:c0a8:0101::1")) == []


@pytest.mark.parametrize(
    "addr",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "192.0.0.8", "::1", "fe80::1", "::ffff:127.0.0.1"],
)
def test_internal_addresses_are_blocked(addr: str) -> None:
    assert ssrf._in_always_internal(ipaddress.ip_address(addr)) is True
    assert ssrf._is_internal_address(ipaddress.ip_address(addr)) is True


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_not_internal(addr: str) -> None:
    assert ssrf._in_always_internal(ipaddress.ip_address(addr)) is False
    assert ssrf._is_internal_address(ipaddress.ip_address(addr)) is False


# ---------------------------------------------------------------------------
# resolve_vetted_addresses
# ---------------------------------------------------------------------------


def _info(ip: str, port: int = 80) -> tuple:
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (fam, socket.SOCK_STREAM, 6, "", (ip, port))


def test_resolve_literal_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: pytest.fail("literal must not hit DNS"))
    assert resolve_vetted_addresses("8.8.8.8", 443) == [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443))]
    assert resolve_vetted_addresses("[2606:4700::1111]", 80) == [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2606:4700::1111", 80))
    ]
    with pytest.raises(SSRFViolation, match="Private/loopback"):
        resolve_vetted_addresses("127.0.0.1", 80)


def test_resolve_hostname_vets_every_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: [_info("8.8.8.8"), _info("10.0.0.5")])
    with pytest.raises(SSRFViolation, match="10.0.0.5"):
        resolve_vetted_addresses("mixed.test", 80)


def test_resolve_hostname_skips_non_ip_and_requires_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: [_info("not-an-ip"), _info("8.8.4.4")])
    assert resolve_vetted_addresses("ok.test", 80) == [_info("8.8.4.4")]
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: [_info("garbage")])
    with pytest.raises(SSRFViolation, match="No routable address"):
        resolve_vetted_addresses("none.test", 80)


def test_resolve_hostname_strips_scope_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: [_info("fe80::1%eth0")])
    with pytest.raises(SSRFViolation):
        resolve_vetted_addresses("scoped.test", 80)


def test_dns_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_DNS_RESOLVE_TIMEOUT", 0.05)
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: time.sleep(0.5) or [_info("8.8.8.8")])
    with pytest.raises(OSError, match="timed out"):
        ssrf._getaddrinfo_with_timeout("slow.test", 80)


# ---------------------------------------------------------------------------
# SSRFPolicy
# ---------------------------------------------------------------------------


def test_allow_and_deny_lists_dedupe_and_remove() -> None:
    policy = SSRFPolicy()
    policy.allow_host("a.test")
    policy.allow_host("a.test")
    policy.deny_host("b.test")
    policy.deny_host("b.test")
    assert policy.to_dict()["allowed"] == ["a.test"]
    assert policy.to_dict()["denied"] == ["b.test"]
    policy.deny_host("c.test")
    policy.remove_denied("b.test")
    assert policy.to_dict()["denied"] == ["c.test"]
    policy.remove_allowed("a.test")
    assert policy.to_dict()["allowed"] == []


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/", "gopher://x/", "data:text/plain,hi"])
def test_non_http_schemes_denied_even_with_allow_all(url: str) -> None:
    assert SSRFPolicy(allow_all=True).is_permitted(url)[0] is False


def test_no_host_and_deny_pattern() -> None:
    policy = SSRFPolicy(default_allow=True)
    assert policy.is_permitted("http:///nohost") == (False, "URL has no host")
    policy.deny_host("*.evil.test")
    ok, reason = policy.is_permitted("http://x.evil.test/")
    assert ok is False and "deny pattern" in reason


def test_private_ranges_can_be_disabled() -> None:
    assert SSRFPolicy(block_private_ranges=False, default_allow=True).is_permitted("http://127.0.0.1/")[0] is True
    assert SSRFPolicy(default_allow=True).is_permitted("http://127.0.0.1/")[0] is False


def test_dns_failure_denies_unless_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(ssrf.socket, "getaddrinfo", boom)
    ok, reason = SSRFPolicy(default_allow=True).is_permitted("http://down.test/")
    assert ok is False and "DNS resolution failed" in reason
    policy = SSRFPolicy()
    policy.allow_host("down.test")
    ok, reason = policy.is_permitted("http://down.test/")
    assert ok is True and "unavailable" in reason


def test_dns_timeout_denies_unless_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_DNS_RESOLVE_TIMEOUT", 0.05)
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: time.sleep(0.5) or [_info("8.8.8.8")])
    ok, reason = SSRFPolicy(default_allow=True).is_permitted("http://slow.test/")
    assert ok is False and "timed out" in reason
    policy = SSRFPolicy()
    policy.allow_host("slow.test")
    ok, reason = policy.is_permitted("http://slow.test/")
    assert ok is True and "timed out" in reason


def test_resolved_internal_address_denied_and_non_ip_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: [_info("weird"), _info("169.254.169.254")])
    policy = SSRFPolicy()
    policy.allow_host("meta.test")
    ok, reason = policy.is_permitted("http://meta.test/")
    assert ok is False and "169.254.169.254" in reason
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: [_info("weird"), _info("8.8.8.8")])
    assert policy.is_permitted("http://meta.test/") == (True, "Host 'meta.test' matches allow pattern 'meta.test'")
    assert SSRFPolicy().is_permitted("http://other.test/")[0] is False
    assert SSRFPolicy(default_allow=True).is_permitted("http://other.test/") == (True, "default_allow is set")


def test_fetch_result_ok_bounds() -> None:
    assert FetchResult(url="u", status_code=200).ok is True
    assert FetchResult(url="u", status_code=299).ok is True
    assert FetchResult(url="u", status_code=300).ok is False
    assert FetchResult(url="u", status_code=199).ok is False
    assert FetchResult(url="u").ok is False


# ---------------------------------------------------------------------------
# Redirects and pinned connections
# ---------------------------------------------------------------------------


def test_redirect_handler_revalidates_location() -> None:
    policy = SSRFPolicy(default_allow=True)
    handler = ssrf._SSRFRedirectHandler(policy)
    req = urllib.request.Request("http://8.8.8.8/start")
    with pytest.raises(SSRFViolation, match="Redirect to 'http://169.254.169.254/"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://169.254.169.254/latest")
    new = handler.redirect_request(req, None, 302, "Found", {}, "http://8.8.4.4/next")
    assert isinstance(new, urllib.request.Request)
    assert new.full_url == "http://8.8.4.4/next"


@pytest.fixture()
def local_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[int, list[str]]]:
    # An ambient HTTP(S)_PROXY would route around the pinned handler by design.
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hits.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_port}/denied")
                self.end_headers()
                return
            body = b"pinned-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Test", "Yes")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], hits
    finally:
        server.shutdown()
        server.server_close()


def test_connect_vetted_rechecks_peer_and_closes(monkeypatch: pytest.MonkeyPatch, local_server) -> None:
    port, _hits = local_server
    monkeypatch.setattr(ssrf, "resolve_vetted_addresses", lambda h, p: [_info("127.0.0.1", port)])
    closed: list[bool] = []
    real_close = socket.socket.close

    def tracking_close(self):  # type: ignore[no-untyped-def]
        closed.append(True)
        return real_close(self)

    monkeypatch.setattr(socket.socket, "close", tracking_close)
    with pytest.raises(SSRFViolation, match="Connected peer 127.0.0.1"):
        ssrf._connect_vetted("rebind.test", port, 2.0)
    assert closed, "the internal-peer socket must be closed"


def test_connect_vetted_tries_next_address_and_reports_last_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_is_internal_address", lambda _a: False)
    # Port 1 on loopback refuses; with no other candidates the OSError surfaces.
    monkeypatch.setattr(ssrf, "resolve_vetted_addresses", lambda h, p: [_info("127.0.0.1", 1)])
    with pytest.raises(OSError):
        ssrf._connect_vetted("refused.test", 1, 1.0)


def test_pinned_dispatcher_connects_to_vetted_address(monkeypatch: pytest.MonkeyPatch, local_server) -> None:
    port, hits = local_server
    # "pinned.test" does not exist; the only way to reach the server is via the vetted answer.
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", lambda *a, **k: [_info("127.0.0.1", port)])
    monkeypatch.setattr(ssrf, "_is_internal_address", lambda _a: False)
    timeouts: list[float] = []
    real_settimeout = socket.socket.settimeout

    def tracking_settimeout(self, value):  # type: ignore[no-untyped-def]
        timeouts.append(value)
        return real_settimeout(self, value)

    monkeypatch.setattr(socket.socket, "settimeout", tracking_settimeout)
    policy = SSRFPolicy()
    policy.allow_host("pinned.test")
    result = NetworkDispatcher(policy).fetch(f"http://pinned.test:{port}/hello", timeout_seconds=3.0)
    assert result.status_code == 200 and result.ok is True
    assert result.body == b"pinned-ok"
    assert result.headers.get("x-test") == "Yes"
    assert hits == ["/hello"]
    assert 3.0 in timeouts


def test_redirect_violation_propagates_from_fetch(local_server) -> None:
    port, hits = local_server
    policy = SSRFPolicy(block_private_ranges=False, default_allow=True)
    policy.deny_host("localhost")
    with pytest.raises(SSRFViolation, match="Redirect to"):
        NetworkDispatcher(policy).fetch(f"http://127.0.0.1:{port}/redirect")
    assert hits == ["/redirect"]


def test_fetch_blocked_raises_before_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: pytest.fail("no I/O on a blocked URL"))
    with pytest.raises(SSRFViolation, match="blocked"):
        NetworkDispatcher().fetch("http://127.0.0.1/")


def test_fetch_network_error_becomes_result(local_server) -> None:
    port, _ = local_server
    policy = SSRFPolicy(block_private_ranges=False, default_allow=True)
    result = NetworkDispatcher(policy).fetch("http://127.0.0.1:1/", timeout_seconds=1.0)
    assert result.status_code == 0 and result.ok is False and result.error


def test_module_fetch_uses_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    ssrf.reset_dispatcher()
    try:
        with pytest.raises(SSRFViolation):
            ssrf.fetch("http://10.0.0.1/")
        assert ssrf.get_dispatcher() is ssrf.get_dispatcher()
    finally:
        ssrf.reset_dispatcher()
