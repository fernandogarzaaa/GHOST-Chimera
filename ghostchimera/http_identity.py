"""One User-Agent for every outbound HTTP request Ghost Chimera makes.

Several upstreams reject requests without a ``User-Agent`` (Groq answers
HTTP 403, as do some CDNs in front of model catalogs), and Python's
``urllib`` default (``Python-urllib/3.x``) is blocked by others. Every
HTTP client in the package routes its request through
:func:`ensure_user_agent` so the header is always present and always
identifies the package version.

The helper never overrides a ``User-Agent`` a caller set on purpose (for
example a browser-style agent a specific site requires).
"""

from __future__ import annotations

import ssl
from typing import Any
from urllib import request as urllib_request

from . import __version__

USER_AGENT: str = f"GHOST-Chimera/{__version__}"

__all__ = ["USER_AGENT", "ensure_user_agent", "with_user_agent", "shared_ssl_context"]


# One TLS context for the whole process, built at import time on the main
# thread. ssl.create_default_context() loads the system CA bundle through
# OpenSSL, which segfaults when called concurrently from background threads
# (observed as SIGSEGV inside ssl.load_default_certs on Python 3.13).
# Building it once here keeps all cert loading off every worker thread.
# The context is never mutated after creation; sharing it across threads
# for opening connections is safe.
_TLS_CONTEXT: ssl.SSLContext | None = None


def shared_ssl_context() -> ssl.SSLContext:
    """Return the process-wide TLS context for outbound HTTPS.

    Every background thread doing HTTPS must use this instead of calling
    ``ssl.create_default_context()`` itself.
    """
    global _TLS_CONTEXT
    if _TLS_CONTEXT is None:
        _TLS_CONTEXT = ssl.create_default_context()
    return _TLS_CONTEXT


# Eagerly build it at import so even the first background thread reuses it.
shared_ssl_context()


def with_user_agent(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``headers`` that carries a User-Agent.

    An existing User-Agent (any capitalization) is kept as-is.
    """
    merged: dict[str, str] = dict(headers or {})
    if not any(key.lower() == "user-agent" for key in merged):
        merged["User-Agent"] = USER_AGENT
    return merged


def ensure_user_agent(req: Any) -> Any:
    """Make sure ``req`` sends a User-Agent, then return it.

    ``req`` may be a URL string (it is wrapped in a GET
    :class:`urllib.request.Request`) or a ``Request``. Anything else is
    returned untouched so test doubles keep working.
    """
    if isinstance(req, str):
        req = urllib_request.Request(req)
    if isinstance(req, urllib_request.Request) and not req.has_header("User-agent"):
        # urllib stores header names via str.capitalize(): "User-agent".
        req.add_header("User-Agent", USER_AGENT)
    return req
