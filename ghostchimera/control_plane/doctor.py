"""Health check (doctor) for Ghost Chimera.

Checks Python version, config, providers, backends, and state directory.
"""

from __future__ import annotations

import importlib
import sys

from .colors import Colors, color, print_error, print_header, print_info, print_success, print_warning
from .config import CONFIG_FILE, ensure_state_dir, load_config


def _check(label: str, ok: bool, hint: str = "") -> None:
    if ok:
        print_success(f"  [OK] {label}")
    elif hint:
        print_warning(f"  [WARN] {label} — {hint}")
    else:
        print_error(f"  [ERR]  {label}")


def run_doctor() -> None:
    """Run health checks and report status."""
    print_header("Ghost Chimera Doctor")
    print()

    passed = 0
    warned = 0
    errors = 0

    # Python version
    ok = sys.version_info >= (3, 11)
    _check(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", ok, "Requires 3.11+")
    if ok:
        passed += 1
    else:
        errors += 1
        return  # Can't continue without Python 3.11+

    # Config file
    config = load_config()
    if config:
        _check(f"Config exists at {CONFIG_FILE}")
        passed += 1
    else:
        _check("Config file", False, "Run 'ghostchimera setup' to configure")
        warned += 1

    # Provider status
    model = config.get("model", {})
    provider = model.get("provider", "")

    if provider == "skip":
        _check("Provider: Deterministic backend", True)
        passed += 1
    elif provider:
        has_key = "api_key" in model
        _check(f"Provider: {provider.title()} (model: {model.get('model', '?')})", has_key, "API key not set")
        if has_key:
            passed += 1
        else:
            warned += 1
    else:
        _check("Provider", False, "No provider configured — run 'ghostchimera setup'")
        warned += 1

    # Gateway
    gateway = config.get("gateway", {})
    if gateway:
        gw_port = gateway.get("port", "??")
        _check(f"Gateway configured ({gateway.get('bind', '?')}:{gw_port})", True)
        passed += 1
    else:
        _check("Gateway", True, "Not configured (optional)")
        passed += 1

    # Safety
    safety = config.get("safety", {})
    if safety:
        shell = "yes" if safety.get("allow_shell") else "no"
        net = "yes" if safety.get("allow_network") else "no"
        fr = "yes" if safety.get("allow_file_read") else "no"
        fw = "yes" if safety.get("allow_file_write") else "no"
        _check(f"Safety: shell={shell}, network={net}, read={fr}, write={fw}", True)
        passed += 1
    else:
        _check("Safety", True, "Using defaults (all deny)")
        passed += 1

    # State directory
    state_dir = CONFIG_FILE.parent
    try:
        ensure_state_dir(state_dir)
        _check(f"State directory writable ({state_dir})", True)
        passed += 1
    except OSError:
        _check(f"State directory ({state_dir})", False)
        errors += 1

    # Deterministic backend (always available)
    try:
        importlib.util.find_spec("ghostchimera.chimera_pilot.backends.deterministic")
        _check("Deterministic backend", True)
        passed += 1
    except ImportError:
        _check("Deterministic backend", False, "chmera_pilot not installed")
        errors += 1

    print()
    print(color("═" * 50, Colors.DIM))
    print()
    print(f"  Result: {passed} passed, {warned} warnings, {errors} errors")
    print()
    if errors > 0:
        print_info("Run 'ghostchimera setup' to fix configuration issues.")
    print()


if __name__ == "__main__":
    run_doctor()
