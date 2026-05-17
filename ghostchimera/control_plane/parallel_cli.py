"""Parallel execution CLI for Ghost Chimera.

Provides ``ghostchimera run <objectives...> --parallel N`` and
``ghostchimera batch <file.jsonl> --workers N`` commands.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..logging_config import ensure_configured, get_logger

logger = get_logger("parallel_cli")


def _add_parallel_args(parser: argparse.ArgumentParser) -> None:
    """Add parallel execution subcommands to the parser."""
    subparsers = parser.add_subparsers(dest="command")

    # run subcommand (with --parallel flag)
    run_parser = subparsers.add_parser("run", help="Run one or more objectives with optional parallelism")
    run_parser.add_argument("objectives", nargs="+", help="One or more objectives to execute")
    run_parser.add_argument(
        "--parallel",
        "-p",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1)",
    )
    run_parser.add_argument(
        "--output-dir",
        "-o",
        default="./parallel_output",
        help="Output directory (default: ./parallel_output)",
    )

    # batch subcommand
    batch_parser = subparsers.add_parser("batch", help="Run objectives from a JSONL file in parallel")
    batch_parser.add_argument("dataset_file", help="Path to JSONL file with objective/prompt field")
    batch_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    batch_parser.add_argument(
        "--output-dir",
        "-o",
        default="./batch_output",
        help="Output directory (default: ./batch_output)",
    )


def _handle_run(args: argparse.Namespace) -> int:
    """Handle the 'run' subcommand."""
    from ..chimera_pilot.agent_pool import BatchAgent

    runner = BatchAgent(
        objectives=args.objectives,
        workers=args.parallel,
        output_dir=args.output_dir,
    )
    summary = runner.run()

    print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
    return 0 if summary.failed_tasks == 0 else 1


def _handle_batch(args: argparse.Namespace) -> int:
    """Handle the 'batch' subcommand."""
    from ..chimera_pilot.agent_pool import ParallelAgent

    runner = ParallelAgent(
        jsonl_file=args.dataset_file,
        workers=args.workers,
        output_dir=args.output_dir,
    )
    summary = runner.run()

    print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
    return 0 if summary.failed_tasks == 0 else 1


def _main(argv: list[str] | None = None) -> int:
    """Entry point for parallel CLI commands."""
    ensure_configured()

    parser = argparse.ArgumentParser(description="Ghost Chimera CLI")

    # Add standard CLI args
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
    parser.add_argument("--pilot-cwd", default="", help="Allowed working directory for Chimera Pilot.")
    parser.add_argument("--allow-python", action="store_true", help="Allow Chimera Pilot local Python execution.")
    parser.add_argument("--allow-network", action="store_true", help="Allow Chimera Pilot network-requiring tasks.")
    parser.add_argument(
        "--include-quantum-backend",
        action="store_true",
        help="Include optional pyqpanda3 quantum backend.",
    )
    parser.add_argument(
        "--config-show",
        action="store_true",
        help="Print resolved Ghost Chimera runtime config as JSON and exit.",
    )

    # Add parallel subcommands
    _add_parallel_args(parser)

    args = parser.parse_args(argv)

    # Handle parallel commands first
    if args.command == "run":
        return _handle_run(args)
    if args.command == "batch":
        return _handle_batch(args)

    # Handle existing commands
    if args.config_show:
        from ..config import GhostChimeraConfig

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
            print(
                json.dumps(
                    {"ok": False, "error": str(exc), "policy": kernel.policy.to_dict()}, indent=2, sort_keys=True
                )
            )
            return 1
        payload = [execution.to_dict() for execution in executions]
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if all(item["ok"] for item in payload) else 1

    # Fall through to original interactive CLI
    from .cli import run_cli

    run_cli()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
