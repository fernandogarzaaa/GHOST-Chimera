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
import logging
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
    parser = argparse.ArgumentParser(description="Ghost Chimera CLI")
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
    parser.add_argument("--include-quantum-backend", action="store_true", help="Probe and register optional pyqpanda3 backend if installed.")
    parser.add_argument("--config-show", action="store_true", help="Print resolved Ghost Chimera runtime config as JSON and exit.")
    args = parser.parse_args(argv)
    ensure_configured()
    logger.info("CLI started with log_level=%s", args.log_level)

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
