"""MCP (Model Context Protocol) client implementation."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    """Connects to an MCP server and discovers/calls tools."""

    def __init__(self, host: str = "127.0.0.1", port: int = 3100) -> None:
        self.host = host
        self.port = port
        self._tools: list[dict[str, Any]] = []

    def _request(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        import urllib.request

        url = f"http://{self.host}:{self.port}/"
        body = json.dumps({"action": action, **(payload or {})}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def connect(self, url: str | None = None) -> bool:
        try:
            result = self._request("discover")
            self._tools = result.get("tools", [])
            return True
        except Exception as exc:
            logger.warning("MCP connect failed: %s", exc)
            return False

    def discover_tools(self) -> list[dict[str, Any]]:
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._tools:
            self.connect()
        result = self._request("call", {"name": name, "arguments": arguments})
        return result
