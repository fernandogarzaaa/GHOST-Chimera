"""Model picker for Ghost Chimera.

Lists configured providers and lets the user switch the current model.
"""

from __future__ import annotations

import sys

from .colors import Colors, color, print_error, print_header, print_info, print_success, print_warning
from .config import CONFIG_FILE, load_config, save_config
from .prog_name import prog_name

_MODEL_LISTS: dict[str, list[tuple[str, str]]] = {
    "openai": [
        ("gpt-4o (strongest)", "gpt-4o"),
        ("gpt-4o-mini (fast)", "gpt-4o-mini"),
        ("gpt-3.5-turbo (cheap)", "gpt-3.5-turbo"),
    ],
    "openrouter": [
        ("anthropic/claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
        ("anthropic/claude-opus-4-6", "anthropic/claude-opus-4-6"),
        ("openai/gpt-4o", "openai/gpt-4o"),
        ("google/gemini-2.5-pro", "google/gemini-2.5-pro"),
        ("Use a different model", ""),
    ],
    "anthropic": [
        ("claude-sonnet-4-6", "claude-sonnet-4-6"),
        ("claude-opus-4-6", "claude-opus-4-6"),
        ("claude-haiku-3-5", "claude-haiku-3-5"),
    ],
    "nebius": [
        ("Nemotron 3 Nano 30B (fast, cheap)", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
        ("Nemotron 3 Super 120B (agentic reasoning)", "nvidia/nemotron-3-super-120b-a12b"),
        ("Use a different model", ""),
    ],
    "local": [
        ("tiny (Qwen2.5 0.5B, 2GB RAM)", "tiny"),
        ("balanced (SmolLM2 1.7B, 4GB RAM)", "balanced"),
        ("stronger (Phi-3.5 mini, 6GB RAM)", "stronger"),
    ],
    "opencode_cli": [
        ("opencode/mimo-v2.5-free (free)", "opencode/mimo-v2.5-free"),
        ("opencode/ling-3.0-flash-fin-free (free)", "opencode/ling-3.0-flash-fin-free"),
        ("opencode/nemotron-3.5-lightning-free (free)", "opencode/nemotron-3.5-lightning-free"),
        ("opencode/muse-spark-1.3-contributor-free (free)", "opencode/muse-spark-1.3-contributor-free"),
        ("Use a different model", ""),
    ],
}

_PROVIDER_DISPLAY = {
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "anthropic": "Anthropic",
    "nebius": "Nebius Token Factory",
    "custom": "Custom",
    "local": "Local",
    "opencode_cli": "OpenCode CLI",
    "skip": "Deterministic",
}


_PICKER_PROVIDERS = ["nebius", "openai", "openrouter", "anthropic", "custom", "local", "opencode_cli", "skip"]


def _stdin_is_tty() -> bool:
    stdin = getattr(sys, "stdin", None)
    try:
        return bool(stdin is not None and stdin.isatty())
    except Exception:  # noqa: BLE001 - a closed/odd stdin is simply not interactive
        return False


def _ask(question: str) -> str | None:
    """Read one answer; ``None`` when input ends (Ctrl-D / closed stdin)."""
    try:
        return input(question).strip()
    except EOFError:
        print()
        return None


def run_model_picker() -> int:
    """List providers and let the user switch the current model.

    Returns a process exit code. Without an interactive terminal it only lists
    the providers and explains how to switch, instead of dying on EOFError.
    """
    print_header("Ghost Chimera — Model Picker")
    print()

    config = load_config() or {}
    model = config.setdefault("model", {})
    current_provider = model.get("provider", "")

    # Show configured providers
    if current_provider:
        print_info(f"Current provider: {_PROVIDER_DISPLAY.get(current_provider, current_provider)}")
        if model.get("model"):
            print_info(f"Current model:    {model['model']}")
        if model.get("base_url"):
            print_info(f"Base URL:         {model['base_url']}")
        print()

    # Provider list
    providers = list(_PICKER_PROVIDERS)
    provider_labels = [_PROVIDER_DISPLAY.get(p, p) for p in providers]

    print("Available providers:")
    for idx, label in enumerate(provider_labels):
        provider = providers[idx]
        marker = ">" if provider == current_provider else " "
        current = " (current)" if provider == current_provider else ""
        line = f"  {marker} {idx + 1}) {label}{current}"
        if provider == current_provider:
            print(color(line, Colors.GREEN))
        else:
            print(line)
    print()

    if not _stdin_is_tty():
        print_warning("No interactive terminal, so nothing was changed.")
        print_info(f"  To switch, run '{prog_name()} model' in a terminal, or set for example:")
        print_info("    GHOSTCHIMERA_MODEL_PROVIDER=nebius  NEBIUS_API_KEY=...")
        return 0

    # Switch provider
    idx = _ask(f"  Select a provider [1-{len(providers)}]: ")
    if idx is None:
        print_warning("Cancelled; nothing was changed.")
        return 1
    try:
        idx = int(idx) - 1
        if not (0 <= idx < len(providers)):
            print_error("Invalid selection.")
            return 2
    except ValueError:
        print_error(f"Please enter a number between 1 and {len(providers)}.")
        return 2

    new_provider = providers[idx]
    config["model"]["provider"] = new_provider

    # Show model list if available
    if new_provider in _MODEL_LISTS:
        models = _MODEL_LISTS[new_provider]
        print(f"\nModels for {_PROVIDER_DISPLAY[new_provider]}:")
        for i, (label, _name) in enumerate(models):
            print(f"  {i + 1}) {label}")
        print()
        model_idx = _ask(f"  Select a model [1-{len(models)}]: ")
        if model_idx is None:
            print_warning("Cancelled; nothing was changed.")
            return 1
        try:
            model_idx = int(model_idx) - 1
            if 0 <= model_idx < len(models):
                config["model"]["model"] = models[model_idx][1]
        except ValueError:
            print_error(f"Please enter a number between 1 and {len(models)}.")
            return 2

    if new_provider == "skip":
        config["model"]["model"] = ""

    save_config(config)

    # Also update env vars
    from .config import config_to_env_vars

    env_vars = config_to_env_vars(config)
    if env_vars:
        env_file = CONFIG_FILE.parent / ".env"
        with open(env_file, "w") as f:
            for k, v in sorted(env_vars.items()):
                if v:
                    f.write(f"{k}={v}\n")

    print_success(f"\nModel switched to {_PROVIDER_DISPLAY.get(new_provider, new_provider)}")
    if config.get("model", {}).get("model"):
        print_success(f"  Model: {config['model']['model']}")
    print()
    print_info(f"  Config saved to: {CONFIG_FILE}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_model_picker())
