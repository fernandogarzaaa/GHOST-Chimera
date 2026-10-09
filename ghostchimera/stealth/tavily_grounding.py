"""Tavily web grounding for the Stealth Loop UNDERSTAND phase.

When the loop observes an event that references the outside world (an
explicit ``ground_with_web`` payload flag, or a research/news-style event),
this capability fetches fresh web context so cloud reasoning — and the
loop's trace — is grounded in current facts instead of stale memory.

Transport priority (first available wins in ``auto`` mode):

1. **Remote Tavily MCP server** (``https://mcp.tavily.com/mcp``) over
   streamable HTTP, using the ``tavily-search`` / ``tavily-extract`` tools.
2. **Local Tavily MCP server** over stdio (``npx -y tavily-mcp`` with
   ``TAVILY_API_KEY`` in its environment).
3. **Direct Tavily REST API** (``POST https://api.tavily.com/search`` with
   ``Authorization: Bearer`` header-only auth) — the final fallback.

Credential reality (2026-09-28): the MCP transports need a Tavily key that
Tavily itself accepts. The connected ``custom.tavily`` dynamic credential
is authorized for ``api.tavily.com`` with ``bearer_header`` placement, so
the REST path works with the surrogate (swapped at egress). It is NOT
authorized for ``mcp.tavily.com``: sending the surrogate there returns
``401 invalid_token`` because no swap happens. In ``auto`` mode the loop
therefore degrades remote MCP -> local MCP -> REST, and the transport that
actually served the request is exposed via ``last_transport`` (and in the
``ground_event`` payload) so callers never mistake a REST result for MCP.
REST uses header-only auth: ``api_key`` is never sent in the JSON body
because Tavily validates ``body.api_key`` before the Authorization header,
which 401s on an unswapped surrogate.

Configuration (environment):

- ``TAVILY_API_KEY`` — required; without it the capability reports
  ``available == False`` and every call degrades gracefully (loudly logged).
- ``TAVILY_MCP_MODE`` — ``auto`` (default), ``remote``, ``local``, or
  ``rest``. Explicit modes are strict (they raise on failure); ``auto``
  falls through the priority list.
- ``TAVILY_MCP_URL`` — override the remote MCP endpoint.
- ``TAVILY_MCP_COMMAND`` — override the local stdio command.

stdlib-only. No network traffic happens at import or construction time.
"""

from __future__ import annotations

import json
import os
import shlex
import ssl
from contextlib import suppress
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from ..logging_config import get_logger
from ..mcp.mcp_protocol import McpClient, McpError, StdioTransport, StreamableHttpTransport

logger = get_logger("tavily_grounding")

TAVILY_MCP_URL_DEFAULT = "https://mcp.tavily.com/mcp"
TAVILY_MCP_COMMAND_DEFAULT = "npx -y tavily-mcp"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

SEARCH_TOOL = "tavily-search"
EXTRACT_TOOL = "tavily-extract"

_GROUND_EVENT_TYPES = frozenset({"web_research", "news_digest", "research", "web"})


class TavilyError(RuntimeError):
    """Raised when a Tavily search/extract call fails."""


