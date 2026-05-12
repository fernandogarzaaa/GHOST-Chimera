#!/usr/bin/env python3
"""Ghost Chimera end-to-end user journey simulation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAX_DETAIL_LENGTH = 4000
TRUNCATE_HEAD_LENGTH = 500
TRUNCATE_TAIL_LENGTH = 3500


def _run_release_gate() -> dict[str, Any]:
    started = time.monotonic()
    timeout_raw = os.environ.get("GHOSTCHIMERA_RELEASE_GATE_TIMEOUT", "180")
    try:
        timeout_seconds = int(timeout_raw)
    except ValueError as exc:
        raise ValueError(
            f"Invalid GHOSTCHIMERA_RELEASE_GATE_TIMEOUT value: expected integer, got {timeout_raw!r}"
        ) from exc
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_release.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    duration_ms = round((time.monotonic() - started) * 1000, 1)
    ok = completed.returncode == 0
    detail = (completed.stdout if ok else (completed.stderr or completed.stdout)).strip()
    if len(detail) > MAX_DETAIL_LENGTH:
        head = detail[:TRUNCATE_HEAD_LENGTH]
        tail = detail[-TRUNCATE_TAIL_LENGTH:]
        detail = f"{head}\n...[truncated]...\n{tail}"
    return {"name": "release_gate", "ok": ok, "duration_ms": duration_ms, "detail": detail}


def _run_eval_suite(name: str) -> dict[str, Any]:
    from ghostchimera.evals.runner import run_suite

    started = time.monotonic()
    report = run_suite(name)
    duration_ms = round((time.monotonic() - started) * 1000, 1)
    return {
        "name": f"suite:{name}",
        "ok": bool(report["ok"]),
        "duration_ms": duration_ms,
        "detail": report,
    }


def run_simulation(quiet: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    from ghostchimera.evals.runner import EVAL_SUITES

    preferred_order = [
        "smoke",
        "safety",
        "autonomy",
        "user-journey",
        "workspace",
        "coverage",
        "track2",
        "track3",
        "track4",
        "redteam",
    ]
    suites = [name for name in preferred_order if name in EVAL_SUITES]
    suites.extend(name for name in EVAL_SUITES if name not in suites)
    steps: list[dict[str, Any]] = [_run_release_gate(), *[_run_eval_suite(name) for name in suites]]
    total_steps = len(steps)
    passed_steps = sum(1 for step in steps if step["ok"])
    failed_steps = total_steps - passed_steps

    total_cases = 0
    passed_cases = 0
    failed_cases = 0
    for step in steps:
        if isinstance(step["detail"], dict) and "cases" in step["detail"]:
            total_cases += len(step["detail"]["cases"])
            passed_cases += int(step["detail"]["passed"])
            failed_cases += int(step["detail"]["failed"])

    wall_ms = round((time.monotonic() - started) * 1000, 1)
    result = {
        "simulation": "ghost_chimera_user_journey",
        "version": "0.3.0-beta",
        "ok": failed_steps == 0,
        "summary": {
            "total_steps": total_steps,
            "passed_steps": passed_steps,
            "failed_steps": failed_steps,
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "wall_time_ms": wall_ms,
        },
        "steps": steps,
        "failed_step_names": [step["name"] for step in steps if not step["ok"]],
    }

    if not quiet:
        print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Ghost Chimera public beta end-to-end simulation")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("--quiet", action="store_true", help="Suppress printed report")
    args = parser.parse_args()

    result = run_simulation(quiet=args.json or args.quiet)
    if args.json:
        print(json.dumps(result, indent=2))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
