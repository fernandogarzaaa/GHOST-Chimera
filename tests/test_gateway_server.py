"""Tests for the Hermes-Agent migration: gateway_server.py and mcp_wrapper.py."""

from __future__ import annotations

import contextlib
import socket
import threading
import unittest

from ghostchimera.chimera_pilot.gateway_server import (
    GatewayMessage,
    GatewayServer,
    GatewaySession,
    find_free_port,
)
from ghostchimera.chimera_pilot.mcp_wrapper import (
    MCPClient,
    MCPRegistry,
    disconnect_mcp_servers,
    get_default_registry,
    list_available_tools,
    register_mcp_server,
)

_CANDIDATE_BASES = (49311, 49411, 49511, 49611, 49711)


def claim_port_block(testcase: unittest.TestCase, size: int) -> int:
    """Return a base port with `size` consecutive free ports, or skip.

    Shared CI runners may hold any fixed port; verifying a free block
    first eliminates EADDRINUSE flakes while keeping exact-offset assertions.
    """
    for base in _CANDIDATE_BASES:
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
    testcase.skipTest("no free port block on this runner")


class GatewayMessageTests(unittest.TestCase):
    def test_to_json_and_from_json(self) -> None:
        msg = GatewayMessage(type="text", session_id="s1", data={"message": "hello"})
        raw = msg.to_json()
        parsed = GatewayMessage.from_json(raw)
        self.assertEqual(parsed.type, "text")
        self.assertEqual(parsed.session_id, "s1")
        self.assertEqual(parsed.data["message"], "hello")

    def test_gateway_message_types(self) -> None:
        for msg_type in ["text", "tool_output", "error", "status", "ping", "pong", "checkpoint"]:
            msg = GatewayMessage(type=msg_type, session_id="s1", data={})
            self.assertEqual(msg.type, msg_type)


class GatewaySessionTests(unittest.TestCase):
    def test_session_creation(self) -> None:
        session = GatewaySession(session_id="s1", agent=None)
        self.assertEqual(session.session_id, "s1")
        self.assertFalse(session.is_connected)
        self.assertEqual(session.message_count, 0)

    def test_touch(self) -> None:
        session = GatewaySession(session_id="s1", agent=None)
        session.touch()
        self.assertEqual(session.message_count, 1)

    def test_to_dict(self) -> None:
        session = GatewaySession(session_id="s1", agent=None)
        d = session.to_dict()
        self.assertEqual(d["session_id"], "s1")
        self.assertIn("created_at", d)


