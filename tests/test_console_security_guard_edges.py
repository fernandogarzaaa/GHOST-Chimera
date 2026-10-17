"""Edge cases for the console Host/Origin/Content-Type guard.

Written from testteeth survivors: every refusal must be a real ``False`` (not
merely falsy), the bind host must be honoured, and loopback aliasing must
not leak to non-loopback hosts.
"""

from __future__ import annotations

import pytest

from ghostchimera.control_plane.console_security import (
    ConsoleRequestGuard,
    GuardRejection,
    is_loopback_host,
    normalize_host,
    parse_extra_hosts,
    split_host_port,
)


def test_normalize_host_strips_only_balanced_brackets() -> None:
    assert normalize_host("[::1]") == "::1"
    assert normalize_host(" LocalHost ") == "localhost"
    # Half a bracket pair is not an IPv6 literal and is kept verbatim.
    assert normalize_host("[::1") == "[::1"
    assert normalize_host("::1]") == "::1]"


def test_split_host_port_unterminated_bracket() -> None:
    assert split_host_port("[::1") == ("[::1", "")
    assert split_host_port("[::1]:8765") == ("::1", "8765")
    assert split_host_port("[::1]") == ("::1", "")
    assert split_host_port("::1") == ("::1", "")
    assert split_host_port("Example.COM:80") == ("example.com", "80")


def test_is_loopback_host() -> None:
    assert is_loopback_host("localhost") is True
    assert is_loopback_host("[::1]") is True
    assert is_loopback_host("127.0.0.1") is True
    assert is_loopback_host("10.0.0.1") is False
    assert is_loopback_host("localhost.evil.com") is False


def test_parse_extra_hosts_none_and_dedupe() -> None:
    assert parse_extra_hosts(None) == []
    assert parse_extra_hosts("") == []
    assert parse_extra_hosts("a.example, ,A.example:9,https://b.example:443/x,:80") == ["a.example", "b.example"]


def test_guard_rejection_payload_is_not_ok() -> None:
    payload = GuardRejection(403, "nope").payload()
    assert payload == {"ok": False, "error": "nope"}
    assert payload["ok"] is False


def test_bind_host_is_allowed_but_wildcard_is_not() -> None:
    guard = ConsoleRequestGuard(bind_host="192.168.1.20")
    assert guard.host_allowed("192.168.1.20:8765") is True
    wildcard = ConsoleRequestGuard(bind_host="0.0.0.0")
    assert wildcard.host_allowed("0.0.0.0:8765") is False
    assert "0.0.0.0" not in wildcard.allowed_hosts


def test_host_allowed_rejects_blank_and_unknown_with_false() -> None:
    guard = ConsoleRequestGuard()
    assert guard.host_allowed("") is False
    assert guard.host_allowed("   ") is False
    assert guard.host_allowed("attacker.example") is False
    assert guard.host_allowed("localhost:1") is True


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "NULL",
        "http://[::1",  # urlsplit raises ValueError
        "ftp://127.0.0.1:8765",
        "http://user@127.0.0.1:8765",
        "http://",
        "http://attacker.example:8765",
        "http://127.0.0.1:9999",
    ],
)
def test_origin_refusals_are_false(origin: str) -> None:
    guard = ConsoleRequestGuard()
    assert guard.origin_allowed(origin, "127.0.0.1:8765") is False


def test_each_origin_shape_condition_rejects_on_its_own() -> None:
    # Each clause of the scheme / userinfo / empty-netloc test must reject alone.
    guard = ConsoleRequestGuard()
    host = "127.0.0.1:8765"
    assert guard.origin_allowed("ws://127.0.0.1:8765", host) is False  # scheme only
    assert guard.origin_allowed("http://a@127.0.0.1:8765", host) is False  # userinfo only
    assert guard.origin_allowed("http:///path", host) is False  # empty netloc only


def test_origin_same_host_and_default_ports() -> None:
    guard = ConsoleRequestGuard(extra_hosts=["console.lan"])
    assert guard.origin_allowed("", "127.0.0.1:8765") is True
    assert guard.origin_allowed("http://console.lan", "console.lan:80") is True
    assert guard.origin_allowed("https://console.lan", "console.lan") is True
    assert guard.origin_allowed("https://console.lan", "console.lan:80") is False
    assert guard.origin_allowed("http://localhost:8765", "127.0.0.1:8765") is True


def test_loopback_aliasing_does_not_extend_to_other_allowed_hosts() -> None:
    guard = ConsoleRequestGuard(extra_hosts=["console.lan"])
    # Both allowed, same port, different hosts, only one is loopback: refuse.
    assert guard.origin_allowed("http://console.lan:8765", "127.0.0.1:8765") is False
    assert guard.origin_allowed("http://127.0.0.1:8765", "console.lan:8765") is False
    other = ConsoleRequestGuard(extra_hosts=["a.lan", "b.lan"])
    assert other.origin_allowed("http://a.lan:8765", "b.lan:8765") is False


def test_check_end_to_end_statuses() -> None:
    guard = ConsoleRequestGuard()
    ok_headers = {"Host": "127.0.0.1:8765", "Content-Type": "application/json; charset=utf-8"}
    assert guard.check("POST", "/api/x", ok_headers) is None
    assert guard.check("GET", "/", {"Host": "127.0.0.1:8765", "Origin": "http://evil"}) is None
    rejected = guard.check("POST", "/api/x", {"Host": "127.0.0.1:8765", "Content-Type": "text/plain"})
    assert rejected is not None and rejected.status == 415
    webhook = guard.check("POST", "/api/webhooks/github", {"Host": "127.0.0.1:8765", "Content-Type": "text/plain"})
    assert webhook is None
