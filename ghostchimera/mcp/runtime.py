"""Ghost MCP runtime entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .ghost_adapter import GhostMCPAdapter


def create_ghost_mcp(
    *,
    state_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    name: str = "Ghost Chimera MCP",
) -> FastMCP:
    """Create the stdio-first Ghost MCP server."""

    adapter = GhostMCPAdapter(state_dir=state_dir, config_path=config_path)
    server = FastMCP(
        name=name,
        instructions=(
            "Ghost Chimera compressed into a small MCP surface. "
            "Use the single `ghost` tool with an action payload to access Ghost capabilities."
        ),
    )

    @server.tool(
        name="ghost",
        description=(
            "Massive Ghost Chimera capability tool. "
            "Accepts an action payload such as run, status, memory, context, consent, bootstrap, teach, train, trust, workspace, or providers."
        ),
    )
    def ghost(action: str = "run", payload: dict | None = None) -> dict:
        return adapter.invoke({"action": action, **(payload or {})})

    return server


def main(argv: list[str] | None = None) -> int:
    """Run Ghost Chimera as an MCP server."""

    parser = argparse.ArgumentParser(description="Ghost Chimera MCP runtime")
    parser.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default="stdio")
    parser.add_argument("--state-dir", default="", help="Optional Ghost state directory.")
    parser.add_argument("--config-path", default="", help="Optional Ghost config.json path.")
    parser.add_argument("--name", default="Ghost Chimera MCP", help="Displayed MCP server name.")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host for non-stdio transports.")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port for non-stdio transports.")
    args = parser.parse_args(argv)

    server = create_ghost_mcp(
        state_dir=args.state_dir or None,
        config_path=args.config_path or None,
        name=args.name,
    )
    server.settings.host = args.host
    server.settings.port = args.port
    server.run(args.transport)
    return 0


__all__ = ["create_ghost_mcp", "main"]
