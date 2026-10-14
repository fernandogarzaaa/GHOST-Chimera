"""SSRF / network policy dispatcher for Ghost Chimera.

Mirrors OpenClaw's ``ssrf-policy``, ``ssrf-dispatcher``, and
``ssrf-runtime`` SDK subpaths.  Outbound network requests from backends
and tool-layer wrappers are evaluated against a per-request policy before
being dispatched.

Usage::

    from ghostchimera.safety_layer.ssrf import SSRFPolicy, NetworkDispatcher, get_dispatcher

    policy = SSRFPolicy()
    policy.allow_host("api.openai.com")

    dispatcher = get_dispatcher()
    result = dispatcher.fetch("https://api.openai.com/v1/models", headers={"Authorization": "Bearer ..."})
"""

from __future__ import annotations

import concurrent.futures
import http.client
import ipaddress
import socket
import ssl
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..http_identity import with_user_agent
from ..logging_config import get_logger

logger = get_logger("ssrf")

_DNS_RESOLVE_TIMEOUT = 5.0  # seconds


ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_internal_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for addresses an outbound fetch must never reach.

    Anything that is not globally routable is internal: private, loopback,
    link-local (incl. the 169.254.169.254 cloud metadata service),
    unspecified, reserved, multicast, shared/CGNAT space (100.64.0.0/10, used
    by Tailscale and carrier NAT), 192.0.0.0/24, benchmarking ranges, and
    IPv4-mapped / 6to4 / Teredo forms of any of them.
    """
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    if isinstance(addr, ipaddress.IPv6Address):
        for embedded in (addr.sixtofour, (addr.teredo or (None, None))[1]):
            if embedded is not None and _is_internal_address(embedded):
                return True
    return (
        not addr.is_global
        or addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_reserved
        or addr.is_multicast
    )


def _getaddrinfo_with_timeout(host: str, port: int | None) -> list[Any]:
    """``socket.getaddrinfo`` bounded by :data:`_DNS_RESOLVE_TIMEOUT` (fails closed)."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
        try:
            return future.result(timeout=_DNS_RESOLVE_TIMEOUT)
        except concurrent.futures.TimeoutError as exc:
            raise OSError(f"DNS resolution timed out for {host}") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def resolve_vetted_addresses(host: str, port: int) -> list[tuple[Any, ...]]:
    """Resolve *host* once and return only safe ``getaddrinfo`` entries.

    Raises :class:`SSRFViolation` when the host is (or resolves to) any
    internal address. The caller must connect to exactly these addresses so a
    second, attacker-controlled DNS answer (rebinding) is never consulted.
    """
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if _is_internal_address(literal):
            raise SSRFViolation(f"Private/loopback address blocked: {host}")
        family = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 0, "", (str(literal), port))]
    infos = _getaddrinfo_with_timeout(host, port)
    vetted = []
    for info in infos:
        try:
            addr = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        except ValueError:
            continue
        if _is_internal_address(addr):
            raise SSRFViolation(f"Hostname '{host}' resolves to private/loopback/link-local address: {addr}")
        vetted.append(info)
    if not vetted:
        raise SSRFViolation(f"No routable address for hostname: {host}")
    return vetted


# ---------------------------------------------------------------------------
# SSRF policy
# ---------------------------------------------------------------------------


