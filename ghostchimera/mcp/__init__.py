"""MCP (Model Context Protocol) package.

Two clients live here:

- :mod:`ghostchimera.mcp.client` — GHOST's historical internal tool protocol
  over HTTP (action/discover/call on 127.0.0.1:3100). Kept for the Chimera
  Pilot MCP backend.
- :mod:`ghostchimera.mcp.mcp_protocol` — a real MCP JSON-RPC client
  (initialize → tools/list → tools/call) over streamable-HTTP and stdio
  transports, stdlib-only.
"""

from .mcp_protocol import (
    CLIENT_NAME,
    CLIENT_VERSION,
    MCP_PROTOCOL_VERSION,
    McpClient,
    McpError,
    StdioTransport,
    StreamableHttpTransport,
)

__all__ = [
    "CLIENT_NAME",
    "CLIENT_VERSION",
    "MCP_PROTOCOL_VERSION",
    "McpClient",
    "McpError",
    "StdioTransport",
    "StreamableHttpTransport",
]
