"""SSRF: HTTPS through a proxy must bypass the pinning guard, not fail on the proxy IP.

For HTTPS, urllib's ProxyHandler rewrites the request in place: ``req.host``
becomes the *proxy's* host and the real destination moves to
``req._tunnel_host`` (so ``req.has_proxy()`` is False for https tunnels).
Without the bypass, the pinning guard vets the proxy's address, blocks
corporate proxies on private IPs, and breaks the CONNECT tunnel for every
HTTPS-through-proxy fetch.
"""

from __future__ import annotations

import socket
import ssl
import urllib.request
from unittest import mock

import pytest

from ghostchimera.safety_layer.ssrf import SSRFViolation, _PinnedHTTPSHandler


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)


def _pinned() -> _PinnedHTTPSHandler:
    return _PinnedHTTPSHandler(ssl.create_default_context())


def _direct_req(url: str) -> urllib.request.Request:
    # OpenerDirector sets this before dispatching handlers; tests set it directly.
    req = urllib.request.Request(url)
    req.timeout = None
    return req


def test_https_via_private_ip_corporate_proxy_delegates_to_stock_handler(monkeypatch) -> None:
    """A proxied HTTPS request must NOT be SSRF-checked against the proxy IP."""

    def no_dns(*args, **kwargs):
        raise AssertionError("no DNS should happen for a proxied request")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)

    handler = _pinned()
    req = urllib.request.Request("https://example.com/api")
    # Exactly what ProxyHandler.proxy_open does for {'https': 'http://10.24.0.7:3128'}.
    req.set_proxy("10.24.0.7:3128", "https")
    assert req.host == "10.24.0.7:3128"
    assert req._tunnel_host == "example.com"
    assert not req.has_proxy()  # https tunnels are invisible to has_proxy()

    with mock.patch.object(urllib.request.HTTPSHandler, "https_open", autospec=True) as stock:
        handler.https_open(req)
    stock.assert_called_once_with(handler, req)


def test_tunnel_host_delegates_even_when_set_directly() -> None:
    """The bypass keys off the tunnel target, not on proxy attrs being present."""
    handler = _pinned()
    req = urllib.request.Request("https://example.com/api")
    req._tunnel_host = "example.com"
    with mock.patch.object(urllib.request.HTTPSHandler, "https_open", autospec=True) as stock:
        handler.https_open(req)
    stock.assert_called_once_with(handler, req)


def test_direct_https_to_private_ip_still_blocked() -> None:
    """The fix must not open a hole for direct (non-proxy) private-IP fetches.

    stdlib ``do_open`` wraps the connection-time SSRFViolation in URLError;
    the assertion pins that the block still fires on the real destination.
    """
    handler = _pinned()
    req = _direct_req("https://192.168.9.9/api")
    with pytest.raises(urllib.error.URLError) as excinfo:
        handler.https_open(req)
    reason = excinfo.value.reason
    assert isinstance(reason, SSRFViolation)
    assert "192.168.9.9" in str(reason)


def test_direct_https_to_public_ip_still_uses_pinned_connection(monkeypatch) -> None:
    """Non-proxied HTTPS keeps the vetted pinning path with the real destination."""
    opened: list[tuple[str, str]] = []

    def spy_do_open(self, http_class, req, **kwargs):
        opened.append((http_class.__name__, req.host))
        raise AssertionError("stop before network")

    monkeypatch.setattr(_PinnedHTTPSHandler, "do_open", spy_do_open)
    handler = _pinned()
    req = _direct_req("https://93.184.216.34/api")
    with pytest.raises(AssertionError, match="stop before network"):
        handler.https_open(req)
    assert opened == [("_PinnedHTTPSConnection", "93.184.216.34")]