class GatewayServerTests(unittest.TestCase):
    def test_server_creation(self) -> None:
        server = GatewayServer()
        self.assertIsNotNone(server)
        self.assertEqual(len(server._sessions), 0)

    def test_create_session(self) -> None:
        server = GatewayServer()
        session = server.create_session("test-s1")
        self.assertEqual(session.session_id, "test-s1")
        self.assertIn("test-s1", server._sessions)

    def test_get_session(self) -> None:
        server = GatewayServer()
        server.create_session("test-s1")
        session = server.get_session("test-s1")
        self.assertIsNotNone(session)

    def test_get_missing_session(self) -> None:
        server = GatewayServer()
        self.assertIsNone(server.get_session("nonexistent"))

    def test_session_thread_safety(self) -> None:
        server = GatewayServer()
        errors: list[Exception] = []

        def create_sessions(n: int) -> None:
            for i in range(n):
                try:
                    server.create_session(f"thread-{i}")
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=create_sessions, args=(100,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_status(self) -> None:
        server = GatewayServer()
        server.create_session("s1")
        status = server.status()
        self.assertEqual(status["session_count"], 1)
        self.assertIn("running", status)

    def test_port_zero_keeps_ephemeral_contract(self) -> None:
        # port=0 means "let the OS pick an ephemeral port" — the auto-port
        # resolver must not rewrite it. Regression: it used to scan from 0
        # and raise OSError, breaking run_console(port=0, http_port=0).
        server = GatewayServer(host="127.0.0.1", port=0, http_port=0)
        server._resolve_ports()
        self.assertEqual(server.port, 0)
        self.assertEqual(server.http_port, 0)

    def test_port_resolution_keeps_concrete_ports_when_free(self) -> None:
        # Sanity: a concrete, free port is left untouched; HTTP stays WS+1.
        # Claimed first: shared runners may hold any fixed number.
        base = claim_port_block(self, 2)
        server = GatewayServer(host="127.0.0.1", port=base, http_port=None)
        server._resolve_ports()
        self.assertEqual(server.port, base)
        self.assertEqual(server.http_port, base + 1)


class GatewayPortSelectionTests(unittest.TestCase):
    # Candidate bases are only starting points: claim_port_block verifies a
    # run of free ports first, so shared CI runners holding one of these do
    # not break the suite (previously hardcoded binds flaked EADDRINUSE).
    def _claim_block(self, size: int) -> int:
        return claim_port_block(self, size)

    def _occupy(self, port: int) -> socket.socket:
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", port))
        holder.listen(1)
        self.addCleanup(holder.close)
        return holder

    def test_preferred_port_returned_when_free(self) -> None:
        base = self._claim_block(4)
        port = find_free_port("127.0.0.1", base, max_attempts=4)
        self.assertGreaterEqual(port, base)
        self.assertLess(port, base + 4)

    def test_occupied_port_is_skipped(self) -> None:
        base = self._claim_block(9)
        self._occupy(base)
        self.assertEqual(find_free_port("127.0.0.1", base, max_attempts=8), base + 1)

    def test_reuseaddr_holder_still_counts_as_occupied(self) -> None:
        # Regression test: http.server sets SO_REUSEADDR, and a probe that
        # also sets SO_REUSEADDR would falsely report such a port as free
        # on Windows. The probe must detect the active listener instead.
        base = self._claim_block(9)
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", base))
        holder.listen(1)
        self.addCleanup(holder.close)
        self.assertEqual(find_free_port("127.0.0.1", base, max_attempts=8), base + 1)

    def test_reserved_ports_are_skipped(self) -> None:
        base = self._claim_block(4)
        self.assertEqual(
            find_free_port("127.0.0.1", base, max_attempts=8, reserved={base, base + 1}),
            base + 2,
        )

    def test_no_free_port_raises(self) -> None:
        base = self._claim_block(1)
        self._occupy(base)
        with self.assertRaises(OSError):
            find_free_port("127.0.0.1", base, max_attempts=1)

    def test_server_start_falls_back_from_occupied_ports(self) -> None:
        import time
        import urllib.request

        base = self._claim_block(4)
        self._occupy(base)
        server = GatewayServer(host="127.0.0.1", port=base, http_port=base + 1)
        try:
            server.start()
            self.assertNotEqual(server.port, base)
            self.assertNotEqual(server.http_port, base)
            self.assertNotEqual(server.port, server.http_port)
            deadline = time.time() + 10
            body = None
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{server.http_port}/health", timeout=2) as response:
                        body = response.read().decode("utf-8")
                    break
                except OSError:
                    time.sleep(0.2)
            self.assertIsNotNone(body)
            self.assertIn('"ok": true', body)
        finally:
            server.stop()

    def test_port_zero_keeps_ephemeral_contract(self) -> None:
        # port=0 means "let the OS pick an ephemeral port" — the auto-port
        # resolver must not rewrite it. Regression: it used to scan from 0
        # and raise OSError, breaking run_console(port=0, http_port=0).
        server = GatewayServer(host="127.0.0.1", port=0, http_port=0)
        server._resolve_ports()
        self.assertEqual(server.port, 0)
        self.assertEqual(server.http_port, 0)

    def test_port_resolution_keeps_concrete_ports_when_free(self) -> None:
        # Sanity: a concrete, free port is left untouched; HTTP stays WS+1.
        # Claimed first: shared runners may hold any fixed number.
        base = claim_port_block(self, 2)
        server = GatewayServer(host="127.0.0.1", port=base, http_port=None)
        server._resolve_ports()
        self.assertEqual(server.port, base)
        self.assertEqual(server.http_port, base + 1)


class MCPClientTests(unittest.TestCase):
    def test_client_creation(self) -> None:
        client = MCPClient(name="test", command="echo")
        self.assertEqual(client.name, "test")
        self.assertFalse(client.available)
        self.assertEqual(client.tools, [])
        self.assertEqual(client.timeout, 120.0)

    def test_call_tool_not_connected(self) -> None:
        client = MCPClient(name="test", command="echo")
        result = client.call_tool("some_tool", {})
        self.assertEqual(result["status"], "error")
        self.assertIn("not connected", result["content"])

    def test_shutdown_no_process(self) -> None:
        client = MCPClient(name="test", command="echo")
        client.shutdown()  # Should not raise


class MCPRegistryTests(unittest.TestCase):
    def test_register_and_get(self) -> None:
        registry = MCPRegistry()
        client = registry.register("test", "echo")
        self.assertEqual(client.name, "test")
        self.assertIs(registry.get("test"), client)

    def test_get_missing(self) -> None:
        registry = MCPRegistry()
        self.assertIsNone(registry.get("nonexistent"))

    def test_connected_tools_empty(self) -> None:
        registry = MCPRegistry()
        self.assertEqual(registry.connected_tools(), [])

    def test_find_tool(self) -> None:
        registry = MCPRegistry()
        client = registry.register("test", "echo")
        client.tools = [{"name": "test_tool", "description": "desc", "inputSchema": {}}]
        found = registry.find_tool("test_tool")
        self.assertIs(found, client)

    def test_find_tool_missing(self) -> None:
        registry = MCPRegistry()
        self.assertIsNone(registry.find_tool("nonexistent"))

    def test_call_tool_via_registry(self) -> None:
        registry = MCPRegistry()
        client = registry.register("test", "echo")
        client.tools = [{"name": "test_tool", "description": "desc", "inputSchema": {}}]
        client.available = True
        result = registry.call_tool("test_tool", {})
        self.assertIn("status", result)

    def test_call_tool_not_found(self) -> None:
        registry = MCPRegistry()
        result = registry.call_tool("nonexistent_tool", {})
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["content"])

    def test_default_registry(self) -> None:
        registry = get_default_registry()
        self.assertIsNotNone(registry)
        # chimeralang should be pre-registered
        chimera = registry.get("chimeralang")
        self.assertIsNotNone(chimera)
        self.assertEqual(chimera.name, "chimeralang")

    def test_register_mcp_server(self) -> None:
        registry = register_mcp_server("custom", "echo", args=["hello"])
        client = registry.get("custom")
        self.assertIsNotNone(client)
        self.assertEqual(client.args, ["hello"])


