"""Minimal Model Context Protocol (MCP) client over stdlib transports.

The legacy :class:`~ghostchimera.mcp.client.MCPClient` speaks Ghost's own
HTTP bridge protocol (``{"action": "discover"}``). This module implements the
actual MCP JSON-RPC wire protocol — ``initialize`` → ``notifications/initialized``
→ ``tools/list`` → ``tools/call`` — so Ghost can talk to real MCP servers:

- **Streamable HTTP** servers, e.g. the Tavily remote MCP server at
  ``https://mcp.tavily.com/mcp`` (single POST endpoint, JSON or SSE
  responses, ``mcp-session-id`` tracking).
- **stdio** servers spawned locally, e.g. ``npx -y tavily-mcp``
  (newline-delimited JSON-RPC over the child process's stdio).

stdlib-only (``urllib`` + ``subprocess`` + ``json`` + ``threading``): no extra
dependencies, so the core test suite never requires an external service.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import ssl
import subprocess
import threading
import time
from contextlib import suppress
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from ..logging_config import get_logger

logger = get_logger("mcp_protocol")

MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "ghost-chimera"
CLIENT_VERSION = "0.4.0-beta"


class McpError(RuntimeError):
    """Raised when an MCP transport or protocol step fails."""


# ---------------------------------------------------------------------------
# Streamable HTTP transport
# ---------------------------------------------------------------------------


class StreamableHttpTransport:
    """POST JSON-RPC messages to an MCP streamable-HTTP endpoint.

    Handles both plain ``application/json`` responses and ``text/event-stream``
    (SSE) responses, and tracks the ``mcp-session-id`` header across requests.
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.session_id: str | None = None

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        headers.update(self.headers)
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        return headers

    def request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """POST one JSON-RPC message; return the parsed response (or None).

        Returns ``None`` for notifications (server answers ``202 Accepted``
        with no body). Raises :class:`McpError` on transport/HTTP failures.
        """
        body = json.dumps(message).encode("utf-8")
        req = urllib_request.Request(self.url, data=body, headers=self._request_headers(), method="POST")
        context = ssl.create_default_context()
        try:
            with urllib_request.urlopen(req, context=context, timeout=self.timeout) as resp:
                status = resp.status
                session_id = resp.headers.get("mcp-session-id")
                if session_id:
                    self.session_id = session_id
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read()
        except HTTPError as exc:
            detail = ""
            with suppress(Exception):
                detail = exc.read().decode("utf-8", "replace")[:500]
            raise McpError(f"MCP HTTP {exc.code} from {self.url}: {detail}") from exc
        except URLError as exc:
            raise McpError(f"MCP request to {self.url} failed: {exc.reason}") from exc

        if status == 202 or not raw:
            return None  # notification accepted, no response body
        if status != 200:
            raise McpError(f"MCP server returned HTTP {status} from {self.url}")

        if "text/event-stream" in content_type:
            return self._parse_sse(raw, message.get("id"))
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise McpError(f"MCP server returned non-JSON body: {raw[:200]!r}") from exc
        return parsed

    @staticmethod
    def _parse_sse(raw: bytes, want_id: Any) -> dict[str, Any]:
        """Extract the JSON-RPC response from an SSE event stream."""
        candidates: list[dict[str, Any]] = []
        for line in raw.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload in ("", "[DONE]"):
                continue
            try:
                obj = json.loads(payload)
            except ValueError:
                continue
            if isinstance(obj, dict) and "jsonrpc" in obj:
                candidates.append(obj)
        if not candidates:
            raise McpError("MCP SSE stream contained no JSON-RPC message")
        for obj in candidates:
            if obj.get("id") == want_id:
                return obj
        return candidates[-1]


# ---------------------------------------------------------------------------
# stdio transport
# ---------------------------------------------------------------------------


def _drain_stderr(proc: subprocess.Popen, sink: queue.Queue[str]) -> None:
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            with suppress(queue.Full):
                sink.put_nowait(line)
    except Exception:
        pass


