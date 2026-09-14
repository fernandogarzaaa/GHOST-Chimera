"""Free private web search through a local SearXNG instance.

SearXNG aggregates public search engines without accounts or API keys, so it
is Ghost's no-cost research backend: point it at a locally provisioned
instance (Astro-style) and queries never leave your control. Result content
is fenced as untrusted web data before any model or UI consumes it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..stealth.untrusted import fence_content

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
RESULT_CONTENT_CHARS = 800


class SearXNGClient:
    """Minimal client for the SearXNG JSON API."""

    def __init__(self, base_url: str | None = None, *, timeout: float = 10.0) -> None:
        configured = (base_url or os.environ.get("GHOSTCHIMERA_SEARXNG_URL", "")).strip()
        self.base_url = configured or DEFAULT_BASE_URL
        self.timeout = max(1.0, timeout)

    def _get_json(self, path: str, params: dict[str, str]) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ghostchimera/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"SearXNG request failed (HTTP {exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"SearXNG unreachable at {self.base_url}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Endpoint at {self.base_url} did not return SearXNG JSON") from exc

    def available(self) -> bool:
        """Return True when any HTTP response arrives from the instance."""

        try:
            urllib.request.urlopen(self.base_url.rstrip("/") + "/", timeout=3.0).close()
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        """Operator-facing availability snapshot (no network on failure)."""

        return {"available": self.available(), "base_url": self.base_url}

    def search(
        self,
        query: str,
        *,
        categories: str = "general",
        language: str = "en",
        max_results: int = 8,
        safesearch: int = 1,
    ) -> list[dict[str, Any]]:
        """Search and return fenced results with title, URL, and snippet."""

        query = query.strip()
        if not query:
            return []
        payload = self._get_json(
            "/search",
            {
                "q": query,
                "format": "json",
                "categories": categories,
                "language": language,
                "safesearch": str(safesearch),
            },
        )
        raw = payload.get("results", []) if isinstance(payload, dict) else []
        results: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict) or len(results) >= max(1, max_results):
                continue
            url = str(item.get("url", ""))
            snippet = str(item.get("content", ""))[:RESULT_CONTENT_CHARS]
            results.append(
                {
                    "title": str(item.get("title", "")),
                    "url": url,
                    "engine": str(item.get("engine", "")),
                    "content": fence_content(
                        {"url": url, "snippet": snippet},
                        source="searxng",
                    ),
                }
            )
        return results

    def search_many(
        self, queries: list[str], *, max_results: int = 5, **kwargs: Any
    ) -> dict[str, list[dict[str, Any]]]:
        """Fan one research brief out across parallel queries."""

        return {query: self.search(query, max_results=max_results, **kwargs) for query in queries if query.strip()}


__all__ = ["DEFAULT_BASE_URL", "RESULT_CONTENT_CHARS", "SearXNGClient"]
