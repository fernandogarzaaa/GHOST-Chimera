"""Tests for the Hermes-Agent migration: gateway_server.py and mcp_wrapper.py."""

from __future__ import annotations

import threading
import unittest

from ghostchimera.chimera_pilot.gateway_server import (
    GatewayMessage,
    GatewayServer,
    GatewaySession,
)
from ghostchimera.chimera_pilot.mcp_wrapper import (
    MCPClient,
    MCPRegistry,
    disconnect_mcp_servers,
    get_default_registry,
    list_available_tools,
    register_mcp_server,
)


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


if __name__ == "__main__":
    unittest.main()
