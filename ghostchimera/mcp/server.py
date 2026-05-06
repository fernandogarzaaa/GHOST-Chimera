"""MCP (Model Context Protocol) server implementation."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

logger = logging.getLogger(__name__)


class MCPTool:
    """Represents a single MCP tool."""

    def __init__(self, name: str, description: str, handler: Callable) -> None:
        self.name = name
        self.description = description
        self.handler = handler

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}


class MCPServer:
    """MCP server that exposes tools via HTTP."""

    def __init__(self, host: str = "127.0.0.1", port: int = 3100) -> None:
        self.host = host
        self.port = port
        self._tools: dict[str, MCPTool] = {}
        self._server: HTTPServer | None = None
        self._running = False

    def register_tool(self, name: str, description: str, handler: Callable) -> None:
        self._tools[name] = MCPTool(name=name, description=description, handler=handler)
        logger.info("Registered MCP tool: %s", name)

    def discover_tools(self) -> list[dict[str, Any]]:
        return [tool.to_dict() for tool in self._tools.values()]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = self._tools.get(name)
        if not tool:
            raise KeyError(f"Unknown tool: {name}")
        result = tool.handler(arguments or {})
        return {"name": name, "result": result}

    def _run_server(self) -> None:
        server = self._server
        if server is None:
            return
        try:
            server.serve_forever()
        except Exception as exc:
            logger.warning("MCP server loop stopped unexpectedly: %s", exc)

    def start(self) -> None:
        if self._running:
            return
        handler = _MCPRequestHandler(self)
        self._server = HTTPServer((self.host, self.port), handler)
        self._running = True
        threading.Thread(target=self._run_server, daemon=True).start()
        logger.info("MCP server started on %s:%d", self.host, self.port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._running = False
        logger.info("MCP server stopped")


class _MCPRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for MCP protocol requests."""

    def do_POST(self) -> None:  # type: ignore[override]
        server = self.server  # type: ignore[assignment]
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        action = body.get("action", "")

        if action == "discover":
            tools = server.discover_tools()  # type: ignore[attr-defined]
            response = json.dumps({"tools": tools})
        elif action == "call":
            name = body.get("name", "")
            args = body.get("arguments", {})
            result = server.call_tool(name, args)  # type: ignore[attr-defined]
            response = json.dumps(result)
        else:
            response = json.dumps({"error": f"Unknown action: {action}"})

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response.encode("utf-8"))

    def log_message(self, format, *args: Any) -> None:  # noqa: A002
        logger.debug(format, *args)
