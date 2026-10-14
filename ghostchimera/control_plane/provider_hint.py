"""Friendly first-run guidance when no model provider is configured."""

from __future__ import annotations

import sys
from typing import TextIO

# Env vars that make a cloud model backend available, most relevant first.
PROVIDER_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("NEBIUS_API_KEY", "NVIDIA Nemotron on Nebius Token Factory (https://console.nebius.com)"),
    ("OPENAI_API_KEY", "OpenAI"),
    ("ANTHROPIC_API_KEY", "Anthropic"),
    ("OPENROUTER_API_KEY", "OpenRouter"),
)


def no_provider_message(objective: str = "", detail: str = "") -> str:
    lines = ["ghost: no model provider is configured, so Chimera Pilot has no backend to run this objective."]
    if objective:
        lines.append(f"  objective: {objective}")
    if detail:
        lines.append(f"  detail: {detail}")
    lines.append("")
    lines.append("Set one of these environment variables and try again:")
    width = max(len(key) for key, _ in PROVIDER_ENV_KEYS) + len("=...")
    for key, label in PROVIDER_ENV_KEYS:
        lines.append(f"  export {(key + '=...').ljust(width)}   # {label}")
    lines.append("")
    lines.append("Or run `ghost setup` to pick a provider (including free local models),")
    lines.append("or `ghost demo` to replay a recorded Nemotron session offline with no keys.")
    return "\n".join(lines)


def print_no_provider(objective: str = "", detail: str = "", stream: TextIO | None = None) -> None:
    print(no_provider_message(objective, detail), file=stream or sys.stderr)


__all__ = ["PROVIDER_ENV_KEYS", "no_provider_message", "print_no_provider"]
