"""GitHub CI status classification for autonomous repair loops."""

from __future__ import annotations

from typing import Any


def classify_check_runs(check_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize GitHub check runs and produce a repair objective when needed."""

    failed = [
        str(run.get("name") or "unnamed")
        for run in check_runs
        if str(run.get("status") or "") == "completed"
        and str(run.get("conclusion") or "") not in {"success", "neutral", "skipped"}
    ]
    return {
        "ok": not failed,
        "failed": failed,
        "total": len(check_runs),
        "repair_objective": "" if not failed else f"Diagnose and repair failing GitHub checks: {', '.join(failed)}.",
    }
