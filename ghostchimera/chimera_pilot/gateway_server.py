"""Gateway server — WebSocket persistent sessions for agent orchestration.

Patterns adapted from Hermes-Agent's messaging gateway (Nous Research, MIT licensed).
Provides a WebSocket server with persistent sessions, real-time tool output streaming,
and remote agent management. Optional dependency (websockets).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import GhostChimeraConfig
from ..logging_config import get_logger
from ..chimera_pilot.agent_loop import AIAgent, SessionState
from ..chimera_pilot.credential_pool import get_pool
from ..chimera_pilot.toolsets import ToolsetManager
from ..chimera_pilot.subagent import SubagentPool
from ..chimera_pilot.batch_runner import BatchRunner
from ..chimera_pilot.checkpoint import get_manager as get_checkpoint_manager

logger = get_logger("gateway_server")

# ---------------------------------------------------------------------------
# Constants
# ------------------ ----------- -- ------ ------ -----------
HOST = os.environ.get("GHOSTCHIMERA_GATEWAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("GHOSTCHIMERA_GATEWAY_PORT", "8765"))
WS_MAX_MESSAGE_BYTES = int(os.environ.get("GHOSTCHIMERA_WS_MAX_MESSAGE", "10_000_000"))
WS_PING_INTERVAL = float(os.environ.get("GHOSTCHIMERA_WS_PING_INTERVAL", "20.0"))
WS_CLOSE_GRACE_PERIOD = float(os.environ.get("GHOSTCHIMERA_WS_CLOSE_GRACE", "5.0"))

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

class GatewayServer:
    """WebSocket server with persistent agent sessions."""

    def __init__(
        self,
        host: str = HOST,
        port: int = PORT,
        config: GhostChimeraConfig | None = None,
    ):
        self.host = host
        self.port = port
        self.config = config or GhostChimeraConfig.from_env()
        self._sessions: dict[str, GatewaySession] = {}
        self._lock = threading.RLock()
        self._websocket_server = None
        self._running = False
        self._credentials = get_pool()
        self._toolset_manager = ToolsetManager()
        self._checkpoints = get_checkpoint_manager(self.config)

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
        """Start the WebSocket server."""
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
        logger.info("Gateway server starting on ws://%s:%d", self.host, self.port)

    async def _handle_connection(self, websocket, path) -> None:
        """Handle incoming WebSocket connection — create or resume session."""
        import uuid
        session_id = f"ws-{uuid.uuid4().hex[:8]}"
        await self.handle_client(websocket, session_id)

    def stop(self) -> None:
        """Stop the gateway server."""
        self._running = False
        if self._websocket_server:
            self._websocket_server.close()
        logger.info("Gateway server stopped")

    def status(self) -> dict[str, Any]:
        with self._lock:
            sessions = [s.to_dict() for s in self._sessions.values()]
        return {
            "host": self.host,
            "port": self.port,
            "running": self._running,
            "session_count": len(sessions),
            "sessions": sessions,
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
    "get_server",
    "start_gateway",
    "stop_gateway",
]
