"""Health check (doctor) for Ghost Chimera.

Checks Python version, config, providers, backends, state directory, and
skill requirements (Gap 4 — OpenClaw-style ``check_requirements()``).
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any

from ..model_layer.providers import get_provider
from ..safety_layer.production import ProductionGuardrails
from .colors import Colors, color, print_error, print_header, print_info, print_success, print_warning
from .config import CONFIG_FILE, config_to_env_vars, ensure_state_dir, load_config


def _check(label: str, ok: bool, hint: str = "") -> None:
    if ok:
        print_success(f"  [OK] {label}")
    elif hint:
        print_warning(f"  [WARN] {label} - {hint}")
    else:
        print_error(f"  [ERR]  {label}")


def _provider_status(config: dict[str, object], env: dict[str, str] | None = None) -> tuple[str, bool, str]:
    """Resolve provider status from env-first deployment config, then setup config."""

    active_env = env or dict(os.environ)
    env_provider = str(active_env.get("GHOSTCHIMERA_MODEL_PROVIDER", "")).strip().lower()
    if env_provider:
        provider = get_provider(env_provider)
        if provider is None:
            return (f"Provider: {env_provider}", False, "Unknown provider configured in GHOSTCHIMERA_MODEL_PROVIDER")
        errors = provider.validate_config()
        hint = "; ".join(errors[:2]) if errors else ""
        return (f"Provider: {provider.name} (env)", provider.available and not errors, hint)

    model = config.get("model", {}) if isinstance(config, dict) else {}
    if not isinstance(model, dict):
        model = {}
    provider_name = str(model.get("provider", "")).strip().lower()
    if provider_name == "skip":
        return ("Provider: Deterministic backend", True, "")
    if provider_name:
        env_overlay = {**active_env, **config_to_env_vars(config)}
        resolved_name = str(env_overlay.get("GHOSTCHIMERA_MODEL_PROVIDER", provider_name)).strip().lower()
        provider = get_provider(resolved_name)
        if provider is not None:
            errors = provider.validate_config()
            hint = "; ".join(errors[:2]) if errors else ""
            return (f"Provider: {provider.name} (config)", provider.available and not errors, hint)
        has_key = "api_key" in model
        return (f"Provider: {provider_name.title()} (model: {model.get('model', '?')})", has_key, "API key not set")
    return ("Provider", False, "No provider configured - run 'ghostchimera setup' or set GHOSTCHIMERA_MODEL_PROVIDER")


def doctor_checks(*, production: bool = False) -> dict[str, Any]:
    """Run health checks and return a JSON-serializable payload (no printing).

    This is the same check suite ``run_doctor`` prints, exposed as data so the
    browser console can surface ``ghostchimera doctor`` without a terminal.
    """
    checks: list[dict[str, Any]] = []
    passed = 0
    warned = 0
    errors = 0

    def record(label: str, ok: bool, hint: str = "") -> None:
        checks.append({"label": label, "ok": bool(ok), "hint": hint})

    def tally(ok: bool, *, warn: bool = False) -> None:
        nonlocal passed, warned, errors
        if ok:
            passed += 1
        elif warn:
            warned += 1
        else:
            errors += 1

    def payload() -> dict[str, Any]:
        return {
            "ok": errors == 0,
            "passed": passed,
            "warned": warned,
            "errors": errors,
            "checks": checks,
        }

    # Python version
    ok = sys.version_info >= (3, 11)
    record(
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ok,
        "Requires 3.11+",
    )
    tally(ok)
    if not ok:
        return payload()  # Can't continue without Python 3.11+

    # Config file
    config = load_config()
    if config:
        record(f"Config exists at {CONFIG_FILE}", True)
        passed += 1
    else:
        record("Config file", False, "Run 'ghostchimera setup' to configure")
        warned += 1

    # Provider status
    provider_label, provider_ok, provider_hint = _provider_status(config)
    record(provider_label, provider_ok, provider_hint)
    tally(provider_ok, warn=True)

    # Gateway
    gateway = config.get("gateway", {})
    if gateway:
        gw_port = gateway.get("port", "??")
        record(f"Gateway configured ({gateway.get('bind', '?')}:{gw_port})", True)
        passed += 1
    else:
        record("Gateway", True, "Not configured (optional)")
        passed += 1

    # Safety
    safety = config.get("safety", {})
    if safety:
        shell = "yes" if safety.get("allow_shell") else "no"
        net = "yes" if safety.get("allow_network") else "no"
        fr = "yes" if safety.get("allow_file_read") else "no"
        fw = "yes" if safety.get("allow_file_write") else "no"
        record(f"Safety: shell={shell}, network={net}, read={fr}, write={fw}", True)
        passed += 1
    else:
        record("Safety", True, "Using defaults (all deny)")
        passed += 1

    autonomy = config.get("autonomy", {})
    level = autonomy.get("level", "supervised") if isinstance(autonomy, dict) else "supervised"
    try:
        from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile
        from ghostchimera.model_layer.minimind_lifecycle import MiniMindLifecycle

        profile = get_autonomy_profile(str(level))
        record(f"Autonomy profile: {profile.name}", True)
        passed += 1
        minimind = MiniMindLifecycle(profile_name=profile.local_model_profile).status()
        minimind_hint = "; ".join(minimind.errors or minimind.notes)
        minimind_ok = minimind.available and not minimind.errors
        record(f"MiniMind architecture/runtime: {minimind.runtime_hint}", minimind_ok, minimind_hint)
        tally(minimind_ok, warn=True)
    except Exception as exc:
        record("Autonomy/MiniMind status", False, f"Could not check ({exc})")
        warned += 1

    # State directory
    state_dir = CONFIG_FILE.parent
    try:
        ensure_state_dir(state_dir)
        record(f"State directory writable ({state_dir})", True)
        passed += 1
    except OSError:
        record(f"State directory ({state_dir})", False)
        errors += 1

    # Deterministic backend (always available)
    try:
        importlib.util.find_spec("ghostchimera.chimera_pilot.backends.deterministic")
        record("Deterministic backend", True)
        passed += 1
    except ImportError:
        record("Deterministic backend", False, "chmera_pilot not installed")
        errors += 1

    # Skill requirement checks (Gap 4 — OpenClaw-style check_requirements())
    try:
        from ghostchimera.skill_layer.registry import get_registry as get_skill_registry

        registry = get_skill_registry()
        skill_problems: list[str] = []
        for _skill_name, skill in registry.list_skills().items():
            if hasattr(skill, "check_requirements"):
                problems = skill.check_requirements()
                skill_problems.extend(problems)
        if skill_problems:
            for problem in skill_problems:
                record(f"Skill requirement: {problem}", False, "")
            errors += len(skill_problems)
        else:
            record("Skill requirements", True)
            passed += 1
    except Exception as exc:
        record("Skill requirements", False, f"Could not check ({exc})")
        warned += 1

    if production:
        guardrails = ProductionGuardrails.from_env()
        if guardrails.is_production:
            record("Production mode", True)
            passed += 1
        else:
            record("Production mode", False, "Set GHOSTCHIMERA_DEPLOYMENT_MODE=production")
            errors += 1
        for requirement in guardrails.requirement_rows():
            req_ok = bool(requirement["ok"])
            record(f"Production guardrail: {requirement['name']}", req_ok, requirement["remediation"])
            tally(req_ok)

    return payload()


def run_doctor(*, production: bool = False) -> int:
    """Run health checks and report status."""
    print_header("Ghost Chimera Doctor")
    print()

    payload = doctor_checks(production=production)
    for check in payload["checks"]:
        _check(check["label"], check["ok"], check["hint"])

    print()
    print(color("=" * 50, Colors.DIM))
    print()
    print(f"  Result: {payload['passed']} passed, {payload['warned']} warnings, {payload['errors']} errors")
    print()
    if payload["errors"] > 0:
        print_info("Run 'ghostchimera setup' to fix configuration issues.")
    print()
    return 0 if payload["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run_doctor())
