"""Tests for the subscription-backed Claude Agent SDK provider."""

from __future__ import annotations

import claude_agent_sdk
import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from ghostchimera.model_layer.claude_agent_provider import ClaudeAgentProvider
from ghostchimera.model_layer.providers import get_provider


def _fake_cli(tmp_path, monkeypatch):
    cli = tmp_path / "claude.cmd"
    cli.write_text("@echo fake", encoding="utf-8")
    monkeypatch.setenv("GHOSTCHIMERA_CLAUDE_CLI_PATH", str(cli))
    return cli


def test_registered_in_provider_registry():
    assert isinstance(get_provider("claude_agent"), ClaudeAgentProvider)


def test_unavailable_without_cli(monkeypatch):
    monkeypatch.setenv("GHOSTCHIMERA_CLAUDE_CLI_PATH", "/nonexistent/claude")
    provider = ClaudeAgentProvider()
    assert provider.available is False
    assert any("Claude Code CLI not found" in e for e in provider.validate_config())


def test_chat_collects_text_from_agent_sdk(tmp_path, monkeypatch):
    _fake_cli(tmp_path, monkeypatch)
    captured = {}

    async def fake_query(*, prompt, options=None, transport=None):
        captured["prompt"] = prompt
        captured["options"] = options
        yield AssistantMessage(content=[TextBlock(text="Hello "), TextBlock(text="Ghost")], model="claude-sonnet-4-6")

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)

    provider = ClaudeAgentProvider()
    assert provider.available is True
    out = provider.chat("be concise", "say hi")

    assert out == "Hello Ghost"
    assert captured["prompt"] == "say hi"
    # Single-turn, tool-free, isolated settings.
    assert captured["options"].max_turns == 1
    assert captured["options"].allowed_tools == []
    assert captured["options"].setting_sources == []
    assert captured["options"].system_prompt == "be concise"


def test_chat_raises_when_no_text(tmp_path, monkeypatch):
    _fake_cli(tmp_path, monkeypatch)

    async def empty_query(*, prompt, options=None, transport=None):
        if False:  # pragma: no cover - makes this an async generator
            yield None

    monkeypatch.setattr(claude_agent_sdk, "query", empty_query)
    provider = ClaudeAgentProvider()
    with pytest.raises(RuntimeError, match="no text content"):
        provider.chat("sys", "user")


def test_model_override_via_env(tmp_path, monkeypatch):
    _fake_cli(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_AGENT_MODEL", "claude-opus-4-8")
    provider = ClaudeAgentProvider()
    assert provider.model == "claude-opus-4-8"
