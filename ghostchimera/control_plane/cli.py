"""
CLI Control Plane
=================

Provides a command line interface for interacting with Ghost Chimera.  This
module can be used both as a library and as a script (``python -m
ghostchimera.control_plane.cli``).  It instantiates an :class:`AgentCore`
and processes user input in a loop until the user types ``exit`` or
``quit``.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..agent_core.core import AgentCore
from ..config import GhostChimeraConfig
from ..logging_config import ensure_configured, get_logger

logger = get_logger("cli")


def run_cli() -> None:
    """Start an interactive command line session with the agent."""
    ensure_configured()
    agent = AgentCore()
    logger.info("Starting interactive CLI session")
    print("Ghost Chimera CLI. Type 'exit' or 'quit' to stop.")
    while True:
        try:
            request = input("≫ ").strip()
        except EOFError:
            print()
            break
        if request.lower() in {"exit", "quit"}:
            break
        if not request:
            continue
        try:
            result = agent.handle_request(request)
            print(result)
        except Exception as exc:
            print(f"Error: {exc}")


def _main(argv: list[str] | None = None) -> int:
    # If parallel flags are present, delegate to parallel_cli
    if argv and ("run" in argv or "batch" in argv):
        from .parallel_cli import _main as _parallel_main
        return _parallel_main(argv)

    parser = argparse.ArgumentParser(description="Ghost Chimera CLI")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup", help="Run interactive setup wizard")
    sub.add_parser("doctor", help="Run health checks and report status")
    sub.add_parser("model", help="List and switch the current model provider")
    sub.add_parser("policy", help="Manage security policies")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity",
    )
    parser.add_argument(
        "--pilot-status",
        action="store_true",
        help="Print Chimera Pilot backend status as JSON and exit.",
    )
    parser.add_argument(
        "--pilot-run",
        default="",
        help="Run one objective through Chimera Pilot and exit.",
    )
    parser.add_argument("--pilot-cwd", default="", help="Allowed working directory for Chimera Pilot local execution.")
    parser.add_argument("--allow-python", action="store_true", help="Allow Chimera Pilot local Python/test execution.")
    parser.add_argument("--allow-network", action="store_true", help="Allow Chimera Pilot network-requiring tasks.")
    parser.add_argument("--allow-desktop-control", action="store_true", help="Allow Chimera Pilot desktop control tasks.")
    parser.add_argument("--enable-desktop-backend", action="store_true", help="Register Chimera Pilot desktop backend (dry-run).")
    parser.add_argument("--enable-live-desktop", action="store_true", help="Enable live desktop backend mode.")
    parser.add_argument("--desktop-kill-switch-path", default="", help="If file exists, desktop actions are blocked.")
    parser.add_argument("--desktop-action-log-path", default="", help="JSONL log path for desktop actions.")
    parser.add_argument("--desktop-max-actions", type=int, default=25, help="Maximum live desktop actions per backend session.")
    parser.add_argument("--desktop-max-duration-seconds", type=float, default=300.0, help="Maximum live desktop session duration.")
    parser.add_argument(
        "--ghost-mode",
        default="",
        choices=["", "whisper", "haunt", "possess"],
        help="Ghost operation mode: whisper (suggest), haunt (observe), possess (act).",
    )
    parser.add_argument("--include-quantum-backend", action="store_true", help="Probe and register optional pyqpanda3 backend if installed.")
    parser.add_argument("--config-show", action="store_true", help="Print resolved Ghost Chimera runtime config as JSON and exit.")
    args = parser.parse_args(argv)
    if args.ghost_mode:
        import os

        os.environ["GHOSTCHIMERA_GHOST_MODE"] = args.ghost_mode
    ensure_configured()
    logger.info("CLI started with log_level=%s", args.log_level)

    # Dispatch subcommands
    if args.command == "setup":
        from .setup_wizard import run_setup_wizard

        run_setup_wizard()
        return 0

    if args.command == "doctor":
        from .doctor import run_doctor

        run_doctor()
        return 0

    if args.command == "model":
        from .model_picker import run_model_picker

        run_model_picker()
        return 0

    if args.command == "policy":
        from .cli_policy import _main as _policy_main

        return _policy_main()

    if args.config_show:
        print(json.dumps(GhostChimeraConfig.from_env().to_dict(), indent=2, sort_keys=True))
        return 0

    if args.pilot_status or args.pilot_run:
        from ..chimera_pilot import ChimeraPilotKernel

        kernel = ChimeraPilotKernel.default(
            include_deterministic_backend=args.pilot_status,
            include_quantum_backend=args.include_quantum_backend,
            cwd=args.pilot_cwd or None,
            allow_python_execution=args.allow_python,
            allow_network=args.allow_network,
            allow_desktop_control=args.allow_desktop_control,
            enable_desktop_backend=args.enable_desktop_backend,
            enable_live_desktop=args.enable_live_desktop,
            desktop_kill_switch_path=args.desktop_kill_switch_path or None,
            desktop_action_log_path=args.desktop_action_log_path or None,
            desktop_max_live_actions=args.desktop_max_actions,
            desktop_max_session_seconds=args.desktop_max_duration_seconds,
            ghost_mode=args.ghost_mode or "whisper",
        )
        if args.pilot_status:
            print(json.dumps(kernel.status(), indent=2, sort_keys=True))
            return 0
        try:
            executions = kernel.run(args.pilot_run)
        except PermissionError as exc:
            print(json.dumps({"ok": False, "error": str(exc), "policy": kernel.policy.to_dict()}, indent=2, sort_keys=True))
            return 1
        payload = [execution.to_dict() for execution in executions]
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if all(item["ok"] for item in payload) else 1

    run_cli()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
