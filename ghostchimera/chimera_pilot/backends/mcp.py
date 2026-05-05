"""MCP backend for Chimera Pilot."""

from __future__ import annotations

from typing import Any

from ghostchimera.mcp.client import MCPClient

from ..backends.base import BackendHealth, ExecutionResult
from ..task_ir import TaskSpec


class MCPBackend:
    """Execute tasks through an MCP server."""

    id = "mcp.remote"
    name = "MCP Remote Backend"
    _description = "Remote MCP server backend"

    def __init__(self, host: str = "127.0.0.1", port: int = 3100) -> None:
        self.host = host
        self.port = port
        self._client = MCPClient(host, port)
        self._tools: list[dict[str, Any]] = []
        self._available = False
        self._probe_once()

    def _probe_once(self) -> None:
        self._available = self._client.connect()
        self._tools = self._client.discover_tools()

    def probe(self) -> BackendHealth:
        self._probe_once()
        return BackendHealth(
            available=self._available,
            reliability=0.80 if self._available else 0.0,
            latency_ms=50,
            estimated_cost_usd=0.0,
        )

    def can_run(self, task: TaskSpec) -> bool:
        return self._available and len(self._tools) > 0

    def estimate(self, task: TaskSpec) -> BackendHealth:
        return self.probe()

    def execute(self, task: TaskSpec) -> ExecutionResult:
        if not self._available:
            return ExecutionResult(self.id, task.id, False, "", "MCP server unavailable", {})
        if not self._tools:
            return ExecutionResult(self.id, task.id, False, "", "No tools available", {})
        tool_name = self._tools[0]["name"] if self._tools else None
        if not tool_name:
            return ExecutionResult(self.id, task.id, False, "", "No tools available", {})
        try:
            result = self._client.call_tool(tool_name, task.inputs or {})
            return ExecutionResult(self.id, task.id, True, str(result.get("result", "")), None, {"tool": tool_name})
        except Exception as exc:
            return ExecutionResult(self.id, task.id, False, "", str(exc), {})


