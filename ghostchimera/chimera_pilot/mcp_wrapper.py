"""Universal MCP tool wrapper for Ghost Chimera.

Patterns adapted from Hermes-Agent's MCP tool system (Nous Research, MIT licensed).
Wires the chimeralang-mcp server (and any MCP server) as Ghost Chimera tool backends
so the agent can call MCP tools as part of its tool-calling loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from ..logging_config import get_logger

logger = get_logger("mcp_wrapper")

# ---------------------------------------------------------------------------
# MCP server connection
# ---------------------------------------------------------------------------

@dataclass
class MCPClient:
    """Connection to a single MCP server (stdio transport)."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 120.0
    connect_timeout: float = 60.0
    tools: list[dict] = field(default_factory=list)
    available: bool = False
    _process: subprocess.Popen | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @contextmanager
    def connect(self):
        """Start MCP server subprocess and discover tools."""
        env = {**self.env, **{k: v for k, v in {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "PYTHONPATH": str(Path(__file__).resolve().parent.parent.parent),
        }.items() if v}}
        try:
            self._process = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
            )
            # Discover tools via MCP protocol
            self._discover_tools()
            self.available = True
            yield self
        finally:
            self.shutdown()

    def _discover_tools(self) -> None:
        """Send MCP 'tools/list' request to discover available tools."""
        if not self._process or not self._process.stdin:
            return
        try:
            request = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ghost-chimera", "version": "0.2.0"},
                },
            })
            self._process.stdin.write(request + "\n")
            self._process.stdin.flush()
            response = self._process.stdout.readline()
            if response:
                resp = json.loads(response.strip())
                # Check for initialized response
                if resp.get("method") == "notifications/initialized":
                    # Now request tools
                    tools_req = json.dumps({
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    })
                    self._process.stdin.write(tools_req + "\n")
                    self._process.stdin.flush()
                    tools_resp = self._process.stdout.readline()
                    if tools_resp:
                        tools_data = json.loads(tools_resp.strip())
                        if "result" in tools_data:
                            for tool in tools_data["result"].get("tools", []):
                                self.tools.append({
                                    "name": tool["name"],
                                    "description": tool.get("description", ""),
                                    "inputSchema": tool.get("inputSchema", {}),
                                })
                logger.info("Discovered %d tools from MCP server %s", len(self.tools), self.name)
        except Exception as exc:
            logger.warning("Failed to discover tools from %s: %s", self.name, exc)

    def shutdown(self):
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
        self.available = False

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on this MCP server via stdio."""
        if not self.available or not self._process or not self._process.stdin:
            return {"status": "error", "content": f"Server {self.name} not connected"}

        request_id = int(time.time() * 1000)
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        })
        try:
            self._process.stdin.write(request + "\n")
            self._process.stdin.flush()
            response = self._process.stdout.readline()
            if response:
                resp = json.loads(response.strip())
                result = resp.get("result", {})
                return {
                    "status": "success",
                    "content": "",
                    "content_parts": [
                        part.get("text", "")
                        for part in result.get("content", [])
                        if isinstance(part, dict) and "text" in part
                    ],
                    "is_error": result.get("isError", False),
                }
        except Exception as exc:
            return {"status": "error", "content": str(exc)}

        return {"status": "error", "content": "No response from server"}

# ---------------------------------------------------------------------------
# MCP server registry
# ---------------------------------------------------------------------------

class MCPRegistry:
    """Manage multiple MCP server connections and their tools."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._lock = threading.RLock()
        self._all_tools: list[dict] = []

    def register(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> MCPClient:
        client = MCPClient(
            name=name,
            command=command,
            args=args or [],
            env=env or {},
            timeout=timeout,
        )
        with self._lock:
            self._clients[name] = client
        return client

    def get(self, name: str) -> MCPClient | None:
        return self._clients.get(name)

    def connected_tools(self) -> list[dict]:
        """Return all tools from all connected MCP servers."""
        tools = []
        for client in self._clients.values():
            if client.available:
                tools.extend(client.tools)
        return tools

    def find_tool(self, name: str) -> MCPClient | None:
        """Find which MCP server has a tool by name."""
        for name2, client in self._clients.items():
            if any(t["name"] == name for t in client.tools):
                return client
        return None

    def connect_all(self) -> None:
        """Connect to all registered MCP servers."""
        for client in self._clients.values():
            try:
                client.connect().__enter__()
            except Exception as exc:
                logger.warning("Failed to connect MCP server %s: %s", client.name, exc)

    def disconnect_all(self) -> None:
        """Disconnect all MCP servers."""
        for client in self._clients.values():
            client.shutdown()
        self._clients.clear()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool by name — auto-discovers which server hosts it."""
        client = self.find_tool(name)
        if client:
            return client.call_tool(name, arguments)

        # Check chimeralang-mcp by default
        chimera = self._clients.get("chimeralang")
        if chimera:
            return chimera.call_tool(name, arguments)

        return {"status": "error", "content": f"Tool {name} not found on any MCP server"}


# -----------------------------------------------------------------------
# Default registry with chimeralang-mcp pre-registered
# -----------------------------------------------------------------------

_default_registry: MCPRegistry | None = None
_registry_lock = threading.Lock()


def get_default_registry() -> MCPRegistry:
    """Get the singleton MCPRegistry with chimeralang-mcp pre-registered."""
    global _default_registry
    if _default_registry is None:
        with _registry_lock:
            if _default_registry is None:
                _default_registry = MCPRegistry()
                _default_registry.register(
                    "chimeralang",
                    command="python3",
                    args=["-m", "chimeralang_mcp.server", "--transport", "stdio"],
                    timeout=180,
                )
    return _default_registry


def register_mcp_server(
    name: str,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> MCPRegistry:
    """Register a new MCP server and return the registry."""
    registry = get_default_registry()
    registry.register(name, command, args=args, env=env, timeout=timeout)
    logger.info("Registered MCP server: %s (%s %s)", name, command, args)
    return registry


def connect_mcp_servers() -> None:
    """Connect to all registered MCP servers."""
    get_default_registry().connect_all()


def disconnect_mcp_servers() -> None:
    """Disconnect all MCP servers."""
    get_default_registry().disconnect_all()


def list_available_tools() -> list[dict]:
    """List all tools available across connected MCP servers."""
    return get_default_registry().connected_tools()


__all__ = [
    "MCPClient",
    "MCPRegistry",
    "get_default_registry",
    "register_mcp_server",
    "connect_mcp_servers",
    "disconnect_mcp_servers",
    "list_available_tools",
]