class StdioTransport:
    """Speak newline-delimited JSON-RPC with a locally spawned MCP server.

    Example: ``StdioTransport(["npx", "-y", "tavily-mcp"], env={"TAVILY_API_KEY": key})``.
    """

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.command = list(command)
        self.env = env
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._inbox: queue.Queue[str] = queue.Queue()
        self._stderr_sink: queue.Queue[str] = queue.Queue(maxsize=100)
        self._reader: threading.Thread | None = None

    @property
    def command_available(self) -> bool:
        """True when the executable part of the command exists on PATH."""
        return shutil.which(self.command[0]) is not None

    def start(self) -> None:
        if self._proc is not None:
            return
        merged_env = dict(os.environ)
        if self.env:
            merged_env.update(self.env)
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=merged_env,
            )
        except (OSError, FileNotFoundError) as exc:
            raise McpError(f"Could not start MCP server {self.command!r}: {exc}") from exc
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        stderr_thread = threading.Thread(target=_drain_stderr, args=(self._proc, self._stderr_sink), daemon=True)
        stderr_thread.start()
        logger.debug("Started MCP stdio server: %s", " ".join(self.command))

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                self._inbox.put(line)
        except Exception:
            pass

    def request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Send one JSON-RPC message; return the matching response (or None).

        For notifications (no ``"id"``) the message is written and ``None``
        is returned without waiting.
        """
        if self._proc is None or self._proc.stdin is None:
            raise McpError("MCP stdio server is not started")
        if self._proc.poll() is not None:
            stderr_tail = ""
            while not self._stderr_sink.empty():
                stderr_tail = self._stderr_sink.get_nowait()
            raise McpError(f"MCP stdio server exited (code {self._proc.returncode}): {stderr_tail[-300:]}")
        self._proc.stdin.write(json.dumps(message) + "\n")
        self._proc.stdin.flush()
        msg_id = message.get("id")
        if msg_id is None:
            return None
        deadline = time.time() + self.timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise McpError(f"MCP stdio request timed out after {self.timeout}s: {message.get('method')}")
            try:
                line = self._inbox.get(timeout=remaining)
            except queue.Empty:
                raise McpError(f"MCP stdio request timed out after {self.timeout}s: {message.get('method')}") from None
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # skip non-JSON chatter on stdout
            if isinstance(obj, dict) and obj.get("id") == msg_id:
                return obj
            # Not our response (server notification/log) — keep waiting.

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            with suppress(Exception):
                proc.kill()


# ---------------------------------------------------------------------------
# MCP client (protocol layer)
# ---------------------------------------------------------------------------


class McpClient:
    """JSON-RPC MCP client over any transport with a ``request()`` method."""

    def __init__(self, transport: StreamableHttpTransport | StdioTransport) -> None:
        self.transport = transport
        self._next_id = 1
        self._server_info: dict[str, Any] = {}

    def _new_id(self) -> int:
        current = self._next_id
        self._next_id += 1
        return current

    def _send(
        self, method: str, params: dict[str, Any] | None = None, *, notification: bool = False
    ) -> dict[str, Any] | None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notification:
            message["id"] = self._new_id()
        if params is not None:
            message["params"] = params
        response = self.transport.request(message)
        if response is None:
            return None
        if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
            raise McpError(f"Malformed MCP response: {str(response)[:200]}")
        if "error" in response and response["error"] is not None:
            err = response["error"]
            raise McpError(f"MCP error {err.get('code')}: {err.get('message')}")
        return response.get("result")

    def initialize(self) -> dict[str, Any]:
        """Run the MCP handshake; returns the server's initialize result."""
        result = self._send(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        )
        if not isinstance(result, dict):
            raise McpError("MCP initialize returned no result")
        self._server_info = result
        server_version = result.get("protocolVersion")
        if server_version and server_version != MCP_PROTOCOL_VERSION:
            logger.debug("MCP server protocol version %s (client %s)", server_version, MCP_PROTOCOL_VERSION)
        self._send("notifications/initialized", notification=True)
        logger.debug("MCP handshake complete: %s", result.get("serverInfo", {}).get("name"))
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the server's tool list."""
        result = self._send("tools/list", {})
        if not isinstance(result, dict):
            raise McpError("MCP tools/list returned no result")
        tools = result.get("tools", [])
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a tool; returns the raw result object (raises on tool error)."""
        result = self._send("tools/call", {"name": name, "arguments": arguments or {}})
        if not isinstance(result, dict):
            raise McpError(f"MCP tools/call {name!r} returned no result")
        if result.get("isError"):
            content = result.get("content", [])
            detail = ""
            if content and isinstance(content, list):
                first = content[0]
                if isinstance(first, dict):
                    detail = str(first.get("text", ""))[:500]
            raise McpError(f"MCP tool {name!r} reported an error: {detail}")
        return result

    def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if callable(close):
            close()


__all__ = [
    "CLIENT_NAME",
    "CLIENT_VERSION",
    "MCP_PROTOCOL_VERSION",
    "McpClient",
    "McpError",
    "StdioTransport",
    "StreamableHttpTransport",
]