@dataclass
class SSRFPolicy:
    """Per-request outbound network policy.

    Rules are evaluated in order:

    1. If ``allow_all`` is True, every request is permitted.
    2. If the hostname matches any **denied** pattern, the request is blocked.
    3. If the hostname matches any **allowed** pattern, the request is permitted.
    4. If ``default_allow`` is True, unmatched requests are permitted; otherwise denied.

    Glob patterns are supported via :func:`fnmatch.fnmatch`.

    Private / loopback addresses are blocked by default when
    ``block_private_ranges`` is True (default).
    """

    allow_all: bool = False
    default_allow: bool = False
    block_private_ranges: bool = True
    _allowed: list[str] = field(default_factory=list, repr=False)
    _denied: list[str] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, init=False)

    def allow_host(self, pattern: str) -> None:
        """Allowlist a hostname glob pattern (e.g. ``"*.openai.com"``)."""
        with self._lock:
            if pattern not in self._allowed:
                self._allowed.append(pattern)

    def deny_host(self, pattern: str) -> None:
        """Denylist a hostname glob pattern."""
        with self._lock:
            if pattern not in self._denied:
                self._denied.append(pattern)

    def remove_allowed(self, pattern: str) -> None:
        with self._lock:
            self._allowed = [p for p in self._allowed if p != pattern]

    def remove_denied(self, pattern: str) -> None:
        with self._lock:
            self._denied = [p for p in self._denied if p != pattern]

    def is_permitted(self, url: str) -> tuple[bool, str]:
        """Check whether *url* may be fetched.

        Returns
        -------
        tuple[bool, str]
            (permitted, reason)
        """
        import fnmatch

        parsed = urllib.parse.urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ALLOWED_SCHEMES:
            # file://, ftp://, gopher://, data: ... are never fetchable (redteam P1-2).
            return False, f"Scheme '{scheme or '(none)'}' is not allowed; only http and https"
        if self.allow_all:
            return True, "allow_all is set"

        hostname = parsed.hostname or ""
        if not hostname:
            return False, "URL has no host"
        with self._lock:
            denied = list(self._denied)
            allowed = list(self._allowed)

        for pattern in denied:
            if fnmatch.fnmatch(hostname, pattern):
                return False, f"Host '{hostname}' matches deny pattern '{pattern}'"

        allow_match = next((pattern for pattern in allowed if fnmatch.fnmatch(hostname, pattern)), None)

        # Block private/loopback ranges
        if self.block_private_ranges and hostname:
            try:
                addr = ipaddress.ip_address(hostname)
                if _is_internal_address(addr):
                    return False, f"Private/loopback address blocked: {hostname}"
            except ValueError:
                # Not a literal IP — resolve the hostname and check all resolved addresses.
                # Use a short-lived executor that is shut down without waiting so that
                # a blocked socket.getaddrinfo call cannot stall the caller after the
                # timeout fires.
                pool = None
                try:
                    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    future = pool.submit(socket.getaddrinfo, hostname, None)
                    try:
                        infos = future.result(timeout=_DNS_RESOLVE_TIMEOUT)
                    except concurrent.futures.TimeoutError:
                        # Fail closed: deny the request rather than skipping the IP
                        # check, because a slow/unresponsive DNS server should not
                        # be exploitable as an SSRF bypass.
                        logger.warning(
                            "DNS resolution for '%s' timed out after %.1fs; denying request",
                            hostname,
                            _DNS_RESOLVE_TIMEOUT,
                        )
                        if allow_match:
                            return True, (
                                f"Host '{hostname}' matches allow pattern '{allow_match}' and "
                                "DNS timed out during private-range verification"
                            )
                        return False, f"DNS resolution timed out for hostname: {hostname}"
                    for info in infos:
                        addr_str = info[4][0]
                        try:
                            addr = ipaddress.ip_address(addr_str)
                            if _is_internal_address(addr):
                                return False, (
                                    f"Hostname '{hostname}' resolves to private/loopback/link-local address: {addr_str}"
                                )
                        except ValueError:
                            logger.debug("Skipping non-IP DNS result for '%s': %s", hostname, addr_str)
                            continue
                except OSError as exc:
                    logger.warning("DNS resolution for '%s' failed; denying request: %s", hostname, exc)
                    if allow_match:
                        return True, (
                            f"Host '{hostname}' matches allow pattern '{allow_match}' and "
                            "DNS resolution is unavailable for private-range verification"
                        )
                    return False, f"DNS resolution failed for hostname: {hostname}"
                finally:
                    # Shut down without waiting so a still-running getaddrinfo thread
                    # does not block the caller.
                    if pool is not None:
                        pool.shutdown(wait=False, cancel_futures=True)

        if allow_match:
            return True, f"Host '{hostname}' matches allow pattern '{allow_match}'"

        if self.default_allow:
            return True, "default_allow is set"

        return False, f"Host '{hostname}' is not in the allowlist and default_allow is False"

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "allow_all": self.allow_all,
                "default_allow": self.default_allow,
                "block_private_ranges": self.block_private_ranges,
                "allowed": list(self._allowed),
                "denied": list(self._denied),
            }


# ---------------------------------------------------------------------------
# SSRFViolation
# ---------------------------------------------------------------------------


class SSRFViolation(PermissionError):
    """Raised when a network request is blocked by the SSRF policy."""


# ---------------------------------------------------------------------------
# Redirect handler
# ---------------------------------------------------------------------------


