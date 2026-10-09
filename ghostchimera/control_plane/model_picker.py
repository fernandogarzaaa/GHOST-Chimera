"""Model picker for Ghost Chimera.

Lists configured providers and lets the user switch the current model.
"""

from __future__ import annotations

from .colors import Colors, color, print_error, print_header, print_info, print_success, print_warning
from .config import CONFIG_FILE, load_config, save_config


def _opencode_cli_model_list() -> list[tuple[str, str]]:
    """Build the OpenCode free-model choices from the provider's live list.

    Generated from ghostchimera.model_layer.opencode_cli_provider.KNOWN_FREE_MODELS
    so the picker never offers a stale hardcoded free-model list.
    """

    from ..model_layer.opencode_cli_provider import KNOWN_FREE_MODELS

    return [(f"{free_model} (free)", free_model) for free_model in KNOWN_FREE_MODELS] + [("Use a different model", "")]


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
    # NOTE: "opencode_cli" is intentionally absent here; its model list is
    # generated at selection time by _opencode_cli_model_list().
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


def run_model_picker() -> None:
    """List providers and let the user switch the current model."""
    print_header("Ghost Chimera — Model Picker")
    print()

    config = load_config()
    model = config.get("model", {})
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
    providers = ["openai", "openrouter", "anthropic", "nebius", "custom", "local", "opencode_cli", "skip"]
    provider_labels = [f"{_PROVIDER_DISPLAY.get(p, p).title()}" for p in providers]

    print("Available providers:")
    for idx, label in enumerate(provider_labels):
        provider = providers[idx]
        marker = ">" if provider == current_provider else " "
        current = " (current)" if provider == current_provider else ""
        if provider == current_provider:
            print(color(f"  {marker} {label}{current}", Colors.GREEN))
        else:
            print(f"  {marker} {label}{current}")
    print()

    # Switch provider
    idx = input(f"  Select a provider [1-{len(providers)}]: ").strip()
    try:
        idx = int(idx) - 1
        if not (0 <= idx < len(providers)):
            print_error("Invalid selection.")
            return
    except ValueError:
        print_error(f"Please enter a number between 1 and {len(providers)}.")
        return

    new_provider = providers[idx]
    config["model"]["provider"] = new_provider

    if new_provider == "opencode_cli":
        from ..model_layer.opencode_cli_provider import (
            FREE_TIER_DATA_USE_NOTICE,
            opencode_setup_guidance,
        )

        print()
        for line in opencode_setup_guidance():
            print_warning(line)
        print_warning(FREE_TIER_DATA_USE_NOTICE)

    # Show model list if available
    models = _opencode_cli_model_list() if new_provider == "opencode_cli" else _MODEL_LISTS.get(new_provider, [])
    if models:
        print(f"\nModels for {_PROVIDER_DISPLAY[new_provider]}:")
        for i, (label, _name) in enumerate(models):
            print(f"  {i + 1}) {label}")
        print()
        model_idx = input(f"  Select a model [1-{len(models)}]: ").strip()
        try:
            model_idx = int(model_idx) - 1
            if 0 <= model_idx < len(models):
                config["model"]["model"] = models[model_idx][1]
        except ValueError:
            print_error(f"Please enter a number between 1 and {len(models)}.")
            return

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


if __name__ == "__main__":
    run_model_picker()
