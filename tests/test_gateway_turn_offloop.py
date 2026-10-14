"""The gateway runs agent turns off the event loop (audit2 codeaudit F12)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

from ghostchimera.chimera_pilot.gateway_server import GatewayServer


class _SlowAgent:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def run(self, message: str) -> str:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self._lock:
            self.active -= 1
        return f"echo:{message}"


class _WS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))


def test_agent_turn_does_not_block_the_event_loop(monkeypatch) -> None:
    server = GatewayServer()
    monkeypatch.setattr(server, "_persist_session", lambda session: None)
    agent = _SlowAgent(0.4)
    session = SimpleNamespace(session_id="s1", agent=agent)
    other = SimpleNamespace(session_id="s2", agent=_SlowAgent(0.4))

    async def scenario() -> tuple[int, float]:
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.02)
                ticks += 1

        started = time.perf_counter()
        await asyncio.gather(
            server._handle_user_message(session, "a", _WS()),
            server._handle_user_message(other, "b", _WS()),
            ticker(),
        )
        return ticks, time.perf_counter() - started

    ticks, elapsed = asyncio.run(scenario())
    assert ticks == 20
    # Two sessions ran concurrently, not back-to-back on the loop.
    assert elapsed < 0.75, elapsed


def test_turns_on_one_session_are_serialized(monkeypatch) -> None:
    server = GatewayServer()
    monkeypatch.setattr(server, "_persist_session", lambda session: None)
    agent = _SlowAgent(0.1)
    session = SimpleNamespace(session_id="s1", agent=agent)
    ws = _WS()

    async def scenario() -> None:
        await asyncio.gather(*(server._handle_user_message(session, str(i), ws) for i in range(3)))

    asyncio.run(scenario())
    assert agent.max_active == 1
    assert sorted(m["data"]["message"] for m in ws.sent if m["type"] == "text") == ["echo:0", "echo:1", "echo:2"]
