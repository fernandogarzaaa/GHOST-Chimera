"""Toolset system — composable tool groups with progressive disclosure.

Patterns adapted from Hermes-Agent's toolsets.py and skills_hub.py (Nous Research, MIT licensed).
Layers on top of Ghost Chimera's existing SkillManager to add tool grouping,
composition, and context-aware progressive disclosure.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent_core.skill_manager import SkillManager
from ..logging_config import get_logger
from .mcp_wrapper import list_available_tools

logger = get_logger("toolsets")

# ---------------------------------------------------------------------------
# Toolset definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolDefinition:
    """A single tool available within a toolset."""
    name: str
    description: str
    schema: dict[str, Any]
    requires_approval: bool = False
    skill_name: str = ""
    category: str = "general"

@dataclass(frozen=True)
class ToolsetDefinition:
    """A composable group of tools with context injection."""
    name: str
    description: str
    tools: list[ToolDefinition]
    permissions: dict[str, bool] = field(default_factory=dict)
    context_injection: dict[str, str] = field(default_factory=dict)
    skill_files: list[str] = field(default_factory=list)
    requires_skill: str = ""  # optional skill prerequisite

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]

    @property
    def tool_count(self) -> int:
        return len(self.tools)

# ---------------------------------------------------------------------------
# Toolset registry
# ---------------------------------------------------------------------------

class ToolsetRegistry:
    """Registry of composable toolsets with progressive disclosure."""

    def __init__(self):
        self._toolsets: dict[str, ToolsetDefinition] = {}
        self._lock = threading.RLock()
        self._loaded_skills: set[str] = set()
        self._mcp_tools: list[dict] = []

    def register(self, toolset: ToolsetDefinition) -> None:
        with self._lock:
            self._toolsets[toolset.name] = toolset
        logger.info("Registered toolset '%s': %d tools", toolset.name, toolset.tool_count)

    def get(self, name: str) -> ToolsetDefinition | None:
        return self._toolsets.get(name)

    def unregister(self, name: str) -> bool:
        with self._lock:
            if name in self._toolsets:
                del self._toolsets[name]
                return True
        return False

    def combine(self, *names: str) -> list[ToolDefinition]:
        """Combine multiple toolsets into a single tool list."""
        combined = []
        seen = set()
        for name in names:
            ts = self._toolsets.get(name)
            if ts:
                for tool in ts.tools:
                    if tool.name not in seen:
                        combined.append(tool)
                        seen.add(tool.name)
        return combined

    def list_all(self) -> list[dict[str, Any]]:
        return [{"name": ts.name, "description": ts.description,
                 "tool_count": ts.tool_count, "tools": ts.tool_names}
                for ts in self._toolsets.values()]

    def register_builtin_toolsets(self) -> None:
        """Register default toolsets based on existing skills."""
        # Build toolsets from existing skills
        skill_manager = SkillManager()
        built_skills = skill_manager.list_skills()
        logger.info("Registered %d skills from skill_manager", len(built_skills))

        # coding toolset
        coding_tools = [
            ToolDefinition(name="write_file", description="Write or overwrite a file",
                          schema={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
                          requires_approval=True, category="coding"),
            ToolDefinition(name="read_file", description="Read file contents",
                          schema={"type": "object", "properties": {"path": {"type": "string"}}},
                          category="coding"),
            ToolDefinition(name="shell", description="Execute shell command",
                          schema={"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}},
                          requires_approval=True, category="coding"),
            ToolDefinition(name="code_search", description="Search codebase for patterns",
                          schema={"type": "object", "properties": {"query": {"type": "string"}, "extensions": {"type": "array", "items": {"type": "string"}}}},
                          category="coding"),
        ]
        self.register(ToolsetDefinition(
            name="coding", description="File editing, shell execution, and code search",
            tools=coding_tools,
            permissions={"allow_shell": True, "allow_file_write": True, "allow_file_read": True},
            context_injection={"code_root": os.environ.get("GHOSTCHIMERA_CODE_ROOT", ".")},
        ))

        # research toolset
        research_tools = [
            ToolDefinition(name="http_get", description="Fetch URL content via HTTPS",
                          schema={"type": "object", "properties": {"url": {"type": "string"}}},
                          requires_approval=True, category="research"),
            ToolDefinition(name="web_research", description="Research a topic via web search",
                          schema={"type": "object", "properties": {"query": {"type": "string"}}},
                          requires_approval=True, category="research"),
            ToolDefinition(name="code_search", description="Search codebase patterns",
                          schema={"type": "object", "properties": {"query": {"type": "string"}}},
                          category="research"),
            ToolDefinition(name="rag_query", description="Query local knowledge base",
                          schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
                          category="research"),
        ]
        self.register(ToolsetDefinition(
            name="research", description="Web research, code search, and knowledge retrieval",
            tools=research_tools,
            permissions={"allow_network": True},
        ))

        # safety toolset
        safety_tools = [
            ToolDefinition(name="safety_check", description="Validate content against safety policy",
                          schema={"type": "object", "properties": {"content": {"type": "string"}, "policy": {"type": "string"}}},
                          category="safety"),
            ToolDefinition(name="hallucination_detect", description="Detect hallucination signals",
                          schema={"type": "object", "properties": {"text": {"type": "string"}, "strategy": {"type": "string"}}},
                          category="safety"),
        ]
        self.register(ToolsetDefinition(
            name="safety", description="Safety validation and hallucination detection",
            tools=safety_tools,
            permissions={},
        ))

        # devops toolset
        devops_tools = [
            ToolDefinition(name="test_run", description="Run test suite",
                          schema={"type": "object", "properties": {"pattern": {"type": "string"}, "parallel": {"type": "boolean"}}},
                          requires_approval=True, category="devops"),
            ToolDefinition(name="lint", description="Run linting checks",
                          schema={"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}}},
                          category="devops"),
            ToolDefinition(name="build", description="Build the project",
                          schema={"type": "object", "properties": {"target": {"type": "string"}}},
                          requires_approval=True, category="devops"),
        ]
        self.register(ToolsetDefinition(
            name="devops", description="Testing, linting, and build operations",
            tools=devops_tools,
            permissions={"allow_shell": True},
        ))

        # MCP toolset (dynamic)
        try:
            mcp_tools = list_available_tools()
            if mcp_tools:
                self.register(ToolsetDefinition(
                    name="mcp", description="Tools from connected MCP servers",
                    tools=[ToolDefinition(name=t["name"], description=t.get("description", ""),
                                         schema=t.get("inputSchema", {})) for t in mcp_tools[:50]],
                    permissions={"allow_network": True},
                ))
        except Exception as exc:
            logger.debug("MCP toolset discovery failed: %s", exc)

    def get_mcp_tools(self) -> list[dict]:
        """Fetch current tools from MCP servers."""
        if not self._mcp_tools:
            try:
                self._mcp_tools = list_available_tools()
            except Exception as exc:
                logger.debug("MCP tool discovery failed: %s", exc)
        return self._mcp_tools

# ---------------------------------------------------------------------------
# Toolset manager — progressive disclosure
# ---------------------------------------------------------------------------

class ToolsetManager:
    """Manages active toolsets and progressive tool disclosure."""

    def __init__(self, registry: ToolsetRegistry | None = None):
        self.registry = registry or ToolsetRegistry()
        self._active_toolsets: list[str] = []
        self._disclosed_tools: list[ToolDefinition] = []
        self._lock = threading.Lock()
        self._load_active()

    def _load_active(self) -> None:
        """Load active toolsets from state or defaults."""
        state_file = Path(os.environ.get("GHOSTCHIMERA_STATE_DIR", str(Path.home() / ".ghostchimera"))) / "active_toolsets.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    self._active_toolsets = json.load(f).get("active", ["coding"])
            except (json.JSONDecodeError, KeyError):
                self._active_toolsets = ["coding"]
        else:
            self._active_toolsets = ["coding"]  # default: coding only

    def _save_active(self) -> None:
        state_file = Path(os.environ.get("GHOSTCHIMERA_STATE_DIR", str(Path.home() / ".ghostchimera"))) / "active_toolsets.json"
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(state_file, "w") as f:
                json.dump({"active": self._active_toolsets}, f)
        except Exception as exc:
            logger.warning("Failed to save active toolsets: %s", exc)

    def enable_toolset(self, name: str) -> bool:
        """Enable a toolset for the current session."""
        if name not in self.registry._toolsets:
            logger.warning("Toolset '%s' not registered", name)
            return False
        with self._lock:
            if name not in self._active_toolsets:
                self._active_toolsets.append(name)
                self._rebuild_disclosure()
        self._save_active()
        logger.info("Enabled toolset: %s", name)
        return True

    def disable_toolset(self, name: str) -> bool:
        """Disable a toolset for the current session."""
        with self._lock:
            if name in self._active_toolsets:
                self._active_toolsets.remove(name)
                self._rebuild_disclosure()
        self._save_active()
        return True

    @property
    def active_tools(self) -> list[ToolDefinition]:
        """Get all currently disclosed tools."""
        if not self._disclosed_tools:
            self._rebuild_disclosure()
        return self._disclosed_tools

    def get_tool_schema(self, name: str) -> dict[str, Any] | None:
        """Get the schema for a specific tool by name."""
        for tool in self.active_tools:
            if tool.name == name:
                return tool.schema
        return None

    def needs_approval(self, tool_name: str) -> bool:
        """Check if a tool requires approval gating."""
        for tool in self.active_tools:
            if tool.name == tool_name:
                return tool.requires_approval
        return False

    def _rebuild_disclosure(self) -> None:
        """Rebuild the disclosed tool list from active toolsets."""
        self._disclosed_tools = []
        seen = set()
        for ts_name in self._active_toolsets:
            ts = self.registry._toolsets.get(ts_name)
            if ts:
                for tool in ts.tools:
                    if tool.name not in seen:
                        self._disclosed_tools.append(tool)
                        seen.add(tool.name)

    def status(self) -> dict[str, Any]:
        """Toolset manager status."""
        return {
            "active_toolsets": self._active_toolsets,
            "active_tool_count": len(self.active_tools),
            "active_tools": [t.name for t in self.active_tools],
            "registered_toolsets": self.registry.list_all(),
        }


__all__ = [
    "ToolsetRegistry",
    "ToolsetManager",
    "ToolsetDefinition",
    "ToolDefinition",
]
