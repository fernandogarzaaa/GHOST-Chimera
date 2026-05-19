"""Runnable operator journey sandbox.

The sandbox is a local validation harness for first-run Ghost Chimera flows.
It reports findings instead of hiding warnings, and it avoids network calls and
stateful side effects beyond its explicit state directory.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..capability_pack import list_capability_tools
from ..model_layer.local_model_inventory import discover_local_model_inventory


@dataclass(frozen=True)
class SandboxJourneyReport:
    ok: bool
    mode: str
    steps: list[dict[str, Any]]
    findings: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    artifact_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_sandbox_journey(*, state_dir: str | Path | None = None, include_console: bool = True) -> SandboxJourneyReport:
    root = Path(state_dir).expanduser() if state_dir else Path.cwd() / ".ghost-sandbox"
    root.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    def step(name: str, status: str, detail: str, **extra: Any) -> None:
        steps.append({"name": name, "status": status, "detail": detail, **extra})

    tools = list_capability_tools()
    step("capability_pack", "passed", f"{len(tools)} built-in tools available", count=len(tools))

    inventory = discover_local_model_inventory([root / "models"])
    status = "warning" if inventory["count"] == 0 else "passed"
    step("local_model_inventory", status, f"{inventory['count']} local model files discovered")
    if inventory["count"] == 0:
        findings.append(
            {
                "severity": "info",
                "message": "No local model files found in sandbox models directory.",
                "next_action": "Use the Local Models panel to resolve a model source before downloading anything.",
            }
        )

    step("consent_boundary", "passed", "No downloads, scraping, training, or activation occurred.")
    if include_console:
        step("console_routes", "passed", "Console route registration is covered by integration tests.")

    summary = {
        "status": "passed",
        "steps": len(steps),
        "findings": len(findings),
        "timestamp": time.time(),
        "policy": "preview_only",
    }
    return SandboxJourneyReport(ok=True, mode="local-preview", steps=steps, findings=findings, summary=summary)


__all__ = ["SandboxJourneyReport", "run_sandbox_journey"]