class _SSRFRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that re-validates every Location URL against the policy."""

    def __init__(self, policy: SSRFPolicy) -> None:
        self._policy = policy
        super().__init__()

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        permitted, reason = self._policy.is_permitted(newurl)
        if not permitted:
            raise SSRFViolation(f"Redirect to '{newurl}' blocked: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ---------------------------------------------------------------------------
# Pinned connections (DNS-rebinding defence, redteam P1-1)
# ---------------------------------------------------------------------------


def _connect_vetted(host: str, port: int, timeout: Any, source_address: Any = None) -> socket.socket:
    """Resolve once, connect only to a vetted address, and re-check the peer."""
    last_error: OSError | None = None
    for family, socktype, proto, _canon, sockaddr in resolve_vetted_addresses(host, port):
        sock = socket.socket(family, socktype, proto)
        try:
            if timeout is not None and timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:  # type: ignore[attr-defined]
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            peer = ipaddress.ip_address(str(sock.getpeername()[0]).split("%", 1)[0])
            if _is_internal_address(peer):
                raise SSRFViolation(f"Connected peer {peer} for '{host}' is internal")
            return sock
        except SSRFViolation:
            sock.close()
            raise
        except OSError as exc:
            sock.close()
            last_error = exc
    raise last_error or OSError(f"could not connect to {host}:{port}")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def connect(self) -> None:
        self.sock = _connect_vetted(self.host, self.port, self.timeout, self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        sock = _connect_vetted(self.host, self.port, self.timeout, self.source_address)
        # SNI and certificate verification stay bound to the *hostname*.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        if req.has_proxy():  # the operator's proxy resolves the target; nothing to pin locally
            return super().http_open(req)
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, context: ssl.SSLContext) -> None:
        super().__init__(context=context)
        self._pinned_context = context

    def https_open(self, req: urllib.request.Request) -> Any:
        if req.has_proxy():
            return super().https_open(req)
        return self.do_open(_PinnedHTTPSConnection, req, context=self._pinned_context)


# ---------------------------------------------------------------------------
# NetworkDispatcher
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """Result of a dispatched HTTP request."""

    url: str
    status_code: int = 0
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class NetworkDispatcher:
    """Wraps outbound HTTP requests with SSRF policy enforcement.

    All fetch calls are checked against the :class:`SSRFPolicy` before
    any network I/O occurs.
    """

    def __init__(self, policy: SSRFPolicy | None = None) -> None:
        self.policy = policy or SSRFPolicy()

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 15.0,
    ) -> FetchResult:
        """Fetch *url* after checking SSRF policy.

        Parameters
        ----------
        url:
            The URL to fetch.
        method:
            HTTP method.
        headers:
            Request headers.
        body:
            Request body bytes.
        timeout_seconds:
            Socket timeout.

        Raises
        ------
        SSRFViolation
            When the policy denies the request.
        """
        permitted, reason = self.policy.is_permitted(url)
        if not permitted:
            logger.warning("SSRF policy blocked request to %s: %s", url, reason)
            raise SSRFViolation(f"Request to '{url}' blocked: {reason}")

        logger.debug("NetworkDispatcher %s %s", method, url)
        hdrs = with_user_agent(headers)
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
            ctx = ssl.create_default_context()
            if self.policy.block_private_ranges and not self.policy.allow_all:
                # Connect only to the address that was vetted at connect time,
                # for the first request and every redirect hop.
                opener = urllib.request.build_opener(
                    _PinnedHTTPHandler(),
                    _PinnedHTTPSHandler(ctx),
                    _SSRFRedirectHandler(self.policy),
                )
            else:
                opener = urllib.request.build_opener(
                    urllib.request.HTTPSHandler(context=ctx),
                    _SSRFRedirectHandler(self.policy),
                )
            with opener.open(req, timeout=timeout_seconds) as resp:
                resp_body = resp.read()
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                return FetchResult(
                    url=url,
                    status_code=resp.status,
                    body=resp_body,
                    headers=resp_headers,
                )
        except SSRFViolation:
            raise
        except Exception as exc:
            return FetchResult(url=url, status_code=0, error=str(exc))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_dispatcher: NetworkDispatcher | None = None
_dispatcher_lock = threading.Lock()


def get_dispatcher(policy: SSRFPolicy | None = None) -> NetworkDispatcher:
    """Return the process-wide singleton :class:`NetworkDispatcher`."""
    global _dispatcher
    if _dispatcher is None:
        with _dispatcher_lock:
            if _dispatcher is None:
                _dispatcher = NetworkDispatcher(policy)
    return _dispatcher


def reset_dispatcher() -> None:
    """Reset the singleton (useful in tests)."""
    global _dispatcher
    with _dispatcher_lock:
        _dispatcher = None


def fetch(url: str, **kwargs: Any) -> FetchResult:
    """Convenience: fetch via the singleton dispatcher."""
    return get_dispatcher().fetch(url, **kwargs)


__all__ = [
    "ALLOWED_SCHEMES",
    "SSRFPolicy",
    "SSRFViolation",
    "resolve_vetted_addresses",
    "NetworkDispatcher",
    "FetchResult",
    "get_dispatcher",
    "reset_dispatcher",
    "fetch",
]
