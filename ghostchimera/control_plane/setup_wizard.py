"""Interactive setup wizard for Ghost Chimera.

Patterned after Hermes-Agent's `hermes setup` and OpenClaw's `openclaw setup`.
Modular wizard with independently-runnable sections.

Sections:
  1. Inference Provider — choose your AI provider and model
  2. Gateway Server — configure the messaging gateway (optional)
  3. Safety Policy — configure execution policy
  4. Summary & Config Write — display what was configured and persist it

If stdin is not a TTY, prints environment variable instructions instead.
"""

from __future__ import annotations

import getpass
import sys

from .colors import Colors, color, print_error, print_header, print_info, print_success, print_warning
from .config import (
    CONFIG_FILE,
    config_to_env_vars,
    ensure_state_dir,
    get_default_config,
    load_config,
    save_config,
)

_LOCAL_PROFILES = ["tiny", "balanced", "stronger"]


def is_interactive() -> bool:
    """Return True when stdin looks like a usable interactive TTY."""
    stdin = getattr(sys, "stdin", None)
    if stdin is None:
        return False
    try:
        return bool(stdin.isatty())
    except Exception:
        return False


def print_noninteractive_guidance() -> None:
    """Print guidance for headless/non-interactive setup flows."""
    print()
    print(color("Ghost Chimera Setup — Non-interactive mode", Colors.CYAN, True))
    print()
    print("The interactive wizard cannot be used here.")
    print()
    print("Configure Ghost Chimera using environment variables:")
    print()
    print("  # Choose a provider:")
    print("  export GHOSTCHIMERA_MODEL_PROVIDER=openrouter  # or openai/anthropic/local")
    print()
    print("  # OpenRouter (200+ models):")
    print('  export OPENAI_BASE_URL="https://openrouter.ai/api/v1"')
    print("  export OPENAI_API_KEY=sk-or-xxx")
    print()
    print("  # OpenAI:")
    print("  export OPENAI_API_KEY=sk-xxx")
    print('  export OPENAI_MODEL="gpt-4o"')
    print()
    print("  # Anthropic:")
    print("  export ANTHROPIC_API_KEY=sk-ant-xxx")
    print('  export ANTHROPIC_MODEL="claude-sonnet-4-6"')
    print()
    print("  # Local (runs entirely offline):")
    print('  export GHOSTCHIMERA_MODEL_PROVIDER=minimind')
    print('  export MINIMIND_MODEL_PROFILE=tiny')
    print()
    print("  # Or run 'ghostchimera setup' in an interactive terminal.")
    print()


def prompt(question: str, default: str = "", password: bool = False) -> str:
    """Prompt for input with optional default value."""
    if default:  # noqa: SIM108 — if/else is clearer than nested ternary
        display = f"{question} [{default}]: "
    else:
        display = f"{question}: "

    try:
        if password:  # noqa: SIM108 — if/else is clearer than nested ternary
            value = getpass.getpass(color(display, Colors.YELLOW))
        else:
            value = input(color(display, Colors.YELLOW))
        return value.strip() or default
    except (KeyboardInterrupt, EOFError):
        print()
        print_warning("Setup cancelled.")
        sys.exit(1)