class TavilyGrounding:
    """Web grounding with MCP-first transports and a REST fallback."""

    def __init__(
        self,
        api_key: str | None = None,
        mode: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("TAVILY_API_KEY", "")
        self._mode = (mode or os.environ.get("TAVILY_MCP_MODE", "auto")).strip().lower()
        if self._mode not in ("auto", "remote", "local", "rest"):
            raise ValueError(f"Unknown TAVILY_MCP_MODE: {self._mode!r}")
        self._mcp_url = os.environ.get("TAVILY_MCP_URL", TAVILY_MCP_URL_DEFAULT)
        self._mcp_command = os.environ.get("TAVILY_MCP_COMMAND", TAVILY_MCP_COMMAND_DEFAULT)
        self._timeout = timeout
        self._remote: McpClient | None = None
        self._local: McpClient | None = None
        self._last_transport: str = ""

    # -- availability ------------------------------------------------------

    @property
    def available(self) -> bool:
        """True when a Tavily API key is configured."""
        return bool(self._api_key)

    @property
    def last_transport(self) -> str:
        """Transport used by the most recent search/extract call.

        One of ``mcp-remote``, ``mcp-local``, ``rest``, or ``""`` when no
        call has been made yet. Lets callers see exactly which transport
        served the request instead of assuming MCP-first.
        """
        return self._last_transport

    def _require_key(self) -> str:
        if not self._api_key:
            raise TavilyError("Tavily is not available; set TAVILY_API_KEY in the environment")
        return self._api_key

    # -- public API --------------------------------------------------------

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Web search; returns normalized ``[{title, url, snippet, score}]``.

        Traced to LangSmith when LANGSMITH_API_KEY is set; tracing never
        changes the result or the MCP-first/REST-fallback dispatch.
        """
        from ghostchimera.observability import get_default_tracer

        tracer = get_default_tracer()
        run = tracer.start_run(
            "tavily.search",
            run_type="tool",
            inputs={"query": query, "max_results": max_results, "mode": self._mode},
            metadata={"provider": "tavily"},
            tags=["ghost-chimera", "tavily"],
        )
        try:
            results = self._search_inner(query, max_results)
        except Exception as exc:
            tracer.end_run(run, error=f"{type(exc).__name__}: {exc}")
            raise
        tracer.end_run(
            run,
            outputs={
                "result_count": len(results),
                "transport": self._last_transport,
                "titles": [r.get("title", "") for r in results[:5]],
            },
        )
        return results

    def _search_inner(self, query: str, max_results: int) -> list[dict[str, Any]]:
        self._require_key()
        query = query.strip()
        if not query:
            raise TavilyError("Tavily search needs a non-empty query")
        if self._mode == "rest":
            return self._rest_search(query, max_results)
        if self._mode == "remote":
            return self._mcp_search(self._remote_client(), query, max_results, "mcp-remote")
        if self._mode == "local":
            return self._mcp_search(self._local_client(), query, max_results, "mcp-local")
        # auto: remote MCP -> local MCP -> REST
        try:
            return self._mcp_search(self._remote_client(), query, max_results, "mcp-remote")
        except McpError as exc:
            logger.info("Tavily remote MCP unavailable (%s); trying local MCP", exc)
        try:
            return self._mcp_search(self._local_client(), query, max_results, "mcp-local")
        except McpError as exc:
            logger.info("Tavily local MCP unavailable (%s); falling back to REST", exc)
        return self._rest_search(query, max_results)

    def extract(self, urls: list[str], query: str = "") -> list[dict[str, Any]]:
        """Extract page content; returns normalized ``[{url, content}]``.

        Traced to LangSmith when LANGSMITH_API_KEY is set; tracing never
        changes the result or the MCP-first/REST-fallback dispatch.
        """
        from ghostchimera.observability import get_default_tracer

        tracer = get_default_tracer()
        run = tracer.start_run(
            "tavily.extract",
            run_type="tool",
            inputs={"urls": urls, "query": query, "mode": self._mode},
            metadata={"provider": "tavily"},
            tags=["ghost-chimera", "tavily"],
        )
        try:
            results = self._extract_inner(urls, query)
        except Exception as exc:
            tracer.end_run(run, error=f"{type(exc).__name__}: {exc}")
            raise
        tracer.end_run(
            run,
            outputs={"result_count": len(results), "transport": self._last_transport},
        )
        return results

    def _extract_inner(self, urls: list[str], query: str) -> list[dict[str, Any]]:
        self._require_key()
        urls = [u for u in urls if u]
        if not urls:
            raise TavilyError("Tavily extract needs at least one URL")
        if self._mode == "rest":
            return self._rest_extract(urls, query)
        if self._mode == "remote":
            return self._mcp_extract(self._remote_client(), urls, query, "mcp-remote")
        if self._mode == "local":
            return self._mcp_extract(self._local_client(), urls, query, "mcp-local")
        try:
            return self._mcp_extract(self._remote_client(), urls, query, "mcp-remote")
        except McpError as exc:
            logger.info("Tavily remote MCP unavailable (%s); trying local MCP", exc)
        try:
            return self._mcp_extract(self._local_client(), urls, query, "mcp-local")
        except McpError as exc:
            logger.info("Tavily local MCP unavailable (%s); falling back to REST", exc)
        return self._rest_extract(urls, query)

    def ground_event(self, event: Any) -> dict[str, Any] | None:
        """Ground one Stealth Loop event in fresh web context (or None).

        Grounding fires when the event opts in (``payload["ground_with_web"]``
        truthy, optionally with ``payload["web_query"]``) or when the event
        type is research/news-like. Returns ``None`` when grounding does not
        apply or the key is absent — the loop treats that as "no web needed".
        """
        if not self.available:
            return None
        query = self._event_query(event)
        if query is None:
            return None
        results = self.search(query)
        return {
            "query": query,
            "results": results[:5],
            "transport": self._last_transport,
            "tool": SEARCH_TOOL,
        }

    def close(self) -> None:
        for client in (self._remote, self._local):
            if client is not None:
                with suppress(Exception):
                    client.close()
        self._remote = None
        self._local = None

    # -- event query building ----------------------------------------------

    @staticmethod
    def _event_query(event: Any) -> str | None:
        payload = getattr(event, "payload", None) or {}
        event_type = str(getattr(event, "event_type", ""))
        summary = str(
            payload.get("web_query")
            or payload.get("summary")
            or payload.get("text")
            or payload.get("description")
            or ""
        ).strip()
        if payload.get("ground_with_web"):
            query = str(payload.get("web_query") or f"{event_type}: {summary}").strip()
            return query[:300] or None
        if event_type in _GROUND_EVENT_TYPES and summary:
            return f"{event_type}: {summary[:280]}"
        return None

    # -- MCP path ----------------------------------------------------------

    def _remote_client(self) -> McpClient:
        if self._remote is None:
            key = self._require_key()
            transport = StreamableHttpTransport(
                self._mcp_url,
                headers={"Authorization": f"Bearer {key}"},
                timeout=self._timeout,
            )
            client = McpClient(transport)
            client.initialize()
            self._remote = client
            logger.info("Tavily remote MCP connected: %s", self._mcp_url)
        return self._remote

    def _local_client(self) -> McpClient:
        if self._local is None:
            key = self._require_key()
            command = shlex.split(self._mcp_command)
            transport = StdioTransport(command, env={"TAVILY_API_KEY": key}, timeout=self._timeout)
            if not transport.command_available:
                raise McpError(f"Local MCP command not found: {command[0]} (is node/npx installed?)")
            transport.start()
            client = McpClient(transport)
            try:
                client.initialize()
            except Exception:
                transport.close()
                raise
            self._local = client
            logger.info("Tavily local MCP connected: %s", self._mcp_command)
        return self._local

    @staticmethod
    def _tool_text(result: dict[str, Any]) -> str:
        content = result.get("content") or []
        texts = [
            str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(texts)

    def _mcp_search(self, client: McpClient, query: str, max_results: int, label: str) -> list[dict[str, Any]]:
        result = client.call_tool(
            SEARCH_TOOL,
            {"query": query, "max_results": max_results, "search_depth": "basic"},
        )
        payload = json.loads(self._tool_text(result) or "{}")
        results = payload.get("results") or []
        self._last_transport = label
        return [self._normalize_search_hit(hit) for hit in results if isinstance(hit, dict)]

    def _mcp_extract(self, client: McpClient, urls: list[str], query: str, label: str) -> list[dict[str, Any]]:
        args: dict[str, Any] = {"urls": urls, "extract_depth": "basic"}
        if query:
            args["query"] = query
        result = client.call_tool(EXTRACT_TOOL, args)
        payload = json.loads(self._tool_text(result) or "{}")
        results = payload.get("results") or []
        self._last_transport = label
        normalized = []
        for item in results:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "url": str(item.get("url", "")),
                    "content": str(item.get("raw_content") or item.get("content") or "")[:4000],
                }
            )
        return normalized

    @staticmethod
    def _normalize_search_hit(hit: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": str(hit.get("title", "")),
            "url": str(hit.get("url", "")),
            "snippet": str(hit.get("content") or hit.get("snippet") or "")[:500],
            "score": hit.get("score"),
        }

    # -- REST fallback -----------------------------------------------------

    def _rest_post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        key = self._require_key()
        data = json.dumps(body).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
            method="POST",
        )
        context = ssl.create_default_context()
        try:
            with urllib_request.urlopen(req, context=context, timeout=self._timeout) as resp:
                if resp.status != 200:
                    raise TavilyError(f"Tavily REST API returned HTTP {resp.status}")
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise TavilyError(f"Tavily REST API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise TavilyError(f"Tavily REST request failed: {exc.reason}") from exc

    def _rest_search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        # Header-only auth: Tavily validates body.api_key BEFORE the
        # Authorization header, so including api_key in the body 401s when
        # the key is a dynamic-credential surrogate (hsurr:*). The Bearer
        # header alone is the sanctioned shape (authd swaps the surrogate
        # at egress for api.tavily.com).
        payload = self._rest_post(
            TAVILY_SEARCH_URL,
            {
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
        )
        self._last_transport = "rest"
        results = payload.get("results") or []
        return [self._normalize_search_hit(hit) for hit in results if isinstance(hit, dict)]

    def _rest_extract(self, urls: list[str], query: str) -> list[dict[str, Any]]:
        # Header-only auth (see _rest_search): never send api_key in the body.
        body: dict[str, Any] = {"urls": urls}
        if query:
            body["query"] = query
        payload = self._rest_post(TAVILY_EXTRACT_URL, body)
        self._last_transport = "rest"
        results = payload.get("results") or []
        normalized = []
        for item in results:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "url": str(item.get("url", "")),
                    "content": str(item.get("raw_content") or item.get("content") or "")[:4000],
                }
            )
        return normalized


__all__ = ["TavilyError", "TavilyGrounding", "SEARCH_TOOL", "EXTRACT_TOOL"]