class ListAvailableToolsTests(unittest.TestCase):
    def test_list_available_tools_returns_list(self) -> None:
        # Returns connected tools, which is empty by default
        tools = list_available_tools()
        self.assertIsInstance(tools, list)


class ModuleConvenienceTests(unittest.TestCase):
    def test_disconnect_mcp_servers(self) -> None:
        # Should not raise even with no servers connected
        disconnect_mcp_servers()


class GatewayCoordinatedBindTests(unittest.TestCase):
    def test_env_http_port_is_explicit(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"GHOSTCHIMERA_HTTP_PORT": "49451"}, clear=False):
            server = GatewayServer(host="127.0.0.1", port=49452)
        self.assertEqual(server.http_port, 49451)
        self.assertTrue(server._http_port_explicit)
        server._resolve_ports()
        self.assertEqual(server.http_port, 49451)

    def test_ephemeral_ws_keeps_ephemeral_http(self) -> None:
        server = GatewayServer(host="127.0.0.1", port=0)
        server._http_port_explicit = False
        server._resolve_ports()
        self.assertEqual(server.port, 0)
        self.assertEqual(server.http_port, 0)

    def test_start_raises_when_no_pair_bindable(self) -> None:
        import socket
        from unittest import mock

        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", 49461))
        holder.listen(1)
        self.addCleanup(holder.close)
        # Force every resolution onto the occupied port: binds must fail.
        with mock.patch("ghostchimera.chimera_pilot.gateway_server.find_free_port", return_value=49461):
            server = GatewayServer(host="127.0.0.1", port=49461, http_port=49462)
            with self.assertRaises(OSError):
                server.start()
            self.assertIsNone(server._http_server)


if __name__ == "__main__":
    unittest.main()
