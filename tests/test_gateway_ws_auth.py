"""WebSocket gateway: real-connection regression tests (no mocks).

P0 audit findings covered:
- handler must accept the modern one-argument API (websockets>=13 calls
  with the connection only) — a ping/pong exchange over a real socket.
- handshake authorization: a configured console token is required
  (query ?token=, Authorization Bearer, or X-Gateway-Token); wrong or
  missing tokens are rejected before any session exists; unconfigured
  servers keep the local default (open).
"""

from __future__ import annotations

import asyncio
import json
import socket
import unittest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer


def _claim_base(size: int = 4) -> int:
    import contextlib

    for base in (49401, 49501, 49601, 49701, 49801):
        holders = []
        try:
            for port in range(base, base + size):
                holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                holder.bind(("127.0.0.1", port))
                holder.listen(1)
                holders.append(holder)
        except OSError:
            for holder in holders:
                with contextlib.suppress(OSError):
                    holder.close()
            continue
        for holder in holders:
            with contextlib.suppress(OSError):
                holder.close()
        return base
    raise unittest.SkipTest("no free port block on this runner")


def _connect(port: int, path: str = "/", **kwargs):
    """websockets.connect tolerant of the additional/extra_headers rename."""
    import websockets

    try:
        return websockets.connect(f"ws://127.0.0.1:{port}{path}", **kwargs)
    except TypeError:
        if "additional_headers" in kwargs:
            kwargs["extra_headers"] = kwargs.pop("additional_headers")
            return websockets.connect(f"ws://127.0.0.1:{port}{path}", **kwargs)
        raise


async def _ping_once(port: int, **connect_kwargs) -> dict:
    async with _connect(port, "/", **connect_kwargs) as ws:
        await ws.send(json.dumps({"type": "ping", "session_id": "t", "timestamp": 0}))
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        return json.loads(raw)


def _run(coro):
    return asyncio.run(coro)


def _close_code(err: Exception) -> int | None:
    """Close code across websockets versions (Protocol.close_code vs legacy .code)."""
    for attr in ("close_code", "code"):
        try:
            with __import__("warnings").catch_warnings():
                __import__("warnings").simplefilter("ignore", DeprecationWarning)
                value = getattr(err, attr, None)
            if isinstance(value, int):
                return value
        except Exception:
            continue
    return None


class GatewayWebSocketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = _claim_base(4)
        cls._open_port = base
        cls._auth_port = base + 2
        cls._open_server = GatewayServer(host="127.0.0.1", port=base, http_port=base + 1)
        cls._open_server.start()  # blocks until both listeners are confirmed live
        cls._auth_server = GatewayServer(host="127.0.0.1", port=base + 2, http_port=base + 3, auth_token="secret-123")
        cls._auth_server.start()
        cls.addClassCleanup(cls._open_server.stop)
        cls.addClassCleanup(cls._auth_server.stop)

    def test_ping_pong_over_real_socket(self) -> None:
        """Modern handler API: one-arg call must serve a full exchange."""
        reply = _run(_ping_once(self._open_port))
        self.assertEqual(reply.get("type"), "pong")

    def test_unauthenticated_handshake_rejected_when_token_configured(self) -> None:
        import websockets

        before = set(self._auth_server._sessions)
        with self.assertRaises(websockets.exceptions.ConnectionClosedError) as ctx:
            _run(_ping_once(self._auth_port))
        self.assertEqual(_close_code(ctx.exception), 1008)
        self.assertEqual(set(self._auth_server._sessions), before)

    def test_wrong_token_rejected(self) -> None:
        import websockets

        with self.assertRaises(websockets.exceptions.ConnectionClosedError):
            _run(_ping_once(self._auth_port, additional_headers={"X-Gateway-Token": "wrong"}))

    def test_token_query_param_accepted(self) -> None:
        from urllib.parse import urlencode

        async def _with_query() -> dict:
            async with _connect(self._auth_port, f"/?{urlencode({'token': 'secret-123'})}") as ws:
                await ws.send(json.dumps({"type": "ping", "session_id": "t", "timestamp": 0}))
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=10))

        reply = _run(_with_query())
        self.assertEqual(reply.get("type"), "pong")

    def test_bearer_header_accepted(self) -> None:
        async def _with_bearer() -> dict:
            async with _connect(self._auth_port, "/", additional_headers={"Authorization": "Bearer secret-123"}) as ws:
                await ws.send(json.dumps({"type": "ping", "session_id": "t", "timestamp": 0}))
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=10))

        reply = _run(_with_bearer())
        self.assertEqual(reply.get("type"), "pong")

    def test_open_server_keeps_local_default(self) -> None:
        reply = _run(_ping_once(self._open_port))
        self.assertEqual(reply.get("type"), "pong")

    def test_foreign_origin_rejected(self) -> None:
        import websockets

        with self.assertRaises(websockets.exceptions.ConnectionClosedError):
            _run(_ping_once(self._auth_port, origin="https://evil.example.com"))


if __name__ == "__main__":
    unittest.main()
