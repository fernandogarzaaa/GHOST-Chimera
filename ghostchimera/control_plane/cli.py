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
from pathlib import Path

from ..agent_core.core import AgentCore
from ..config import GhostChimeraConfig
from ..logging_config import ensure_configured, get_logger
from .config import get_autonomy_config, load_config, save_config

logger = get_logger("cli")


_PARALLEL_COMMANDS = {"run", "batch"}
_GLOBAL_OPTIONS_WITH_VALUES = {
    "--log-level",
    "--pilot-run",
    "--pilot-cwd",
    "--desktop-action-class",
    "--desktop-allow-app",
    "--desktop-deny-app",
    "--desktop-allow-window",
    "--desktop-deny-window",
    "--desktop-kill-switch-path",
    "--desktop-confirm-token",
    "--desktop-action-log-path",
    "--desktop-screenshot-dir",
    "--desktop-max-actions",
    "--desktop-max-duration-seconds",
    "--ghost-mode",
    "--autonomy-level",
    "--runtime-specialization-cache-dir",
}


def _first_command_token(argv: list[str]) -> str:
    """Return the first top-level command token after global options."""

    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if not token:
            continue
        if token.startswith("--"):
            option_name = token.split("=", 1)[0]
            if "=" not in token and option_name in _GLOBAL_OPTIONS_WITH_VALUES:
                skip_next = True
            continue
        if token.startswith("-"):
            continue
        return token
    return ""


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
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if _first_command_token(effective_argv) in _PARALLEL_COMMANDS:
        from .parallel_cli import _main as _parallel_main
        return _parallel_main(effective_argv)

    parser = argparse.ArgumentParser(description="Ghost Chimera CLI")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup", help="Run interactive setup wizard")
    console_parser = sub.add_parser("console", help="Open the browser-based Ghost Console")
    console_parser.add_argument("--host", default="127.0.0.1", help="Gateway bind host for the console.")
    console_parser.add_argument("--port", type=int, default=8765, help="Gateway WebSocket port.")
    console_parser.add_argument("--http-port", type=int, default=8766, help="Console HTTP port.")
    console_parser.add_argument("--state-dir", default="", help="Optional state directory for console jobs and schedules.")
    console_parser.add_argument("--no-open", action="store_true", help="Print the console URL without opening a browser.")
    console_parser.add_argument("--auth-token", default="", help="Require this bearer token on all /api/* routes (X-Gateway-Token header).")
    doctor_parser = sub.add_parser("doctor", help="Run health checks and report status")
    doctor_parser.add_argument("--production", action="store_true", help="Require production deployment guardrails.")
    capabilities_parser = sub.add_parser("capabilities", help="Inspect competitive agent-orchestration capability coverage")
    capabilities_parser.add_argument("--format", choices=["json", "markdown"], default="json", help="Output format.")
    capabilities_parser.add_argument("--save", default="", help="Optional path to write the report.")
    sub.add_parser("model", help="List and switch the current model provider")
    sub.add_parser("policy", help="Manage security policies")
    desktop_stop_parser = sub.add_parser("desktop-stop", help="Create the Chimera Pilot desktop kill-switch file")
    desktop_stop_parser.add_argument("--desktop-kill-switch-path", default="", help="Kill-switch path to create.")
    desktop_stop_parser.add_argument("--reason", default="operator_stop", help="Reason written into the stop file.")
    autonomy_parser = sub.add_parser("autonomy", help="Show, set, and run autonomy controls")
    autonomy_parser.add_argument("action", choices=["show", "set", "jobs", "run"], nargs="?", default="show")
    autonomy_parser.add_argument("job", nargs="?", default="", help="Job name for 'run'")
    autonomy_parser.add_argument("--level", choices=["assist", "supervised", "autonomous", "generalist", "agi", "sgi"])
    autonomy_parser.add_argument("--max-tool-rounds", type=int)
    autonomy_parser.add_argument("--max-parallel-tasks", type=int)
    autonomy_parser.add_argument("--local-model-profile", choices=["tiny", "balanced", "stronger"])
    autonomy_parser.add_argument("--execute", action="store_true", help="Allow jobs that otherwise return preview-only plans.")
    workspace_parser = sub.add_parser("workspace", help="Inspect and update the local operator workspace state")
    workspace_parser.add_argument(
        "action",
        choices=["show", "add-evidence", "reflect", "set-goal", "sync-memory", "clear"],
        nargs="?",
        default="show",
    )
    workspace_parser.add_argument("--state-dir", default="", help="Optional state directory for workspace state.")
    workspace_parser.add_argument("--memory-db", default="", help="Memory database path for sync-memory.")
    workspace_parser.add_argument("--min-confidence", type=float, default=0.0, help="Minimum confidence for sync-memory.")
    workspace_parser.add_argument("--stale-after-days", type=float, default=30.0, help="Mark synced workspace records stale after this many days.")
    workspace_parser.add_argument("--source", default="", help="Evidence source for add-evidence.")
    workspace_parser.add_argument("--content", default="", help="Evidence content for add-evidence.")
    workspace_parser.add_argument("--confidence", type=float, default=0.5, help="Confidence from 0.0 to 1.0.")
    workspace_parser.add_argument("--reflection-action", default="", help="Action name for reflect.")
    workspace_parser.add_argument("--outcome", default="", help="Outcome text for reflect.")
    workspace_parser.add_argument("--goal", default="", help="Goal name for set-goal.")
    workspace_parser.add_argument("--description", default="", help="Goal description for set-goal.")
    minimind_parser = sub.add_parser("minimind", help="Inspect MiniMind local runtime support")
    minimind_parser.add_argument(
        "action",
        choices=[
            "status",
            "architectures",
            "dataset",
            "log-failure",
            "bootstrap-personal",
            "beta-vision",
            "personal-status",
            "personal-consent",
            "personal-bootstrap",
            "personal-handoff",
            "personal-revoke",
        ],
        nargs="?",
        default="status",
    )
    minimind_parser.add_argument("--profile", default="", help="MiniMind/local model profile.")
    minimind_parser.add_argument("--output", default="", help="Output JSONL path.")
    minimind_parser.add_argument("--prompt", default="", help="Prompt/instruction text.")
    minimind_parser.add_argument("--response", default="", help="Response/output text.")
    minimind_parser.add_argument("--confidence", type=float, default=0.0)
    minimind_parser.add_argument("--threshold", type=float, default=0.5)
    minimind_parser.add_argument("--memory-db", default=".ghostchimera-memory.sqlite3", help="Memory DB path for personal ingestion.")
    minimind_parser.add_argument("--state-dir", default="", help="Optional state directory for Personal MiniMind consent/datasets.")
    minimind_parser.add_argument("--allow-files", action="store_true", help="Allow ingestion of file paths/directories.")
    minimind_parser.add_argument("--allow-email", action="store_true", help="Allow ingestion of .eml/.mbox paths/directories.")
    minimind_parser.add_argument("--admin-controls", action="store_true", help="Grant Personal MiniMind admin consent.")
    minimind_parser.add_argument("--allow-system-specs", action="store_true", help="Allow Personal MiniMind to read local system specs.")
    minimind_parser.add_argument("--allow-machine-crawl", action="store_true", help="Allow Personal MiniMind to discover supported files from crawl roots.")
    minimind_parser.add_argument("--allow-email-crawl", action="store_true", help="Allow Personal MiniMind to discover .eml/.mbox files from crawl roots.")
    minimind_parser.add_argument("--allow-autonomy", action="store_true", help="Allow Personal MiniMind to prepare autonomy job handoffs.")
    minimind_parser.add_argument("--allow-training", action="store_true", help="Allow Personal MiniMind to write training dataset records.")
    minimind_parser.add_argument("--include-system-specs", action="store_true", help="Include local system specs during Personal MiniMind bootstrap.")
    minimind_parser.add_argument("--operator", default="cli", help="Operator label stored with Personal MiniMind consent.")
    minimind_parser.add_argument("--objective", default="", help="Objective for Personal MiniMind handoff.")
    minimind_parser.add_argument("--file-path", action="append", default=[], help="File or directory path to ingest. Repeatable.")
    minimind_parser.add_argument("--email-path", action="append", default=[], help=".eml/.mbox file or directory path to ingest. Repeatable.")
    minimind_parser.add_argument("--crawl-root", action="append", default=[], help="Root to scan when whole-machine crawl is enabled. Repeatable; defaults to local drives/home.")
    minimind_parser.add_argument("--exclude-path", action="append", default=[], help="Path to exclude from whole-machine crawl. Repeatable.")
    minimind_parser.add_argument("--max-files", type=int, default=500, help="Maximum files to ingest per file directory.")
    minimind_parser.add_argument("--max-emails", type=int, default=1000, help="Maximum emails/files to ingest per email directory/archive.")
    minimind_parser.add_argument("--config", default="", help="Path to beta vision JSON config.")
    minimind_parser.add_argument("--run-autonomy-jobs", action="store_true", help="For beta-vision inline mode, enqueue autonomy jobs.")
    local_model_parser = sub.add_parser("local-model", help="Bootstrap and check local model inference readiness")
    local_model_parser.add_argument(
        "action",
        choices=["check", "guide", "profiles"],
        nargs="?",
        default="check",
        help="check: report readiness; guide: print install steps; profiles: list all profiles",
    )
    local_model_parser.add_argument("--profile", default="", help="Local model profile name (tiny, balanced, stronger).")
    runtime_warmup_parser = sub.add_parser("runtime-warmup", help="Precompute local runtime specialization manifests")
    runtime_warmup_parser.add_argument("--runtime-specialization-cache-dir", default=".ghost/runtime-specialization", help="Directory for warmup manifests.")
    runtime_warmup_parser.add_argument("--local-model-profile", action="append", default=[], help="Profile to warm. Repeat for multiple; omit for all profiles.")
    runtime_warmup_parser.add_argument("--local-model-gpu-layers", type=int, default=0, help="llama.cpp GPU layers to offload.")
    runtime_warmup_parser.add_argument("--gpu-architecture", default="", help="Optional GPU architecture hint, for example sm100.")
    runtime_warmup_parser.add_argument("--gpu-sm-count", type=int, default=0, help="Optional GPU SM count hint.")
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
    parser.add_argument("--desktop-allow-app", action="append", default=[], help="Allowlisted desktop app target.")
    parser.add_argument("--desktop-deny-app", action="append", default=[], help="Denied desktop app target.")
    parser.add_argument("--desktop-allow-window", action="append", default=[], help="Allowlisted desktop window target.")
    parser.add_argument("--desktop-deny-window", action="append", default=[], help="Denied desktop window target.")
    parser.add_argument("--enable-desktop-backend", action="store_true", help="Register Chimera Pilot desktop backend (dry-run).")
    parser.add_argument("--enable-live-desktop", action="store_true", help="Enable live desktop backend mode.")
    parser.add_argument("--desktop-kill-switch-path", default="", help="If file exists, desktop actions are blocked.")
    parser.add_argument("--desktop-confirm-token", default="", help="Required token for destructive live desktop actions.")
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
    parser.add_argument("--disable-runtime-specialization", action="store_true", help="Disable local runtime specialization planning.")
    parser.add_argument("--runtime-specialization-cache-dir", default="", help="Write local runtime specialization manifests here.")
    parser.add_argument("--config-show", action="store_true", help="Print resolved Ghost Chimera runtime config as JSON and exit.")
    args = parser.parse_args(effective_argv)
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

    if args.command == "console":
        from .console import run_console

        run_console(
            host=args.host,
            port=args.port,
            http_port=args.http_port,
            state_dir=args.state_dir or None,
            open_browser=not args.no_open,
            block=True,
            auth_token=args.auth_token or "",
        )
        return 0

    if args.command == "doctor":
        from .doctor import run_doctor

        return run_doctor(production=args.production)

    if args.command == "capabilities":
        return _run_capabilities_cli(args)

    if args.command == "model":
        from .model_picker import run_model_picker

        run_model_picker()
        return 0

    if args.command == "policy":
        from .cli_policy import _main as _policy_main

        return _policy_main()

    if args.command == "desktop-stop":
        from ..chimera_pilot.desktop_policy import write_desktop_stop_file

        path = write_desktop_stop_file(args.desktop_kill_switch_path or None, reason=args.reason)
        print(json.dumps({"ok": True, "path": str(path)}, indent=2, sort_keys=True))
        return 0

    if args.command == "autonomy":
        return _run_autonomy_cli(args)

    if args.command == "workspace":
        return _run_workspace_cli(args)

    if args.command == "minimind":
        return _run_minimind_cli(args)

    if args.command == "local-model":
        from .local_model_cli import run_local_model_cli

        return run_local_model_cli(action=args.action, profile=getattr(args, "profile", ""))

    if args.command == "runtime-warmup":
        from ..model_layer.runtime_specialization import detect_runtime_environment, warm_runtime_specialization_cache

        environment = detect_runtime_environment(
            n_gpu_layers=args.local_model_gpu_layers,
            architecture=args.gpu_architecture or None,
            sm_count=args.gpu_sm_count or None,
        )
        print(
            json.dumps(
                warm_runtime_specialization_cache(
                    cache_dir=args.runtime_specialization_cache_dir,
                    profile_names=args.local_model_profile,
                    environment=environment,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

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
            desktop_allowed_apps=args.desktop_allow_app,
            desktop_denied_apps=args.desktop_deny_app,
            desktop_allowed_windows=args.desktop_allow_window,
            desktop_denied_windows=args.desktop_deny_window,
            desktop_confirmation_token=args.desktop_confirm_token or None,
            enable_desktop_backend=args.enable_desktop_backend,
            enable_live_desktop=args.enable_live_desktop,
            desktop_kill_switch_path=args.desktop_kill_switch_path or None,
            desktop_action_log_path=args.desktop_action_log_path or None,
            desktop_screenshot_dir=args.desktop_screenshot_dir or None,
            desktop_max_live_actions=args.desktop_max_actions,
            desktop_max_session_seconds=args.desktop_max_duration_seconds,
            ghost_mode=args.ghost_mode or "whisper",
            local_runtime_specialization=not args.disable_runtime_specialization,
            local_runtime_specialization_cache_dir=args.runtime_specialization_cache_dir or None,
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


def _run_capabilities_cli(args: argparse.Namespace) -> int:
    from ..chimera_pilot.capability_intelligence import format_capability_report, inspect_capabilities

    payload = inspect_capabilities()
    if args.format == "markdown":
        output = format_capability_report(payload)
    else:
        output = json.dumps(payload, indent=2, sort_keys=True)
    if args.save:
        Path(args.save).expanduser().write_text(output, encoding="utf-8")
    print(output, end="" if output.endswith("\n") else "\n")
    return 0 if payload.get("ok") else 1


def _run_workspace_cli(args: argparse.Namespace) -> int:
    from ..cognition_layer.workspace_state import OperatorWorkspaceStore

    store = OperatorWorkspaceStore(state_dir=args.state_dir or None)
    try:
        if args.action == "show":
            payload = store.snapshot()
        elif args.action == "add-evidence":
            payload = store.add_evidence(args.source, args.content, confidence=args.confidence)
        elif args.action == "reflect":
            payload = store.add_reflection(
                action=args.reflection_action,
                outcome=args.outcome,
                confidence=args.confidence,
            )
        elif args.action == "set-goal":
            payload = store.set_goal(args.goal, args.description)
        elif args.action == "sync-memory":
            payload = store.sync_to_memory(
                memory_db=args.memory_db or None,
                min_confidence=args.min_confidence,
                stale_after_days=args.stale_after_days,
            )
        elif args.action == "clear":
            payload = store.clear()
        else:
            return 2
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _run_minimind_cli(args: argparse.Namespace) -> int:
    from ..model_layer.minimind_lifecycle import MiniMindLifecycle
    from ..model_layer.minimind_personal_agent import MiniMindPersonalAgent
    from ..model_layer.minimind_runtime import list_minimind_architectures, minimind_source_metadata

    lifecycle = MiniMindLifecycle(profile_name=args.profile or None, state_dir=args.state_dir or None)
    personal = MiniMindPersonalAgent(
        profile_name=args.profile or None,
        memory_db=args.memory_db,
        state_dir=args.state_dir or None,
    )
    if args.action == "status":
        print(json.dumps(lifecycle.status().to_dict(), indent=2, sort_keys=True))
        return 0
    if args.action == "architectures":
        print(
            json.dumps(
                {
                    "ok": True,
                    "source": minimind_source_metadata(),
                    "architectures": [architecture.to_dict() for architecture in list_minimind_architectures()],
                },
                indent=2,
                sort_keys=True,
            )
        )
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
    if args.action == "bootstrap-personal":
        if not args.allow_files and not args.allow_email:
            print(json.dumps({"ok": False, "error": "Pass --allow-files and/or --allow-email with explicit paths."}, indent=2, sort_keys=True))
            return 2
        summary = lifecycle.bootstrap_personal_dataset(
            memory_db=args.memory_db,
            allow_files=args.allow_files,
            allow_email=args.allow_email,
            file_paths=list(args.file_path or []),
            email_paths=list(args.email_path or []),
            max_files=args.max_files,
            max_emails=args.max_emails,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.action == "beta-vision":
        from ..model_layer.minimind_beta_orchestrator import BetaVisionConfig, load_beta_config, run_beta_vision

        if args.config:
            config = load_beta_config(args.config)
        else:
            config = BetaVisionConfig(
                memory_db=args.memory_db,
                file_paths=list(args.file_path or []),
                email_paths=list(args.email_path or []),
                run_autonomy_jobs=bool(args.run_autonomy_jobs),
                autonomy_profile="supervised",
                autonomy_jobs=["self-audit", "memory-refresh"],
            )
        payload = run_beta_vision(config=config, profile_name=args.profile or None)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.action == "personal-status":
        print(json.dumps(personal.status(), indent=2, sort_keys=True))
        return 0
    if args.action == "personal-consent":
        payload = personal.grant_consent(
            admin_controls=args.admin_controls,
            allow_system_specs=args.allow_system_specs,
            allow_files=args.allow_files,
            allow_email=args.allow_email,
            allow_machine_crawl=args.allow_machine_crawl,
            allow_email_crawl=args.allow_email_crawl,
            allow_autonomy=args.allow_autonomy,
            allow_training=args.allow_training,
            file_paths=list(args.file_path or []),
            email_paths=list(args.email_path or []),
            crawl_roots=list(args.crawl_root or []),
            exclude_paths=list(args.exclude_path or []),
            operator=args.operator,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload.get("ok") else 2
    if args.action == "personal-bootstrap":
        payload = personal.bootstrap(
            file_paths=list(args.file_path or []),
            email_paths=list(args.email_path or []),
            include_system_specs=args.include_system_specs,
            max_files=args.max_files,
            max_emails=args.max_emails,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload.get("ok") else 2
    if args.action == "personal-handoff":
        if not args.objective:
            print(json.dumps({"ok": False, "error": "Pass --objective for personal-handoff."}, indent=2, sort_keys=True))
            return 2
        payload = personal.build_handoff(args.objective)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload.get("ok") else 2
    if args.action == "personal-revoke":
        print(json.dumps(personal.revoke_consent(), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
