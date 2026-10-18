"""tool_layer.browser.http_get goes through the SSRF guard."""

from __future__ import annotations

import ipaddress
import socket
import urllib.request

import pytest

from ghostchimera.safety_layer.ssrf import _is_internal_address
from ghostchimera.tool_layer import browser

AUTH = {"authorized": True}


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    """Fail the test if any socket-level fetch is attempted."""

    def boom(*args, **kwargs):
        raise AssertionError("network I/O attempted for a URL that should have been blocked")

    monkeypatch.setattr(urllib.request, "build_opener", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://localhost/admin",  # resolves to loopback
        "https://169.254.169.254/latest/meta-data/iam/security-credentials/",  # cloud metadata
        "https://10.0.0.5/",
        "https://192.168.1.1/",
        "https://0.0.0.0/",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
    ],
)
def test_internal_targets_are_blocked_before_any_request(url: str, no_network) -> None:
    with pytest.raises(ValueError, match="SSRF"):
        browser.http_get(url, policy=AUTH)


def test_hostname_resolving_to_metadata_ip_is_blocked(monkeypatch: pytest.MonkeyPatch, no_network) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port, *a, **k: [(socket.AF_INET, 0, 0, "", ("169.254.169.254", 0))]
    )
    with pytest.raises(ValueError, match="SSRF"):
        browser.http_get("https://metadata.google.internal/computeMetadata/v1/", policy=AUTH)


def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port, *a, **k: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))]
    )


def test_public_url_is_fetched_through_the_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)
    seen = []

    class _Resp:
        status = 200
        headers = {"Content-Type": "text/html; charset=latin-1"}

        def read(self):
            return "caf\xe9".encode("latin-1")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Opener:
        def open(self, req, timeout=None):
            seen.append(req.full_url)
            return _Resp()

    handlers = []
    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: handlers.extend(h) or _Opener())
    assert browser.http_get("https://example.com/page", policy=AUTH) == "caf\xe9"
    assert seen == ["https://example.com/page"]
    # Redirects are re-validated by the SSRF redirect handler.
    assert any(type(h).__name__ == "_SSRFRedirectHandler" for h in handlers)


def test_http_errors_surface_as_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)

    class _Opener:
        def open(self, req, timeout=None):
            raise OSError("connection reset")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: _Opener())
    with pytest.raises(ValueError, match="connection reset"):
        browser.http_get("https://example.com/", policy=AUTH)


def test_https_only_and_authorization_still_enforced() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        browser.http_get("http://example.com/", policy=AUTH)
    with pytest.raises(PermissionError):
        browser.http_get("https://example.com/", policy=None)


@pytest.mark.parametrize(
    ("address", "blocked"),
    [("8.8.8.8", False), ("169.254.169.254", True), ("0.0.0.0", True), ("::ffff:10.0.0.1", True), ("::", True)],
)
def test_internal_address_classifier(address: str, blocked: bool) -> None:
    assert _is_internal_address(ipaddress.ip_address(address)) is blocked
