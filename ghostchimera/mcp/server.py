"""GHOST internal tool protocol server (custom HTTP, not standard MCP).

This module implements GHOST's internal "MCP"-named protocol: a simple HTTP
server on 127.0.0.1:3100 with action/discover/call endpoints. It is NOT the
standard Model Context Protocol (JSON-RPC over stdio/SSE). The "MCP" naming
is historical. For standard MCP compatibility, use the mcp CLI's trust and
approval management for external servers.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger(__name__)

_MAX_BODY_BYTES = 1_000_000


class MCPTool:
    """Represents a single MCP tool."""

    def __init__(self, name: str, description: str, handler: Callable) -> None:
        self.name = name
        self.description = description
        self.handler = handler

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}


class MCPServer:
    """GHOST internal tool server exposing tools via custom HTTP protocol.

    Uses action/discover/call endpoints (default 127.0.0.1:3100; ``port=0``
    picks a free port, readable from ``.port`` after ``start()``). This is NOT
    the standard Model Context Protocol (JSON-RPC over stdio/SSE).

    ``call`` executes registered handlers, so every request must carry the
    server's token as ``Authorization: Bearer <token>`` or ``X-MCP-Token``.
    A random token is generated when none is given; read it from
    ``.auth_token``.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 3100, auth_token: str | None = None) -> None:
        self.host = host
        self.port = port
        self.auth_token = auth_token or secrets.token_urlsafe(32)
        self._tools: dict[str, MCPTool] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
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

    def is_authorized(self, headers: Any) -> bool:
        supplied = str(headers.get("X-MCP-Token", "") or "")
        auth = str(headers.get("Authorization", "") or "")
        if not supplied and auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8"), self.auth_token.encode("utf-8"))

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
        # BaseHTTPRequestHandler is instantiated by the HTTP server per request
        # with (request, client_address, server); pass a class bound to this
        # MCPServer, not an instance (that raised TypeError on every start()).
        self._server = ThreadingHTTPServer((self.host, self.port), _handler_for(self))
        self._server.daemon_threads = True
        self.port = int(self._server.server_address[1])
        self._running = True
        self._thread = threading.Thread(target=self._run_server, name="ghost-mcp-server", daemon=True)
        self._thread.start()
        logger.info("MCP server started on %s:%d", self.host, self.port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._running = False
        logger.info("MCP server stopped")


def _handler_for(mcp_server: MCPServer) -> type[BaseHTTPRequestHandler]:
    class _BoundHandler(_MCPRequestHandler):
        mcp = mcp_server

    return _BoundHandler


class _MCPRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for MCP protocol requests."""

    mcp: MCPServer

    def _reply(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        if not self.mcp.is_authorized(self.headers):
            self._reply(401, {"error": "unauthorized"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > _MAX_BODY_BYTES:
            self._reply(413 if content_length > 0 else 400, {"error": "invalid Content-Length"})
            return
        try:
            body = json.loads(self.rfile.read(content_length)) if content_length else {}
        except (ValueError, UnicodeDecodeError):
            self._reply(400, {"error": "body must be JSON"})
            return
        if not isinstance(body, dict):
            self._reply(400, {"error": "body must be a JSON object"})
            return
        action = body.get("action", "")

        if action == "discover":
            self._reply(200, {"tools": self.mcp.discover_tools()})
            return
        if action == "call":
            name = str(body.get("name", "") or "")
            args = body.get("arguments") or {}
            if not isinstance(args, dict):
                self._reply(400, {"error": "arguments must be an object"})
                return
            try:
                self._reply(200, self.mcp.call_tool(name, args))
            except KeyError:
                self._reply(404, {"error": f"Unknown tool: {name}"})
            except Exception as exc:  # noqa: BLE001 - a failing tool must not kill the server thread
                logger.warning("MCP tool %s failed: %s", name, exc)
                self._reply(500, {"error": f"tool {name} failed: {type(exc).__name__}"})
            return
        self._reply(400, {"error": f"Unknown action: {action}"})

    def log_message(self, format, *args: Any) -> None:  # noqa: A002
        logger.debug(format, *args)
