"""
Browser Tool
============

Provides a lightweight HTTP client for performing GET requests.  This is
intended for simple data retrieval; complex websites requiring JavaScript
should be handled by a headless browser integration in a dedicated module.

All requests are enforced to use HTTPS with explicit SSL context validation.
Non-HTTPS and dangerous schemes (file://, data:, javascript:) are rejected.
"""

import ssl
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from ..logging_config import get_logger
from ..safety_layer.gating import ensure_authorized

logger = get_logger("browser")


def http_get(url: str, policy: dict[str, Any] | None = None) -> str:
    """Fetch the contents of a URL.

    Parameters
    ----------
    url: str
        The URL to fetch.

    Returns
    -------
    str
        The body of the response as a string.  Raises ``ValueError`` on error.
    """
    ensure_authorized(policy)
    # Enforce HTTPS-only scheme
    if not url.startswith("https://"):
        raise ValueError(f"Only HTTPS URLs are allowed; got: {url}")
    logger.debug("Fetching HTTPS URL: %s", url[:80])
    context = ssl.create_default_context()
    req = urllib_request.Request(url, headers={"User-Agent": "GhostChimera/0.2.0"})
    try:
        with urllib_request.urlopen(req, context=context, timeout=15) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as e:
        raise ValueError(f"HTTP error {e.code} while fetching {url}: {e.reason}")
    except URLError as e:
        raise ValueError(f"Failed to fetch {url}: {e.reason}")
