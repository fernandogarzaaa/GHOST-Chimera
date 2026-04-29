"""
Browser Tool
============

Provides a lightweight HTTP client for performing GET requests.  This is
intended for simple data retrieval; complex websites requiring JavaScript
should be handled by a headless browser integration in a dedicated module.
"""

from typing import Any
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError

from ..safety_layer.gating import ensure_authorized


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
    try:
        with urllib_request.urlopen(url, timeout=15) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as e:
        raise ValueError(f"HTTP error {e.code} while fetching {url}: {e.reason}")
    except URLError as e:
        raise ValueError(f"Failed to fetch {url}: {e.reason}")