def prompt_choice(question: str, choices: list[str], default: int = 0) -> int:
    """Prompt for a choice from a numbered list."""
    print()
    for i, choice in enumerate(choices):
        marker = ">" if i == default else " "
        if i == default:
            print(color(f"  {marker} {choice}", Colors.GREEN))
        else:
            print(f"  {marker} {choice}")

    print(f"  {Colors.DIM}Enter for default ({default + 1})  Ctrl+C to exit{Colors.RESET}")
    while True:
        try:
            value = input(color(f"  Select [1-{len(choices)}]: ", Colors.DIM))
            if not value:
                return default
            idx = int(value) - 1
            if 0 <= idx < len(choices):
                return idx
            print_error(f"Please enter a number between 1 and {len(choices)}")
        except ValueError:
            print_error("Please enter a number")
        except (KeyboardInterrupt, EOFError):
            print()
            print_warning("Setup cancelled.")
            sys.exit(1)


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt for yes/no. Default returned on empty input."""
    default_str = "Y/n" if default else "y/N"
    while True:
        try:
            value = (
                input(color(f"{question} [{default_str}]: ", Colors.YELLOW))
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            print()
            print_warning("Setup cancelled.")
            sys.exit(1)
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print_error("Please enter 'y' or 'n'")


# ──────────────────────────────────────────────────────────────────────
# Section 1: Inference Provider
# ──────────────────────────────────────────────────────────────────────

_PROVIDER_CHOICES = [
    "OpenAI API          — gpt-4o, gpt-3.5-turbo  (https://platform.openai.com/api-keys)",
    "OpenRouter          — 200+ models via unified API  (https://openrouter.ai/keys)",
    "Anthropic           — Claude models  (https://console.anthropic.com/keys)",
    "Custom endpoint     — Ollama, LM Studio, vLLM, any OpenAI-compatible server",
    "Local profile       — tiny/balanced/stronger, no API key needed",
    "Skip                — use deterministic backend only (for testing/hackathons)",
]

_PROVIDER_MODELS: dict[str, list[tuple[str, str]]] = {
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
    "local": [
        ("tiny (Qwen2.5 0.5B, 2GB RAM)", "tiny"),
        ("balanced (SmolLM2 1.7B, 4GB RAM)", "balanced"),
        ("stronger (Phi-3.5 mini, 6GB RAM)", "stronger"),
    ],
}

_PROVIDER_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

_PROVIDER_URLS: dict[str, str] = {
    "openai": "https://platform.openai.com/api-keys",
    "openrouter": "https://openrouter.ai/keys",
    "anthropic": "https://console.anthropic.com/keys",
}


def _setup_provider(config: dict) -> None:
    """Interactive provider selection."""
    print_header("Inference Provider")
    print_info("Ghost Chimera needs an AI model to reason with.")
    print_info("Choose how you'd like to connect:")
    print()

    idx = prompt_choice("Select a provider:", _PROVIDER_CHOICES, 0)

    providers = ["openai", "openrouter", "anthropic", "custom", "local", "skip"]
    provider = providers[idx]
    config["model"]["provider"] = provider

    if provider == "skip":
        config["model"]["model"] = ""
        print_success("Skipping — will use deterministic backend")
        return

    if provider == "custom":
        base_url = prompt("  Base URL (e.g. http://localhost:11434/v1)")
        if not base_url:
            base_url = "http://localhost:11434/v1"
        config["model"]["base_url"] = base_url

        model_name = prompt("  Model name (e.g. qwen3.6, llama3.1)", "")
        if model_name:
            config["model"]["model"] = model_name

        api_key_label = "  API key (optional, press Enter to skip)"
        api_key = getpass.getpass(color(api_key_label, Colors.YELLOW))
        if api_key:
            config["model"]["api_key"] = api_key

        print_success("Custom endpoint configured")
        return

    # Providers that need an API key
    key_var = _PROVIDER_KEYS.get(provider, "")
    key_url = _PROVIDER_URLS.get(provider, "")
    if key_var:
        print()
        print_info("  This provider requires an API key.")
        print_info(f"  Get your key at: {key_url}")
        print()
        key = getpass.getpass(color("  API key: ", Colors.YELLOW))
        if key:
            config["model"]["api_key"] = key
            env_var = _PROVIDER_KEYS[provider]
            print_success(f"  {env_var} saved to config")
        else:
            print_warning("  Skipped — will prompt for key at runtime")

    # Model selection
    if provider in _PROVIDER_MODELS:
        models = _PROVIDER_MODELS[provider]
        model_idx = prompt_choice("Select a model:", [m[0] for m in models], 0)
        config["model"]["model"] = models[model_idx][1]
        print_success(f"  Model: {models[model_idx][0]}")

    print()


# ──────────────────────────────────────────────────────────────────────
# Section 2: Gateway Server
# ──────────────────────────────────────────────────────────────────────

def _setup_gateway(config: dict) -> None:
    """Interactive gateway server configuration."""
    print_header("Gateway Server (optional)")
    print_info("Set up a local gateway for messaging platforms (Telegram, Discord, etc.)")
    print()

    if not prompt_yes_no("Configure gateway server?", False):
        return

    port_str = prompt("  Port number", str(config.get("gateway", {}).get("port", 8080)))
    try:
        port = int(port_str)
    except ValueError:
        port = 8080

    bind = prompt("  Bind address", "127.0.0.1")
    auth = prompt_choice(
        "  Auth mode:",
        ["None (no authentication)", "Token (API token)", "Password (username/password)"],
        1,
    )
    auth_modes = ["none", "token", "password"]
    auth = auth_modes[auth]

    config["gateway"] = {
        "port": port,
        "bind": bind,
        "auth": auth,
    }
    print_success("Gateway configured")
    print()


# ──────────────────────────────────────────────────────────────────────
# Section 3: Safety Policy
# ──────────────────────────────────────────────────────────────────────

def _setup_safety(config: dict) -> None:
    """Interactive safety policy configuration."""
    print_header("Safety Policy")
    print_info("Ghost Chimera defaults to conservative execution:")
    print()
    print_info("  - Shell execution: blocked by default")
    print_info("  - Network access: blocked by default")
    print_info("  - File access: blocked by default")
    print()

    safety = config.get("safety", {})
    safety.setdefault("allow_shell", False)
    safety.setdefault("allow_network", False)
    safety.setdefault("allow_file_read", False)
    safety.setdefault("allow_file_write", False)

    if prompt_yes_no("  Allow shell execution?", safety["allow_shell"]):
        safety["allow_shell"] = True
    if prompt_yes_no("  Allow network access?", safety["allow_network"]):
        safety["allow_network"] = True
    if prompt_yes_no("  Allow file reads?", safety["allow_file_read"]):
        safety["allow_file_read"] = True
    if prompt_yes_no("  Allow file writes?", safety["allow_file_write"]):
        safety["allow_file_write"] = True

    config["safety"] = safety
    print()


# ──────────────────────────────────────────────────────────────────────
# Section 4: Summary
# ──────────────────────────────────────────────────────────────────────

def _show_summary(config: dict) -> None:
    """Display setup summary and persist config."""
    print_header("Setup Summary")
    print()

    model = config.get("model", {})
    provider = model.get("provider", "skip")
    model_name = model.get("model", "")
    base_url = model.get("base_url", "")
    has_key = "api_key" in model

    if provider == "skip":
        print_success("  Provider: Deterministic backend (no AI model)")
    else:
        provider_display = provider.title()
        print(f"  Provider:      {Colors.GREEN}{provider_display}{Colors.RESET}")
        if model_name:
            print(f"  Model:         {Colors.GREEN}{model_name}{Colors.RESET}")
        if base_url:
            print(f"  Base URL:      {Colors.GREEN}{base_url}{Colors.RESET}")
        print(f"  API Key:       {Colors.GREEN}configured{Colors.RESET}" if has_key else "  API Key:       {Colors.DIM}not set{Colors.RESET}")

    gateway = config.get("gateway", {})
    gw_port = gateway.get("port", 8080)
    gw_bind = gateway.get("bind", "127.0.0.1")
    gw_auth = gateway.get("auth", "token")
    print(f"  Gateway:       {Colors.GREEN}enabled{Colors.RESET} ({gw_bind}:{gw_port}, auth={gw_auth})")

    safety = config.get("safety", {})
    shell = "yes" if safety.get("allow_shell") else "no"
    network = "yes" if safety.get("allow_network") else "no"
    freader = "yes" if safety.get("allow_file_read") else "no"
    fwriter = "yes" if safety.get("allow_file_write") else "no"
    print(f"  Safety:        shell={shell}, network={network}, read={freader}, write={fwriter}")

    print()
    print(color("═" * 50, Colors.DIM))
    print()
    print_success("  Setup complete!")
    print()
    print_info(f"  Config saved to: {CONFIG_FILE}")
    print()
    print_info("  To start chatting:")
    print_info("    ghostchimera")
    print()
    print_info("  To check your setup:")
    print_info("    ghostchimera doctor")
    print()


def run_setup_wizard() -> None:
    """Run the full interactive setup wizard."""
    if not is_interactive():
        print_noninteractive_guidance()
        return

    print()
    print(color("Ghost Chimera Setup Wizard", Colors.CYAN, True))
    print(color("═" * 50, Colors.DIM))
    print()
    print_info("This wizard will configure Ghost Chimera step by step.")
    print_info("You can always re-run 'ghostchimera setup' later to change anything.")
    print()

    ensure_state_dir()

    # Load existing config if present
    existing = load_config()
    if existing:
        print_info("Existing configuration detected.")
        print()
        action = prompt_choice(
            "What would you like to do?",
            ["Use existing values as defaults", "Start fresh (reset)"],
            0,
        )
        if action == 0:
            config = existing
        else:
            config = get_default_config()
            print_info("Configuration reset.")
    else:
        config = get_default_config()

    # Run sections
    _setup_provider(config)

    # Show gateway if provider is configured
    if config.get("model", {}).get("provider", ""):
        _setup_gateway(config)

    # Safety policy
    _setup_safety(config)

    # Summary and persist
    _show_summary(config)

    # Write config
    save_config(config)

    # Also write env vars for legacy consumers
    env_vars = config_to_env_vars(config)
    env_file = CONFIG_FILE.parent / ".env"
    if env_vars:
        with open(env_file, "w") as f:
            for k, v in sorted(env_vars.items()):
                if v:
                    f.write(f"{k}={v}\n")
        print_info(f"  Env vars written to: {env_file}")

    print()


if __name__ == "__main__":
    run_setup_wizard()
