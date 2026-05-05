"""Tests for the Hermes-Agent migration: toolsets.py."""

from __future__ import annotations

import os
import tempfile
import unittest

from ghostchimera.chimera_pilot.toolsets import (
    ToolDefinition,
    ToolsetDefinition,
    ToolsetManager,
    ToolsetRegistry,
)


class ToolsetDefinitionTests(unittest.TestCase):
    def test_tool_names(self) -> None:
        tools = [
            ToolDefinition(name="a", description="a", schema={}),
            ToolDefinition(name="b", description="b", schema={}),
        ]
        ts = ToolsetDefinition(name="test", description="test", tools=tools)
        self.assertEqual(ts.tool_names, ["a", "b"])

    def test_tool_count(self) -> None:
        ts = ToolsetDefinition(name="test", description="test", tools=[])
        self.assertEqual(ts.tool_count, 0)
        ts = ToolsetDefinition(name="test", description="test",
                               tools=[ToolDefinition(name="x", description="x", schema={})])
        self.assertEqual(ts.tool_count, 1)


class ToolsetRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolsetRegistry()

    def test_register_and_get(self) -> None:
        ts = ToolsetDefinition(name="test", description="test", tools=[])
        self.registry.register(ts)
        found = self.registry.get("test")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "test")

    def test_unregister(self) -> None:
        ts = ToolsetDefinition(name="test", description="test", tools=[])
        self.registry.register(ts)
        self.assertTrue(self.registry.unregister("test"))
        self.assertIsNone(self.registry.get("test"))

    def test_unregister_nonexistent(self) -> None:
        self.assertFalse(self.registry.unregister("nonexistent"))

    def test_combine_toolsets(self) -> None:
        ts1 = ToolsetDefinition(name="a", description="a",
                                tools=[ToolDefinition(name="x", description="x", schema={})])
        ts2 = ToolsetDefinition(name="b", description="b",
                                tools=[ToolDefinition(name="y", description="y", schema={})])
        self.registry.register(ts1)
        self.registry.register(ts2)
        combined = self.registry.combine("a", "b")
        names = [t.name for t in combined]
        self.assertIn("x", names)
        self.assertIn("y", names)

    def test_combine_removes_duplicates(self) -> None:
        ts1 = ToolsetDefinition(name="a", description="a",
                                tools=[ToolDefinition(name="x", description="x", schema={})])
        ts2 = ToolsetDefinition(name="b", description="b",
                                tools=[ToolDefinition(name="x", description="x dup", schema={})])
        self.registry.register(ts1)
        self.registry.register(ts2)
        combined = self.registry.combine("a", "b")
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0].name, "x")

    def test_list_all(self) -> None:
        ts = ToolsetDefinition(name="test", description="test", tools=[])
        self.registry.register(ts)
        all_ts = self.registry.list_all()
        self.assertEqual(len(all_ts), 1)
        self.assertEqual(all_ts[0]["name"], "test")

    def test_list_all_empty(self) -> None:
        self.assertEqual(self.registry.list_all(), [])


class ToolsetManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        os.environ["GHOSTCHIMERA_STATE_DIR"] = self.tmpdir
        self.registry = ToolsetRegistry()
        # Register a coding toolset manually
        coding_tools = [
            ToolDefinition(name="write_file", description="write", schema={"type": "object", "properties": {}}, requires_approval=True),
            ToolDefinition(name="read_file", description="read", schema={"type": "object", "properties": {}}),
        ]
        self.registry.register(ToolsetDefinition(name="coding", description="coding", tools=coding_tools))
        self.registry.register(ToolsetDefinition(name="research", description="research",
                                                  tools=[ToolDefinition(name="web_search", description="search", schema={})]))
        self.manager = ToolsetManager(registry=self.registry)

    def test_default_active_toolsets(self) -> None:
        self.assertEqual(self.manager._active_toolsets, ["coding"])

    def test_enable_toolset(self) -> None:
        self.assertTrue(self.manager.enable_toolset("research"))
        self.assertIn("research", self.manager._active_toolsets)
        self.assertIn("write_file", [t.name for t in self.manager.active_tools])
        self.assertIn("web_search", [t.name for t in self.manager.active_tools])

    def test_disable_toolset(self) -> None:
        self.manager.enable_toolset("research")
        self.assertTrue(self.manager.disable_toolset("research"))
        self.assertNotIn("research", self.manager._active_toolsets)

    def test_disable_missing_toolset(self) -> None:
        # disable_toolset always returns True (idempotent)
        self.assertTrue(self.manager.disable_toolset("nonexistent"))

    def test_active_tools(self) -> None:
        tools = self.manager.active_tools
        self.assertIn("write_file", [t.name for t in tools])
        self.assertIn("read_file", [t.name for t in tools])

    def test_get_tool_schema(self) -> None:
        schema = self.manager.get_tool_schema("write_file")
        self.assertIsNotNone(schema)
        self.assertEqual(schema["type"], "object")

    def test_get_tool_schema_missing(self) -> None:
        self.assertIsNone(self.manager.get_tool_schema("nonexistent"))

    def test_needs_approval(self) -> None:
        self.assertTrue(self.manager.needs_approval("write_file"))
        self.assertFalse(self.manager.needs_approval("read_file"))

    def test_needs_approval_missing(self) -> None:
        self.assertFalse(self.manager.needs_approval("nonexistent"))

    def test_status(self) -> None:
        status = self.manager.status()
        self.assertIn("active_toolsets", status)
        self.assertIn("active_tools", status)
        self.assertIn("registered_toolsets", status)

    def test_status_reflects_active_toolsets(self) -> None:
        self.manager.enable_toolset("research")
        status = self.manager.status()
        self.assertIn("research", status["active_toolsets"])
        self.assertIn("web_search", status["active_tools"])

    def test_combine_via_registry(self) -> None:
        combined = self.registry.combine("coding", "research")
        names = [t.name for t in combined]
        self.assertIn("write_file", names)
        self.assertIn("web_search", names)


if __name__ == "__main__":
    unittest.main()
