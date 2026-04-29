"""CLI entry point for Ghost Chimera evals."""

from __future__ import annotations

import argparse
import json
import sys

from .runner import run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Ghost Chimera evaluation suites")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run one suite")
    run_parser.add_argument("--suite", default="smoke", choices=["smoke", "safety"])
    args = parser.parse_args(argv)

    if args.command == "run":
        report = run_suite(args.suite)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
