"""CLI entry point for Ghost Chimera harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .case import HarnessCase
from .runner import HarnessRunner


def _load_cases(path: str) -> list[HarnessCase]:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.suffix.lower() == ".jsonl":
        cases: list[HarnessCase] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            cases.append(HarnessCase.from_dict(json.loads(line)))
        return cases
    payload = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [HarnessCase.from_dict(item) for item in payload]
    return [HarnessCase.from_dict(payload)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ghost Chimera harness (deterministic regression runner)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run harness cases from JSON/JSONL")
    run.add_argument("--cases", required=True, help="Path to cases file (.json or .jsonl)")
    run.add_argument("--output-dir", default="harness_runs", help="Directory to write JSONL artifacts into.")
    args = parser.parse_args(argv)

    if args.command == "run":
        cases = _load_cases(args.cases)
        runner = HarnessRunner(output_dir=args.output_dir)
        results = runner.run(cases)
        return 0 if all(r.ok for r in results) else 1
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
