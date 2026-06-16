"""Claude Agent SDK provider (subscription-backed).

This provider lets Ghost Chimera use the user's **Claude subscription** as a
model backend, rather than a billed ``ANTHROPIC_API_KEY``.  It delegates a single
reasoning turn to the Claude Agent SDK (``claude-agent-sdk``), which drives the
locally-installed, subscription-authenticated Claude Code CLI.  Ghost never reads
or copies OAuth tokens — the CLI owns the subscription session, exactly like
:class:`~ghostchimera.model_layer.codex_cli_provider.CodexCliProvider` does for
Codex.

It is used as a plain single-turn text backend: tools are disabled, settings
sources are not loaded, and ``max_turns`` is 1, so it behaves like any other
``BaseProvider`` and does not start an autonomous agent loop.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .base_provider import BaseProvider


def _claude_cli_path() -> str | None:
    """Resolve the subscription-authenticated Claude Code CLI executable."""

    override = os.environ.get("GHOSTCHIMERA_CLAUDE_CLI_PATH")
    if override:
        return override if Path(override).exists() else None
    if sys.platform.startswith("win"):
        for candidate in ("claude.cmd", "claude.exe", "claude.ps1", "claude"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return shutil.which("claude")


def _sdk_available() -> bool:
    return importlib.util.find_spec("claude_agent_sdk") is not None


class ClaudeAgentProvider(BaseProvider):
    """Single-turn provider backed by the Claude Agent SDK + subscription CLI."""

    name = "claude_agent"
    default_model = "claude-sonnet-4-6"

    def __init__(self, profile: Any | None = None) -> None:
        self.model = (
            getattr(profile, "model", "")
            if profile is not None and getattr(profile, "model", "")
            else os.environ.get("CLAUDE_AGENT_MODEL", self.default_model)
        )
        self.cli_path = _claude_cli_path()
        self.timeout_seconds = float(os.environ.get("GHOSTCHIMERA_CLAUDE_AGENT_TIMEOUT_SECONDS", "180"))
        self._sdk_present = _sdk_available()
        self.available = self._sdk_present and self.cli_path is not None

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self._sdk_present:
            errors.append("claude-agent-sdk is not installed (pip install claude-agent-sdk)")
        if self.cli_path is None:
            errors.append(
                "Claude Code CLI not found. Install with `npm i -g @anthropic-ai/claude-code` and run `claude` to log in."
            )
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
            "auth": "claude-subscription-oauth",
            "cli_path": self.cli_path or "",
        }

    def chat(self, system_message: str, user_message: str) -> str:
        errors = self.validate_config()
        if errors:
            raise RuntimeError("ClaudeAgentProvider unavailable: " + "; ".join(errors))
        try:
            return asyncio.run(self._achat(system_message, user_message))
        except RuntimeError as exc:
            # asyncio.run fails if a loop is already running; fall back to a fresh loop.
            if "asyncio.run() cannot be called" in str(exc) or "running event loop" in str(exc):
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(self._achat(system_message, user_message))
                finally:
                    loop.close()
            raise

    async def _achat(self, system_message: str, user_message: str) -> str:
        from claude_agent_sdk import (  # imported lazily so the package stays optional
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )

        options = ClaudeAgentOptions(
            system_prompt=system_message,
            model=self.model,
            allowed_tools=[],          # pure reasoning backend — no tool use
            max_turns=1,               # single response, not an agent loop
            permission_mode="default",
            setting_sources=[],        # do not load user/project CLAUDE.md, hooks, MCP
            cli_path=self.cli_path,
        )

        chunks: list[str] = []

        async def _collect() -> None:
            async for message in query(prompt=user_message, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            chunks.append(block.text)

        await asyncio.wait_for(_collect(), timeout=self.timeout_seconds)
        text = "".join(chunks).strip()
        if not text:
            raise RuntimeError("Claude Agent SDK returned no text content")
        return text


__all__ = ["ClaudeAgentProvider"]
