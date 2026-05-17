"""
Configuration Validator for Ghost Chimera.

Validates environment variables and configuration settings for production deployments.
Part of IBM Bob Phase 1: Developer Tools.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def parse_env_file(env_file_path: Path) -> dict[str, str]:
    """
    Parse a .env file into a dictionary.

    Args:
        env_file_path: Path to .env file

    Returns:
        Dictionary of environment variables
    """
    env_vars = {}

    if not env_file_path.exists():
        return env_vars

    try:
        content = env_file_path.read_text(encoding="utf-8")
        for line in content.split("\n"):
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Parse KEY=VALUE
            if "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()

    except Exception as e:
        print(f"Warning: Error parsing env file: {e}", file=sys.stderr)

    return env_vars


def redact_secret(value: str) -> str:
    """
    Redact a secret value for safe display.

    Args:
        value: Secret value to redact

    Returns:
        Redacted string
    """
    if not value:
        return "[NOT SET]"
    if len(value) <= 4:
        return "[REDACTED]"
    return f"{value[:2]}...{value[-2:]} [REDACTED]"


def _truthy(value: str | None) -> bool:
    """Return True for boolean-like env values used by Ghost Chimera."""
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _placeholder(value: str) -> bool:
    """Return True for example values that must not pass production validation."""
    lowered = value.strip().lower()
    return not lowered or any(marker in lowered for marker in ("replace-with", "changeme", "example", "placeholder"))


def validate_config(env_vars: dict[str, str], production_mode: bool = False) -> dict[str, Any]:
    """
    Validate Ghost Chimera configuration.

    Args:
        env_vars: Dictionary of environment variables
        production_mode: Whether to enforce production guardrails

    Returns:
        Validation results dictionary
    """
    results = {"valid": True, "errors": [], "warnings": [], "checks": []}

    # Check deployment mode
    deployment_mode = env_vars.get("GHOSTCHIMERA_DEPLOYMENT_MODE", "")
    results["checks"].append(
        {
            "name": "GHOSTCHIMERA_DEPLOYMENT_MODE",
            "value": deployment_mode or "[NOT SET]",
            "status": "OK" if deployment_mode else "WARNING",
        }
    )

    if not deployment_mode:
        results["warnings"].append("GHOSTCHIMERA_DEPLOYMENT_MODE not set")

    # Check external isolation
    external_isolation = env_vars.get("GHOSTCHIMERA_EXTERNAL_ISOLATION", "").strip().lower()
    valid_isolation_modes = {"container", "vm", "service-account", "sandboxed"}
    results["checks"].append(
        {
            "name": "GHOSTCHIMERA_EXTERNAL_ISOLATION",
            "value": external_isolation or "[NOT SET]",
            "status": "OK" if external_isolation in valid_isolation_modes else "WARNING",
        }
    )

    if production_mode and external_isolation not in valid_isolation_modes:
        results["errors"].append(
            "GHOSTCHIMERA_EXTERNAL_ISOLATION must be container, vm, service-account, or sandboxed in production"
        )
        results["valid"] = False

    # Check security reviewed
    security_reviewed = env_vars.get("GHOSTCHIMERA_SECURITY_REVIEWED", "")
    security_reviewed_ok = _truthy(security_reviewed)
    results["checks"].append(
        {
            "name": "GHOSTCHIMERA_SECURITY_REVIEWED",
            "value": security_reviewed or "[NOT SET]",
            "status": "OK" if security_reviewed_ok else "WARNING",
        }
    )

    if production_mode and not security_reviewed_ok:
        results["errors"].append("GHOSTCHIMERA_SECURITY_REVIEWED must be truthy in production")
        results["valid"] = False

    # Check human approval required
    human_approval = env_vars.get("GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED", "")
    human_approval_ok = _truthy(human_approval)
    results["checks"].append(
        {
            "name": "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED",
            "value": human_approval or "[NOT SET]",
            "status": "OK" if human_approval_ok else "WARNING",
        }
    )

    if production_mode and not human_approval_ok:
        results["errors"].append("GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED must be truthy in production")
        results["valid"] = False

    # Check allow untrusted inputs
    allow_untrusted = env_vars.get("GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS", "")
    trusted_inputs_only = not _truthy(allow_untrusted)
    results["checks"].append(
        {
            "name": "GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS",
            "value": allow_untrusted or "[NOT SET]",
            "status": "OK" if trusted_inputs_only else "WARNING",
        }
    )

    if production_mode and not trusted_inputs_only:
        results["errors"].append("GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS must be unset or falsey in production")
        results["valid"] = False

    # Check console auth token (presence only, never value)
    console_token = env_vars.get("GHOSTCHIMERA_CONSOLE_AUTH_TOKEN", "")
    token_status = "OK" if console_token else "WARNING"
    results["checks"].append(
        {"name": "GHOSTCHIMERA_CONSOLE_AUTH_TOKEN", "value": redact_secret(console_token), "status": token_status}
    )

    if production_mode and not console_token:
        results["errors"].append("GHOSTCHIMERA_CONSOLE_AUTH_TOKEN must be set in production")
        results["valid"] = False
    elif production_mode and _placeholder(console_token):
        results["errors"].append("GHOSTCHIMERA_CONSOLE_AUTH_TOKEN must not use an example or placeholder value")
        results["valid"] = False

    # Check Vultr API key (presence only, never value)
    vultr_key = env_vars.get("VULTR_INFERENCE_API_KEY", "")
    vultr_key_status = "OK" if vultr_key else "WARNING"
    results["checks"].append(
        {"name": "VULTR_INFERENCE_API_KEY", "value": redact_secret(vultr_key), "status": vultr_key_status}
    )

    if not vultr_key:
        results["warnings"].append("VULTR_INFERENCE_API_KEY not set (required for Vultr inference)")

    # Check Vultr model
    vultr_model = env_vars.get("VULTR_INFERENCE_MODEL", "")
    results["checks"].append(
        {
            "name": "VULTR_INFERENCE_MODEL",
            "value": vultr_model or "[NOT SET]",
            "status": "OK" if vultr_model else "WARNING",
        }
    )

    if not vultr_model:
        results["warnings"].append("VULTR_INFERENCE_MODEL not set")

    # Check Vultr base URL
    vultr_url = env_vars.get("VULTR_INFERENCE_BASE_URL", "")
    results["checks"].append(
        {
            "name": "VULTR_INFERENCE_BASE_URL",
            "value": vultr_url or "[NOT SET]",
            "status": "OK" if vultr_url else "WARNING",
        }
    )

    if not vultr_url:
        results["warnings"].append("VULTR_INFERENCE_BASE_URL not set")

    return results


def format_text(results: dict[str, Any]) -> str:
    """Format validation results as text."""
    lines = ["Ghost Chimera Configuration Validation", "=" * 50, ""]

    # Overall status
    status = "VALID" if results["valid"] else "INVALID"
    lines.append(f"Overall Status: {status}")
    lines.append("")

    # Checks
    lines.append("Configuration Checks:")
    lines.append("-" * 50)
    for check in results["checks"]:
        status_marker = "OK" if check["status"] == "OK" else "FAIL" if check["status"] == "ERROR" else "WARN"
        lines.append(f"[{status_marker}] {check['name']}: {check['value']}")
    lines.append("")

    # Errors
    if results["errors"]:
        lines.append("Errors:")
        for error in results["errors"]:
            lines.append(f"  - {error}")
        lines.append("")

    # Warnings
    if results["warnings"]:
        lines.append("Warnings:")
        for warning in results["warnings"]:
            lines.append(f"  - {warning}")
        lines.append("")

    return "\n".join(lines)


def format_json_output(results: dict[str, Any]) -> str:
    """Format validation results as JSON."""
    return json.dumps(results, indent=2)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate Ghost Chimera configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate current environment
  python scripts/validate_config.py

  # Validate a specific env file
  python scripts/validate_config.py --env-file .env.vultr.example

  # Validate for production (strict mode)
  python scripts/validate_config.py --env-file .env.production --production

  # Output as JSON
  python scripts/validate_config.py --format json
        """,
    )

    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text)")
    parser.add_argument("--env-file", help="Path to .env file to validate")
    parser.add_argument("--production", action="store_true", help="Enable production mode (strict validation)")

    args = parser.parse_args()

    # Load environment variables
    env_vars = {}
    if args.env_file:
        env_file_path = Path(args.env_file)
        if not env_file_path.exists():
            print(f"Error: Env file not found: {args.env_file}", file=sys.stderr)
            return 1
        env_vars = parse_env_file(env_file_path)
    else:
        # Use current environment
        import os

        env_vars = dict(os.environ)

    # Validate configuration
    results = validate_config(env_vars, production_mode=args.production)

    # Format and print output
    output = format_json_output(results) if args.format == "json" else format_text(results)

    print(output)

    # Return non-zero exit code for production errors
    if args.production and not results["valid"]:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
