"""Command line interface for Chimera Pilot."""

from __future__ import annotations

import argparse
import json
import sys

from ..memory_layer.store import MemoryStore
from ..model_layer.local_profiles import list_local_model_profiles
from .autonomy import get_autonomy_profile, list_autonomy_profiles
from .kernel import ChimeraPilotKernel


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chimera Pilot resource orchestration layer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show backend health and telemetry summary.")
    status_parser.add_argument("--include-deterministic-backend", action="store_true")
    status_parser.add_argument("--include-quantum-backend", action="store_true", help="Probe and register optional pyqpanda3 backend if installed.")
    status_parser.add_argument("--memory-db", default="", help="SQLite memory database for CWR retrieval.")
    status_parser.add_argument("--local-model-path", default="", help="Optional GGUF model path for llama.cpp local reasoning.")
    status_parser.add_argument("--local-model-profile", default="tiny", help="Local model profile name.")
    status_parser.add_argument("--autonomy-level", default="", help="Autonomy profile: assist, supervised, autonomous, or generalist.")
    status_parser.add_argument("--local-model-gpu-layers", type=int, default=0, help="llama.cpp GPU layers to offload.")
    status_parser.add_argument("--allow-desktop-control", action="store_true", help="Allow desktop cursor/keyboard control.")
    status_parser.add_argument("--enable-desktop-backend", action="store_true", help="Register desktop backend.")
    status_parser.add_argument("--enable-live-desktop", action="store_true", help="Enable live desktop backend mode.")
    status_parser.add_argument("--desktop-kill-switch-path", default="", help="If this file exists, desktop actions are blocked.")
    status_parser.add_argument("--desktop-action-log-path", default="", help="JSONL log file for desktop actions.")
    status_parser.add_argument("--desktop-screenshot-dir", default="", help="Directory for live desktop before/after screenshots.")
    status_parser.add_argument("--desktop-max-actions", type=int, default=25, help="Maximum live desktop actions per backend session.")
    status_parser.add_argument("--desktop-max-duration-seconds", type=float, default=300.0, help="Maximum live desktop session duration.")
    status_parser.add_argument("--ghost-mode", default="whisper", choices=["whisper", "haunt", "possess"], help="Ghost mode for policy gating.")

    run_parser = subparsers.add_parser("run", help="Compile and execute one objective.")
    run_parser.add_argument("objective", help="Objective to compile and execute.")
    run_parser.add_argument("--cwd", default="", help="Allowed working directory for local Python/test execution.")
    run_parser.add_argument("--include-deterministic-backend", action="store_true")
    run_parser.add_argument("--include-quantum-backend", action="store_true", help="Probe and register optional pyqpanda3 backend if installed.")
    run_parser.add_argument("--allow-python", action="store_true", help="Allow local Python/test execution for this command.")
    run_parser.add_argument("--allow-network", action="store_true", help="Allow network-requiring tasks for this command.")
    run_parser.add_argument("--allow-desktop-control", action="store_true", help="Allow desktop cursor/keyboard control.")
    run_parser.add_argument("--enable-desktop-backend", action="store_true", help="Register desktop backend (dry-run).")
    run_parser.add_argument("--enable-live-desktop", action="store_true", help="Enable live desktop backend mode.")
    run_parser.add_argument("--desktop-kill-switch-path", default="", help="If this file exists, desktop actions are blocked.")
    run_parser.add_argument("--desktop-action-log-path", default="", help="JSONL log file for desktop actions.")
    run_parser.add_argument("--desktop-screenshot-dir", default="", help="Directory for live desktop before/after screenshots.")
    run_parser.add_argument("--desktop-max-actions", type=int, default=25, help="Maximum live desktop actions per backend session.")
    run_parser.add_argument("--desktop-max-duration-seconds", type=float, default=300.0, help="Maximum live desktop session duration.")
    run_parser.add_argument("--ghost-mode", default="whisper", choices=["whisper", "haunt", "possess"], help="Ghost mode for policy gating.")
    run_parser.add_argument("--memory-db", default="", help="SQLite memory database for CWR retrieval.")
    run_parser.add_argument("--local-model-path", default="", help="Optional GGUF model path for llama.cpp local reasoning.")
    run_parser.add_argument("--local-model-profile", default="tiny", help="Local model profile name.")
    run_parser.add_argument("--autonomy-level", default="", help="Autonomy profile: assist, supervised, autonomous, or generalist.")
    run_parser.add_argument("--local-model-gpu-layers", type=int, default=0, help="llama.cpp GPU layers to offload.")

    compile_parser = subparsers.add_parser("compile", help="Compile one objective without executing it.")
    compile_parser.add_argument("objective", help="Objective to compile.")

    calibrate_parser = subparsers.add_parser("calibrate", help="Probe all registered backends once.")
    calibrate_parser.add_argument("--include-deterministic-backend", action="store_true")
    calibrate_parser.add_argument("--include-quantum-backend", action="store_true", help="Probe and register optional pyqpanda3 backend if installed.")
    calibrate_parser.add_argument("--memory-db", default="", help="SQLite memory database for CWR retrieval.")
    calibrate_parser.add_argument("--local-model-path", default="", help="Optional GGUF model path for llama.cpp local reasoning.")
    calibrate_parser.add_argument("--local-model-profile", default="tiny", help="Local model profile name.")
    calibrate_parser.add_argument("--autonomy-level", default="", help="Autonomy profile: assist, supervised, autonomous, or generalist.")
    calibrate_parser.add_argument("--local-model-gpu-layers", type=int, default=0, help="llama.cpp GPU layers to offload.")

    subparsers.add_parser("model-profiles", help="List built-in local model profiles.")
    subparsers.add_parser("autonomy-profiles", help="List built-in autonomy profiles.")

    memory_add_parser = subparsers.add_parser("memory-add", help="Add one document to the CWR memory database.")
    memory_add_parser.add_argument("--memory-db", required=True, help="SQLite memory database to update.")
    memory_add_parser.add_argument("--source", required=True, help="Source identifier for citations.")
    memory_add_parser.add_argument("--content", required=True, help="Document content to store.")
    memory_add_parser.add_argument("--metadata", default="{}", help="Optional JSON metadata object.")

    memory_search_parser = subparsers.add_parser("memory-search", help="Search the CWR memory database.")
    memory_search_parser.add_argument("--memory-db", required=True, help="SQLite memory database to search.")
    memory_search_parser.add_argument("--limit", type=int, default=5, help="Maximum result count.")
    memory_search_parser.add_argument("query", help="Search query.")

    args = parser.parse_args(argv)

    if args.command == "compile":
        kernel = ChimeraPilotKernel.default(include_deterministic_backend=True)
        _print_json([
            {
                "id": task.id,
                "kind": task.kind.value,
                "objective": task.objective,
                "inputs": task.inputs,
                "constraints": task.constraints,
                "privacy_level": task.privacy_level,
                "requires_network": task.requires_network,
            }
            for task in kernel.compile(args.objective)
        ])
        return 0

    if args.command == "model-profiles":
        _print_json({"profiles": [profile.to_dict() for profile in list_local_model_profiles()]})
        return 0

    if args.command == "autonomy-profiles":
        _print_json({"profiles": [profile.to_dict() for profile in list_autonomy_profiles()]})
        return 0

    if args.command == "memory-add":
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError as exc:
            _print_json({"ok": False, "error": f"Invalid metadata JSON: {exc}"})
            return 1
        if not isinstance(metadata, dict):
            _print_json({"ok": False, "error": "Metadata must be a JSON object"})
            return 1
        store = MemoryStore(args.memory_db)
        document_id = store.add_document(args.source, args.content, metadata=metadata)
        _print_json({"ok": True, "id": document_id, "source": args.source})
        return 0

    if args.command == "memory-search":
        store = MemoryStore(args.memory_db)
        _print_json({"ok": True, "query": args.query, "results": store.search(args.query, limit=args.limit)})
        return 0

    kernel = ChimeraPilotKernel.default(
        include_deterministic_backend=getattr(args, "include_deterministic_backend", False),
        include_quantum_backend=getattr(args, "include_quantum_backend", False),
        cwd=getattr(args, "cwd", "") or None,
        allow_python_execution=getattr(args, "allow_python", False),
        allow_network=getattr(args, "allow_network", False),
        allow_desktop_control=getattr(args, "allow_desktop_control", False),
        enable_desktop_backend=getattr(args, "enable_desktop_backend", False),
        enable_live_desktop=getattr(args, "enable_live_desktop", False),
        desktop_kill_switch_path=getattr(args, "desktop_kill_switch_path", "") or None,
        desktop_action_log_path=getattr(args, "desktop_action_log_path", "") or None,
        desktop_screenshot_dir=getattr(args, "desktop_screenshot_dir", "") or None,
        desktop_max_live_actions=getattr(args, "desktop_max_actions", 25),
        desktop_max_session_seconds=getattr(args, "desktop_max_duration_seconds", 300.0),
        ghost_mode=getattr(args, "ghost_mode", "whisper"),
        memory_store=MemoryStore(args.memory_db) if getattr(args, "memory_db", "") else None,
        local_model_path=getattr(args, "local_model_path", "") or None,
        local_model_profile=(
            getattr(args, "local_model_profile", "tiny")
            if getattr(args, "local_model_profile", "tiny") != "tiny" or not getattr(args, "autonomy_level", "")
            else get_autonomy_profile(getattr(args, "autonomy_level", "")).local_model_profile
        ),
        local_model_gpu_layers=getattr(args, "local_model_gpu_layers", 0),
        autonomy_level=getattr(args, "autonomy_level", "") or None,
    )

    if args.command == "status":
        _print_json(kernel.status())
        return 0

    if args.command == "calibrate":
        _print_json(kernel.calibrate())
        return 0

    if args.command == "run":
        try:
            executions = kernel.run(args.objective)
        except PermissionError as exc:
            _print_json({"ok": False, "error": str(exc), "policy": kernel.policy.to_dict()})
            return 1
        payload = [execution.to_dict() for execution in executions]
        _print_json(payload)
        return 0 if all(item["ok"] for item in payload) else 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
