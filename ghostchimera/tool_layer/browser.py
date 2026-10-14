"""
Browser Tool
============

Provides a lightweight HTTP client for performing GET requests.  This is
intended for simple data retrieval; complex websites requiring JavaScript
should be handled by a headless browser integration in a dedicated module.

All requests are enforced to use HTTPS with explicit SSL context validation.
Non-HTTPS and dangerous schemes (file://, data:, javascript:) are rejected.
Every fetch, and every redirect it follows, goes through the SSRF guard
(:mod:`ghostchimera.safety_layer.ssrf`): private, loopback, link-local
(cloud metadata), unspecified and reserved addresses are refused, including
hostnames that resolve to them.
"""

from email.message import Message
from typing import Any

from ..http_identity import USER_AGENT, ensure_user_agent
from ..logging_config import get_logger
from ..safety_layer.gating import ensure_authorized
from ..safety_layer.ssrf import NetworkDispatcher, SSRFPolicy, SSRFViolation

logger = get_logger("browser")

_USER_AGENT = "GhostChimera/0.2.0"


def _browser_dispatcher() -> NetworkDispatcher:
    # Public internet is allowed (this is a general fetch tool), internal
    # address space never is. A fresh policy per call keeps it immune to
    # allow_all/allow_host changes made on the shared singleton elsewhere.
    return NetworkDispatcher(SSRFPolicy(default_allow=True, block_private_ranges=True))


def _charset(headers: dict[str, str]) -> str:
    content_type = headers.get("content-type", "")
    if not content_type:
        return "utf-8"
    msg = Message()
    msg["content-type"] = content_type
    return msg.get_content_charset() or "utf-8"


def http_get(url: str, policy: dict[str, Any] | None = None) -> str:
    """Fetch the contents of a URL.

    Parameters
    ----------
    url: str
        The URL to fetch.

    Returns
    -------
    str
        The body of the response as a string.  Raises ``ValueError`` on error,
        including when the SSRF guard blocks the URL or a redirect.
    """
    ensure_authorized(policy)
    # Enforce HTTPS-only scheme
    if not url.startswith("https://"):
        raise ValueError(f"Only HTTPS URLs are allowed; got: {url}")
    logger.debug("Fetching HTTPS URL: %s", url[:80])
    try:
        result = _browser_dispatcher().fetch(url, headers={"User-Agent": USER_AGENT}, timeout_seconds=15)
    except SSRFViolation as e:
        raise ValueError(f"Blocked by SSRF policy: {e}") from e
    if result.error or not result.ok:
        detail = result.error or f"HTTP {result.status_code}"
        raise ValueError(f"Failed to fetch {url}: {detail}")
    return result.body.decode(_charset(result.headers), errors="replace")
