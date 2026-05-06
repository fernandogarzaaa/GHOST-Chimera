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
from .config import get_autonomy_config, load_config, save_config

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
    doctor_parser = sub.add_parser("doctor", help="Run health checks and report status")
    doctor_parser.add_argument("--production", action="store_true", help="Require production deployment guardrails.")
    sub.add_parser("model", help="List and switch the current model provider")
    sub.add_parser("policy", help="Manage security policies")
    autonomy_parser = sub.add_parser("autonomy", help="Show, set, and run autonomy controls")
    autonomy_parser.add_argument("action", choices=["show", "set", "jobs", "run"], nargs="?", default="show")
    autonomy_parser.add_argument("job", nargs="?", default="", help="Job name for 'run'")
    autonomy_parser.add_argument("--level", choices=["assist", "supervised", "autonomous", "generalist", "agi", "sgi"])
    autonomy_parser.add_argument("--max-tool-rounds", type=int)
    autonomy_parser.add_argument("--max-parallel-tasks", type=int)
    autonomy_parser.add_argument("--local-model-profile", choices=["tiny", "balanced", "stronger"])
    autonomy_parser.add_argument("--execute", action="store_true", help="Allow jobs that otherwise return preview-only plans.")
    minimind_parser = sub.add_parser("minimind", help="Inspect MiniMind local runtime support")
    minimind_parser.add_argument("action", choices=["status", "dataset", "log-failure"], nargs="?", default="status")
    minimind_parser.add_argument("--profile", default="", help="MiniMind/local model profile.")
    minimind_parser.add_argument("--output", default="", help="Output JSONL path.")
    minimind_parser.add_argument("--prompt", default="", help="Prompt/instruction text.")
    minimind_parser.add_argument("--response", default="", help="Response/output text.")
    minimind_parser.add_argument("--confidence", type=float, default=0.0)
    minimind_parser.add_argument("--threshold", type=float, default=0.5)
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
    parser.add_argument(
        "--desktop-action-class",
        action="append",
        choices=["read_only", "mutating", "destructive"],
        help="Desktop action class to allow. Repeat to allow multiple classes.",
    )
    parser.add_argument("--enable-desktop-backend", action="store_true", help="Register Chimera Pilot desktop backend (dry-run).")
    parser.add_argument("--enable-live-desktop", action="store_true", help="Enable live desktop backend mode.")
    parser.add_argument("--desktop-kill-switch-path", default="", help="If file exists, desktop actions are blocked.")
    parser.add_argument("--desktop-action-log-path", default="", help="JSONL log path for desktop actions.")
    parser.add_argument("--desktop-screenshot-dir", default="", help="Directory for live desktop before/after screenshots.")
    parser.add_argument("--desktop-max-actions", type=int, default=25, help="Maximum live desktop actions per backend session.")
    parser.add_argument("--desktop-max-duration-seconds", type=float, default=300.0, help="Maximum live desktop session duration.")
    parser.add_argument(
        "--ghost-mode",
        default="",
        choices=["", "whisper", "haunt", "possess"],
        help="Ghost operation mode: whisper (suggest), haunt (observe), possess (act).",
    )
    parser.add_argument("--include-quantum-backend", action="store_true", help="Probe and register optional pyqpanda3 backend if installed.")
    parser.add_argument("--autonomy-level", default="", help="Autonomy profile: assist, supervised, autonomous, or generalist.")
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

        return run_doctor(production=args.production)

    if args.command == "model":
        from .model_picker import run_model_picker

        run_model_picker()
        return 0

    if args.command == "policy":
        from .cli_policy import _main as _policy_main

        return _policy_main()

    if args.command == "autonomy":
        return _run_autonomy_cli(args)

    if args.command == "minimind":
        return _run_minimind_cli(args)

    if args.config_show:
        print(json.dumps(GhostChimeraConfig.from_env().to_dict(), indent=2, sort_keys=True))
        return 0

    if args.pilot_status or args.pilot_run:
        from ..chimera_pilot import ChimeraPilotKernel

        persisted_autonomy = get_autonomy_config(load_config())
        autonomy_level = args.autonomy_level or str(persisted_autonomy.get("level") or "supervised")
        kernel = ChimeraPilotKernel.default(
            include_deterministic_backend=args.pilot_status,
            include_quantum_backend=args.include_quantum_backend,
            cwd=args.pilot_cwd or None,
            allow_python_execution=args.allow_python,
            allow_network=args.allow_network,
            allow_desktop_control=args.allow_desktop_control,
            desktop_action_classes=args.desktop_action_class,
            enable_desktop_backend=args.enable_desktop_backend,
            enable_live_desktop=args.enable_live_desktop,
            desktop_kill_switch_path=args.desktop_kill_switch_path or None,
            desktop_action_log_path=args.desktop_action_log_path or None,
            desktop_screenshot_dir=args.desktop_screenshot_dir or None,
            desktop_max_live_actions=args.desktop_max_actions,
            desktop_max_session_seconds=args.desktop_max_duration_seconds,
            ghost_mode=args.ghost_mode or "whisper",
            autonomy_level=autonomy_level,
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


def _run_autonomy_cli(args: argparse.Namespace) -> int:
    from ..chimera_pilot.autonomy import get_autonomy_profile, list_autonomy_profiles
    from ..chimera_pilot.autonomy_jobs import AutonomyJobRunner

    config = load_config()
    autonomy = get_autonomy_config(config)

    if args.action == "show":
        profile = get_autonomy_profile(str(autonomy.get("level") or "supervised"))
        print(json.dumps({"config": autonomy, "resolved_profile": profile.to_dict()}, indent=2, sort_keys=True))
        return 0

    if args.action == "set":
        if args.level:
            autonomy["level"] = args.level
        if args.max_tool_rounds is not None:
            autonomy["max_tool_rounds"] = args.max_tool_rounds
        if args.max_parallel_tasks is not None:
            autonomy["max_parallel_tasks"] = args.max_parallel_tasks
        if args.local_model_profile:
            autonomy["local_model_profile"] = args.local_model_profile
        config["autonomy"] = autonomy
        save_config(config)
        profile = get_autonomy_profile(str(autonomy.get("level") or "supervised"))
        print(json.dumps({"ok": True, "config": autonomy, "resolved_profile": profile.to_dict()}, indent=2, sort_keys=True))
        return 0

    if args.action == "jobs":
        print(json.dumps({"profiles": [p.to_dict() for p in list_autonomy_profiles()], "jobs": AutonomyJobRunner.list_jobs()}, indent=2, sort_keys=True))
        return 0

    if args.action == "run":
        if not args.job:
            print(json.dumps({"ok": False, "error": "Missing autonomy job name"}, indent=2, sort_keys=True))
            return 2
        runner = AutonomyJobRunner(profile=str(autonomy.get("level") or "supervised"))
        result = runner.run(args.job, execute=args.execute)
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.ok else 1

    return 2


def _run_minimind_cli(args: argparse.Namespace) -> int:
    from ..model_layer.minimind_lifecycle import MiniMindLifecycle

    lifecycle = MiniMindLifecycle(profile_name=args.profile or None)
    if args.action == "status":
        print(json.dumps(lifecycle.status().to_dict(), indent=2, sort_keys=True))
        return 0
    if args.action == "dataset":
        path = lifecycle.generate_dataset(
            [{"prompt": args.prompt, "response": args.response}],
            output_path=args.output or None,
        )
        print(json.dumps({"ok": True, "path": str(path)}, indent=2, sort_keys=True))
        return 0
    if args.action == "log-failure":
        logged = lifecycle.log_low_confidence(
            prompt=args.prompt,
            response=args.response,
            confidence=args.confidence,
            threshold=args.threshold,
            output_path=args.output or None,
        )
        print(json.dumps({"ok": True, "logged": logged}, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
