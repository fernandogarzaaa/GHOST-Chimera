"""Request hardening and per-install secrets for the Ghost Console.

Ported from the ghost-chimera-rs console API (``crates/ghost-console-api/
src/server.rs``) and tightened for the Python console, which can arm an
unrestricted host-execution mode:

- **Host allow-list (DNS rebinding).** Every request must carry a ``Host``
  header naming ``localhost``, ``127.0.0.1`` or ``[::1]`` (any port), the
  configured bind host, or an operator-configured extra host.
- **Origin check (cross-site request forgery).** State-changing requests
  (POST/PUT/PATCH/DELETE) with a foreign ``Origin``, the opaque ``null``
  origin, or ``Sec-Fetch-Site: cross-site`` are refused. A browser page can
  only drive the console from the console's own origin.
- **JSON-only mutations.** State-changing requests must declare
  ``Content-Type: application/json``. ``text/plain`` / form bodies are the
  "simple request" shapes a hostile page can send without a CORS preflight.

Per-install secrets (console token, host-execution arming phrase) live in
:mod:`ghostchimera.control_plane.console_secrets`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

ALLOWED_HOSTS_ENV = "GHOSTCHIMERA_CONSOLE_ALLOWED_HOSTS"
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_WILDCARD_BIND_HOSTS = frozenset({"", "0.0.0.0", "::", "*"})

# Routes that accept server-to-server deliveries with their own signature
# checks (Slack/GitHub/etc. send form or vendor content types). The Host and
# Origin checks still apply; only the JSON content-type rule is waived.
CONTENT_TYPE_EXEMPT_PREFIXES: tuple[str, ...] = ("/api/webhooks/",)


# ---------------------------------------------------------------------------
# Host / Origin parsing
# ---------------------------------------------------------------------------


def normalize_host(host: str) -> str:
    """Lower-case a bare host name and strip IPv6 brackets."""
    value = str(host or "").strip().lower()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return value


def split_host_port(value: str) -> tuple[str, str]:
    """Split a ``Host`` header value into ``(host, port)``.

    Handles ``host``, ``host:port``, ``[v6]`` and ``[v6]:port``. A bare IPv6
    literal (more than one colon, no brackets) has no port. The host is
    normalized; the port is returned as written ("" when absent).
    """
    raw = str(value or "").strip()
    if raw.startswith("["):
        end = raw.find("]")
        if end == -1:
            return normalize_host(raw), ""
        host = raw[1:end]
        rest = raw[end + 1 :]
        port = rest[1:] if rest.startswith(":") else ""
        return normalize_host(host), port
    if raw.count(":") == 1:
        host, port = raw.split(":", 1)
        return normalize_host(host), port
    return normalize_host(raw), ""


def is_loopback_host(host: str) -> bool:
    """True for ``localhost``, ``127.0.0.1`` and ``::1`` (brackets allowed)."""
    return normalize_host(host) in LOOPBACK_HOSTS


def is_loopback_host_header(value: str) -> bool:
    """True when a ``Host`` header names a loopback host (any port)."""
    host, _port = split_host_port(value)
    return host in LOOPBACK_HOSTS


def _default_port(scheme: str) -> str:
    return {"http": "80", "https": "443"}.get(scheme, "")


def _media_type(content_type: str) -> str:
    return str(content_type or "").split(";", 1)[0].strip().lower()


def parse_extra_hosts(values: Iterable[str] | str | None) -> list[str]:
    """Normalize operator-configured extra hosts (comma lists allowed)."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    hosts: list[str] = []
    for item in values:
        for part in str(item or "").split(","):
            part = part.strip()
            if not part:
                continue
            authority = urlsplit(part).netloc if "://" in part else part
            host, _port = split_host_port(authority)
            if host and host not in hosts:
                hosts.append(host)
    return hosts


# ---------------------------------------------------------------------------
# Request guard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardRejection:
    """Why a request was refused before reaching any route."""

    status: int
    error: str

    def payload(self) -> dict[str, Any]:
        return {"ok": False, "error": self.error}


class ConsoleRequestGuard:
    """Host / Origin / Content-Type gate applied to every console request.

    Install with ``server.routes.request_guard = guard``. The gateway calls
    :meth:`check` before route lookup and authentication.
    """

    def __init__(self, *, bind_host: str = "127.0.0.1", extra_hosts: Iterable[str] | None = None) -> None:
        allowed = set(LOOPBACK_HOSTS)
        bind = normalize_host(bind_host)
        if bind not in _WILDCARD_BIND_HOSTS:
            allowed.add(bind)
        allowed.update(parse_extra_hosts(extra_hosts))
        self.allowed_hosts = frozenset(allowed)

    # -- individual checks -------------------------------------------------

    def host_allowed(self, host_header: str) -> bool:
        if not str(host_header or "").strip():
            return False
        host, _port = split_host_port(host_header)
        return host in self.allowed_hosts

    def origin_allowed(self, origin: str, host_header: str) -> bool:
        """Same-origin check: the Origin must name this console's own authority."""
        value = str(origin or "").strip()
        if not value:
            return True  # non-browser client (curl, CLI, SDK)
        if value.lower() == "null":
            return False  # sandboxed iframe, file:, data: — never the console
        try:
            parts = urlsplit(value)
        except ValueError:
            return False
        scheme = (parts.scheme or "").lower()
        if scheme not in {"http", "https"} or "@" in parts.netloc or not parts.netloc:
            return False
        origin_host, origin_port = split_host_port(parts.netloc)
        if origin_host not in self.allowed_hosts:
            return False
        req_host, req_port = split_host_port(host_header)
        origin_port = origin_port or _default_port(scheme)
        req_port = req_port or _default_port(scheme)
        if origin_port != req_port:
            return False  # another local web app on a different port
        # Loopback aliases (localhost vs 127.0.0.1) are the same machine.
        if origin_host == req_host:
            return True
        return origin_host in LOOPBACK_HOSTS and req_host in LOOPBACK_HOSTS

    # -- combined gate -----------------------------------------------------

    def check(self, method: str, path: str, headers: dict[str, str]) -> GuardRejection | None:
        """Return a rejection for a disallowed request, or ``None`` to proceed."""
        lowered = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        host_header = lowered.get("host", "")
        if not self.host_allowed(host_header):
            return GuardRejection(403, "forbidden: host not allowed (set GHOSTCHIMERA_CONSOLE_ALLOWED_HOSTS)")
        if str(method or "").upper() not in STATE_CHANGING_METHODS:
            return None
        if lowered.get("sec-fetch-site", "").strip().lower() == "cross-site":
            return GuardRejection(403, "forbidden: cross-site request")
        if not self.origin_allowed(lowered.get("origin", ""), host_header):
            return GuardRejection(403, "forbidden: origin not allowed")
        exempt = any(str(path or "").startswith(prefix) for prefix in CONTENT_TYPE_EXEMPT_PREFIXES)
        if not exempt and _media_type(lowered.get("content-type", "")) != "application/json":
            return GuardRejection(415, "unsupported media type: state-changing requests require application/json")
        return None


def allowed_hosts_from_env() -> list[str]:
    return parse_extra_hosts(os.environ.get(ALLOWED_HOSTS_ENV, ""))


__all__ = [
    "ALLOWED_HOSTS_ENV",
    "CONTENT_TYPE_EXEMPT_PREFIXES",
    "ConsoleRequestGuard",
    "GuardRejection",
    "allowed_hosts_from_env",
    "is_loopback_host",
    "is_loopback_host_header",
    "parse_extra_hosts",
    "split_host_port",
]
