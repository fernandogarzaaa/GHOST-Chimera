"""Gateway server — WebSocket persistent sessions + HTTP route registry.

Patterns adapted from Hermes-Agent's messaging gateway (Nous Research, MIT licensed).
Provides a WebSocket server with persistent sessions, real-time tool output streaming,
remote agent management, and an HTTP route registry (Gap 6 — mirrors OpenClaw's
``registerHttpRoute`` contract).
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from ..chimera_pilot.agent_loop import AIAgent, SessionState
from ..chimera_pilot.checkpoint import get_manager as get_checkpoint_manager
from ..chimera_pilot.credential_pool import get_pool
from ..chimera_pilot.toolsets import ToolsetManager
from ..config import GhostChimeraConfig
from ..logging_config import get_logger
from .service_registry import BackgroundService, ServiceHealth

logger = get_logger("gateway_server")

# ---------------------------------------------------------------------------
# Constants
# ------------------ ----------- -- ------ ------ -----------
HOST = os.environ.get("GHOSTCHIMERA_GATEWAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("GHOSTCHIMERA_GATEWAY_PORT", "8765"))
_default_http_port = str(int(os.environ.get("GHOSTCHIMERA_GATEWAY_PORT", "8765")) + 1)
HTTP_PORT = int(os.environ.get("GHOSTCHIMERA_HTTP_PORT", _default_http_port))
WS_MAX_MESSAGE_BYTES = int(os.environ.get("GHOSTCHIMERA_WS_MAX_MESSAGE", "10_000_000"))
WS_PING_INTERVAL = float(os.environ.get("GHOSTCHIMERA_WS_PING_INTERVAL", "20.0"))
WS_CLOSE_GRACE_PERIOD = float(os.environ.get("GHOSTCHIMERA_WS_CLOSE_GRACE", "5.0"))


# ---------------------------------------------------------------------------
# HTTP route registry  (Gap 6)
# ---------------------------------------------------------------------------

RouteHandler = Callable[[dict[str, Any]], Any]
"""A callable ``(request_context) → response_dict``."""


@dataclass(frozen=True)
class HttpResponse:
    """Raw HTTP response for non-JSON gateway routes."""

    body: str | bytes
    status: int = 200
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)

    def body_bytes(self) -> bytes:
        if isinstance(self.body, bytes):
            return self.body
        return self.body.encode("utf-8")


@dataclass(frozen=True)
class HttpRoute:
    """A registered HTTP route.

    Parameters
    ----------
    path:
        URL path (exact match or prefix when ``prefix=True``).
    handler:
        Callable ``(request_context) → dict`` where ``request_context``
        contains ``method``, ``path``, ``headers``, ``body``, ``query``.
    method:
        HTTP method (e.g. ``"GET"``).  ``"*"`` matches any method.
    auth:
        Auth mode: ``"gateway"`` (require gateway token),
        ``"open"`` (no auth required), ``"token"`` (custom token from
        ``X-Gateway-Token`` header).
    prefix:
        When True, match any path that starts with ``path``.
    """

    path: str
    handler: RouteHandler
    method: str = "*"
    auth: str = "gateway"
    prefix: bool = False
    description: str = ""
    token: str = ""

    def matches(self, method: str, req_path: str) -> bool:
        if self.method != "*" and self.method.upper() != method.upper():
            return False
        if self.prefix:
            return req_path.startswith(self.path)
        return req_path == self.path


class HttpRouteRegistry:
    """Thread-safe registry of :class:`HttpRoute` entries."""

    def __init__(self) -> None:
        self._routes: list[HttpRoute] = []
        self._lock = threading.Lock()
        self._gateway_token: str = os.environ.get("GHOSTCHIMERA_GATEWAY_TOKEN", "")

    def register(
        self,
        path: str,
        handler: RouteHandler,
        *,
        method: str = "*",
        auth: str = "open",
        prefix: bool = False,
        description: str = "",
        token: str = "",
    ) -> None:
        """Register a route.

        Parameters
        ----------
        path:
            URL path.
        handler:
            Route handler callable.
        method:
            HTTP method filter.
        auth:
            Auth mode (``"gateway"``, ``"open"``, ``"token"``).
        prefix:
            Whether to do prefix matching.
        description:
            Human-readable description.
        token:
            Expected secret for ``auth="token"`` routes.  The value is
            compared against the ``X-Gateway-Token`` request header.  A
            route registered with ``auth="token"`` but no *token* will
            always reject requests.
        """
        route = HttpRoute(path=path, handler=handler, method=method,
                          auth=auth, prefix=prefix, description=description,
                          token=token)
        with self._lock:
            self._routes.append(route)
        logger.debug("Registered HTTP route %s %s (auth=%s)", method, path, auth)

    def find(self, method: str, path: str) -> HttpRoute | None:
        with self._lock:
            for route in self._routes:
                if route.matches(method, path):
                    return route
        return None

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"path": r.path, "method": r.method, "auth": r.auth,
                 "prefix": r.prefix, "description": r.description}
                for r in self._routes
            ]

    def check_auth(self, route: HttpRoute, headers: dict[str, str]) -> bool:
        """Return True when the request is authorised for *route*."""
        if route.auth == "open":
            return True
        token_header = headers.get("x-gateway-token", "").strip()
        if route.auth == "gateway":
            return bool(self._gateway_token) and token_header == self._gateway_token
        if route.auth == "token":
            # Custom token — compare against the route-specific expected value using
            # constant-time comparison to prevent timing-based token extraction.
            # A route with no configured token always rejects requests.
            return bool(route.token) and bool(token_header) and secrets.compare_digest(token_header, route.token)
        return False

# ---------------------------------------------------------------------------
# Data types
# ------------ ----------- -- ------ ------ -----------

@dataclass(frozen=True)
class GatewayMessage:
    """Message sent over the WebSocket gateway."""
    type: str  # "text" | "tool_output" | "error" | "status" | "ping" | "pong" | "checkpoint"
    session_id: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    sender: str = "server"

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "session_id": self.session_id,
            "data": self.data,
            "timestamp": self.timestamp,
            "sender": self.sender,
        })

    @classmethod
    def from_json(cls, raw: str) -> GatewayMessage:
        data = json.loads(raw)
        return cls(
            type=data["type"],
            session_id=data["session_id"],
            data=data.get("data", {}),
            timestamp=data.get("timestamp", time.time()),
            sender=data.get("sender", "client"),
        )


@dataclass
class GatewaySession:
    """A persistent WebSocket session with an agent."""
    session_id: str
    agent: AIAgent
    credential_pool: Any = None
    toolset_manager: ToolsetManager | None = None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    message_count: int = 0
    is_connected: bool = False
    pending_checkpoints: int = 0

    def touch(self) -> None:
        self.last_active = time.time()
        self.message_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "message_count": self.message_count,
            "is_connected": self.is_connected,
            "agent_status": self.agent.status() if self.agent else {},
        }


# ---------------------------------------------------------------------------
# Gateway server
# ------------ ----------- -- ------ ------ -----------

class GatewayServer(BackgroundService):
    """WebSocket server with persistent agent sessions and HTTP route registry.

    Implements :class:`~ghostchimera.chimera_pilot.service_registry.BackgroundService`.
    """

    service_id = "gateway_server"
    service_name = "Gateway Server"
    service_description = "WebSocket persistent sessions + HTTP route registry"

    def __init__(
        self,
        host: str = HOST,
        port: int = PORT,
        config: GhostChimeraConfig | None = None,
        http_port: int | None = None,
    ):
        self.host = host
        self.port = port
        self.http_port = http_port if http_port is not None else HTTP_PORT
        self.config = config or GhostChimeraConfig.from_env()
        self._sessions: dict[str, GatewaySession] = {}
        self._lock = threading.RLock()
        self._websocket_server = None
        self._http_server: HTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._running = False
        self._credentials = get_pool()
        self._toolset_manager = ToolsetManager()
        self._checkpoints = get_checkpoint_manager(self.config)
        self.routes = HttpRouteRegistry()
        self._register_builtin_routes()

    def _register_builtin_routes(self) -> None:
        """Register built-in HTTP routes."""
        self.routes.register("/health", self._handle_health, method="GET", auth="open",
                             description="Health check endpoint")
        self.routes.register("/status", self._handle_status, method="GET", auth="open",
                             description="Gateway status")
        self.routes.register("/sessions", self._handle_list_sessions, method="GET", auth="gateway",
                             description="List active WebSocket sessions")

    def _handle_health(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "timestamp": time.time()}

    def _handle_status(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return self.status()

    def _handle_list_sessions(self, ctx: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            sessions = [s.to_dict() for s in self._sessions.values()]
        return {"sessions": sessions, "count": len(sessions)}

    def register_route(
        self,
        path: str,
        handler: RouteHandler,
        *,
        method: str = "*",
        auth: str = "open",
        prefix: bool = False,
        description: str = "",
    ) -> None:
        """Register a custom HTTP route.

        Parameters
        ----------
        path:
            URL path (e.g. ``"/my/endpoint"``).
        handler:
            Callable ``(request_context) → dict``.
        method:
            HTTP method filter (``"*"`` matches any).
        auth:
            Auth mode: ``"open"``, ``"gateway"``, ``"token"``.
        prefix:
            Enable prefix matching.
        description:
            Human-readable description.
        """
        self.routes.register(path, handler, method=method, auth=auth,
                             prefix=prefix, description=description)

    def create_session(self, session_id: str | None = None,
                      system_prompt: str = "") -> GatewaySession:
        """Create a new agent session."""
        import uuid
        session_id = session_id or f"ws-{uuid.uuid4().hex[:8]}"

        agent = AIAgent(
            system_prompt=system_prompt,
            config=self.config,
            session=SessionState(session_id=session_id, system_prompt=system_prompt),
        )
        session = GatewaySession(
            session_id=session_id,
            agent=agent,
            credential_pool=self._credentials,
            toolset_manager=self._toolset_manager,
        )
        with self._lock:
            self._sessions[session_id] = session
        logger.info("Created session %s", session_id)
        return session

    def get_session(self, session_id: str) -> GatewaySession | None:
        with self._lock:
            return self._sessions.get(session_id)

    async def handle_client(self, websocket, session_id: str) -> None:
        """Handle a single WebSocket client connection."""
        session = self.get_session(session_id)
        if not session:
            session = self.create_session(session_id)
            session.agent.session.system_prompt = "Ghost Chimera agent — created via WebSocket gateway"

        session.is_connected = True
        session.touch()

        try:
            async for raw in websocket:
                msg = GatewayMessage.from_json(raw)
                session.touch()

                if msg.type == "ping":
                    await websocket.send(GatewayMessage(
                        type="pong", session_id=session_id, data={"latency": time.time() - msg.timestamp},
                    ).to_json())
                    continue

                if msg.type == "text":
                    user_text = msg.data.get("message", "")
                    await self._handle_user_message(session, user_text, websocket)
                    continue

                if msg.type == "status":
                    await websocket.send(GatewayMessage(
                        type="status", session_id=session_id,
                        data=session.to_dict(),
                    ).to_json())
                    continue

                if msg.type == "checkpoint":
                    ckpt = self._checkpoints.create_checkpoint(
                        description=msg.data.get("description", ""),
                        agent=session.agent,
                    )
                    if ckpt:
                        await websocket.send(GatewayMessage(
                            type="checkpoint", session_id=session_id,
                            data=ckpt.to_dict(),
                        ).to_json())

        except Exception as exc:
            logger.warning("Client %s disconnected: %s", session_id, exc)
        finally:
            session.is_connected = False

    async def _handle_user_message(self, session: GatewaySession,
                                  message: str, websocket) -> None:
        """Process a user message and stream agent response."""
        session_id = session.session_id

        # Send tool_output start
        await websocket.send(GatewayMessage(
            type="tool_output", session_id=session_id,
            data={"phase": "processing", "message": "Running agent..."},
        ).to_json())

        try:
            result = session.agent.run(message)
            await websocket.send(GatewayMessage(
                type="text", session_id=session_id,
                data={"message": str(result)[:5000]},
            ).to_json())
        except Exception as exc:
            await websocket.send(GatewayMessage(
                type="error", session_id=session_id,
                data={"error": str(exc)},
            ).to_json())

    def start(self) -> None:
        """Start the WebSocket server and the HTTP route server."""
        self._running = True
        import asyncio

        async def _start_async():
            import websockets
            async with websockets.serve(
                self._handle_connection, self.host, self.port,
                ping_interval=WS_PING_INTERVAL,
                ping_timeout=WS_CLOSE_GRACE_PERIOD,
                max_size=WS_MAX_MESSAGE_BYTES,
            ) as server:
                self._websocket_server = server
                logger.info("Gateway server listening on ws://%s:%d", self.host, self.port)
                while self._running:
                    await asyncio.sleep(1)

        def _run():
            asyncio.run(_start_async())

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        # Start HTTP server on adjacent port
        self._start_http_server()

        logger.info("Gateway server starting on ws://%s:%d, http://%s:%d",
                    self.host, self.port, self.host, self.http_port)

    def _start_http_server(self) -> None:
        """Start a lightweight HTTP server for route registry."""
        registry = self.routes

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._dispatch("GET")

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b""
                self._dispatch("POST", body=body)

            def _dispatch(self, method: str, body: bytes = b"") -> None:
                import urllib.parse
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                query_str = parsed.query
                query: dict[str, str] = {}
                if query_str:
                    for part in query_str.split("&"):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            query[urllib.parse.unquote(k)] = urllib.parse.unquote(v)

                headers = {k.lower(): v for k, v in self.headers.items()}
                route = registry.find(method, path)

                if route is None:
                    self._respond(404, {"error": "Not found", "path": path})
                    return

                if not registry.check_auth(route, headers):
                    self._respond(401, {"error": "Unauthorized"})
                    return

                ctx = {
                    "method": method,
                    "path": path,
                    "headers": headers,
                    "body": body.decode("utf-8", errors="replace"),
                    "query": query,
                }
                try:
                    result = route.handler(ctx)
                    self._respond(200, result)
                except Exception as exc:
                    self._respond(500, {"error": str(exc)})

            def _respond(self, code: int, data: Any) -> None:
                if isinstance(data, HttpResponse):
                    body = data.body_bytes()
                    self.send_response(data.status)
                    self.send_header("Content-Type", data.content_type)
                    self.send_header("Content-Length", str(len(body)))
                    for name, value in data.headers.items():
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(body)
                    return

                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
                logger.debug("HTTP %s", fmt % args)

        try:
            self._http_server = HTTPServer((self.host, self.http_port), _Handler)
            self._http_thread = threading.Thread(
                target=self._http_server.serve_forever, daemon=True
            )
            self._http_thread.start()
            logger.info("HTTP route server listening on http://%s:%d", self.host, self.http_port)
        except OSError as exc:
            logger.warning("Could not start HTTP route server on port %d: %s", self.http_port, exc)

    async def _handle_connection(self, websocket, path) -> None:
        """Handle incoming WebSocket connection — create or resume session."""
        import uuid
        session_id = f"ws-{uuid.uuid4().hex[:8]}"
        await self.handle_client(websocket, session_id)

    def stop(self) -> None:
        """Stop the gateway server (WebSocket + HTTP)."""
        self._running = False
        if self._websocket_server:
            self._websocket_server.close()
        if self._http_server:
            self._http_server.shutdown()
        logger.info("Gateway server stopped")

    def probe(self) -> ServiceHealth:
        """Return the health of the gateway server."""
        with self._lock:
            session_count = len(self._sessions)
        return ServiceHealth(
            ok=self._running,
            state="running" if self._running else "stopped",
            details={
                "session_count": session_count,
                "ws_port": self.port,
                "http_port": self.http_port,
            },
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            sessions = [s.to_dict() for s in self._sessions.values()]
        return {
            "host": self.host,
            "port": self.port,
            "http_port": self.http_port,
            "running": self._running,
            "session_count": len(sessions),
            "sessions": sessions,
            "routes": self.routes.list_all(),
        }


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_server: GatewayServer | None = None
_server_lock = threading.Lock()


def get_server(config: GhostChimeraConfig | None = None) -> GatewayServer:
    """Get the singleton gateway server."""
    global _server
    if _server is None:
        with _server_lock:
            if _server is None:
                _server = GatewayServer(config=config)
    return _server


def start_gateway(host: str = HOST, port: int = PORT) -> GatewayServer:
    """Quick-start the gateway."""
    server = get_server()
    server.host = host
    server.port = port
    server.start()
    return server


def stop_gateway() -> None:
    get_server().stop()


__all__ = [
    "GatewayServer",
    "GatewayMessage",
    "GatewaySession",
    "HttpResponse",
    "HttpRoute",
    "HttpRouteRegistry",
    "get_server",
    "start_gateway",
    "stop_gateway",
]
