"""Friendly first-run guidance when no model provider is configured."""

from __future__ import annotations

import os
import sys
from typing import TextIO

# Env vars that make a cloud model backend available, most relevant first.
PROVIDER_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("NEBIUS_API_KEY", "NVIDIA Nemotron on Nebius Token Factory (https://console.nebius.com)"),
    ("OPENAI_API_KEY", "OpenAI"),
    ("ANTHROPIC_API_KEY", "Anthropic"),
    ("OPENROUTER_API_KEY", "OpenRouter"),
)


# Task kinds a configured model provider can run (see ModelProviderBackend).
MODEL_TASK_KINDS = frozenset({"reasoning", "long_context_doc", "rag_query"})


def _keys_already_set(env: dict[str, str] | None = None) -> list[str]:
    active = os.environ if env is None else env
    return [key for key, _ in PROVIDER_ENV_KEYS if str(active.get(key, "") or "").strip()]


def model_provider_available(env: dict[str, str] | None = None) -> bool:
    """True when the auto-resolved model provider has credentials."""

    from ..model_layer.providers import get_provider, resolve_provider_name

    name, _source = resolve_provider_name(env=env)
    provider = get_provider(name)
    if provider is None:
        return False
    try:
        return bool(provider.available) and not provider.validate_config()
    except Exception:
        return False


def no_provider_message(objective: str = "", detail: str = "", env: dict[str, str] | None = None) -> str:
    already = _keys_already_set(env)
    if already:
        # A key is set but the provider still did not come up: don't tell the
        # user to set the variable they already set.
        lines = [f"ghost: {', '.join(already)} is set, but the configured model provider is not available."]
    else:
        lines = ["ghost: no model provider is configured, so Chimera Pilot has no backend to run this objective."]
    if objective:
        lines.append(f"  objective: {objective}")
    if detail:
        lines.append(f"  detail: {detail}")
    lines.append("")
    if already:
        active = os.environ if env is None else env
        chosen = str(active.get("GHOSTCHIMERA_MODEL_PROVIDER", "") or "").strip()
        if chosen:
            lines.append(
                f"GHOSTCHIMERA_MODEL_PROVIDER={chosen} overrides the key you set; unset it or point it at the "
                "matching provider (e.g. GHOSTCHIMERA_MODEL_PROVIDER=nebius for NEBIUS_API_KEY)."
            )
        else:
            lines.append("Pick the provider explicitly, e.g. `export GHOSTCHIMERA_MODEL_PROVIDER=nebius`.")
        lines.append("")
        lines.append("Run `ghost doctor` to see what is missing.")
        return "\n".join(lines)
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


# What enables a backend for task kinds a model provider cannot run alone.
_KIND_HINTS: dict[str, str] = {
    "file_analysis": "no file-analysis backend is registered in this build; ask about the file in plain words "
    '(e.g. `ghost ask "summarize notes.txt"`) or pass --allow-python with --pilot-cwd',
    "web_research": "no web-research backend is registered in this build; set TAVILY_API_KEY for Stealth Loop "
    "grounding, or phrase the objective as a question for the model",
    "code_execution": "pass --allow-python (and --pilot-cwd) to enable the Python runtime backend",
    "desktop_action": "pass --enable-desktop-backend (and --allow-desktop-control) to enable desktop actions",
}


def no_backend_message(objective: str, task_kind: str, detail: str = "", env: dict[str, str] | None = None) -> str:
    """Accurate message for a task no registered backend can run.

    Only a model-class task with no usable provider gets the provider hint;
    every other kind names the kind and what would enable it.
    """

    kind = str(task_kind or "").strip().lower()
    if (kind in MODEL_TASK_KINDS or not kind) and not model_provider_available(env):
        return no_provider_message(objective, detail, env)
    lines = [f"ghost: no available backend can run a `{kind}` task for this objective."]
    if objective:
        lines.append(f"  objective: {objective}")
    if detail:
        lines.append(f"  detail: {detail}")
    hint = _KIND_HINTS.get(kind)
    if hint:
        lines.append(f"  hint: {hint}")
    lines.append("Run `ghost --pilot-status` to see which backends are registered and available.")
    return "\n".join(lines)


def print_no_backend(objective: str, task_kind: str, detail: str = "", stream: TextIO | None = None) -> None:
    print(no_backend_message(objective, task_kind, detail), file=stream or sys.stderr)


__all__ = [
    "MODEL_TASK_KINDS",
    "PROVIDER_ENV_KEYS",
    "model_provider_available",
    "no_backend_message",
    "no_provider_message",
    "print_no_backend",
    "print_no_provider",
]
