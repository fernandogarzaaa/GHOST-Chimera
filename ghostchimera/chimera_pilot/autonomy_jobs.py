"""Profile-aware autonomy jobs for Ghost Chimera."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..model_layer.minimind_lifecycle import MiniMindLifecycle
from .autonomy import AutonomyProfile, get_autonomy_profile
from .kernel import ChimeraPilotKernel


@dataclass(frozen=True)
class AutonomyJobSpec:
    name: str
    description: str
    high_impact: bool = False
    background_capable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "high_impact": self.high_impact,
            "background_capable": self.background_capable,
        }


@dataclass
class AutonomyJobResult:
    job: str
    status: str
    profile: str
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "preview", "skipped"}

    def finish(self) -> AutonomyJobResult:
        self.finished_at = time.time()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "job": self.job,
            "status": self.status,
            "ok": self.ok,
            "profile": self.profile,
            "summary": self.summary,
            "findings": list(self.findings),
            "artifacts": dict(self.artifacts),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


JOB_SPECS: dict[str, AutonomyJobSpec] = {
    "self-audit": AutonomyJobSpec(
        name="self-audit",
        description="Inspect Pilot status, policy posture, autonomy profile, and backend availability.",
        background_capable=True,
    ),
    "dependency-scan": AutonomyJobSpec(
        name="dependency-scan",
        description="Check optional runtime/development dependencies without installing anything.",
        background_capable=True,
    ),
    "test-regression": AutonomyJobSpec(
        name="test-regression",
        description="Run or preview the release regression command according to the active autonomy profile.",
        high_impact=True,
        background_capable=True,
    ),
    "memory-refresh": AutonomyJobSpec(
        name="memory-refresh",
        description="Write a local autonomy heartbeat artifact for later diagnostics.",
        background_capable=True,
    ),
    "model-health-check": AutonomyJobSpec(
        name="model-health-check",
        description="Report local model profiles and MiniMind runtime status.",
        background_capable=True,
    ),
    "repair-preview": AutonomyJobSpec(
        name="repair-preview",
        description="Produce an audit-to-repair preview plan without modifying source files.",
        high_impact=True,
    ),
}


class AutonomyJobRunner:
    """Runs bounded, profile-aware autonomy jobs."""

    def __init__(
        self,
        *,
        profile: AutonomyProfile | str | None = None,
        state_dir: str | Path | None = None,
        kernel: ChimeraPilotKernel | None = None,
    ) -> None:
        self.profile = (
            get_autonomy_profile(profile) if isinstance(profile, str) else profile or get_autonomy_profile("supervised")
        )
        self.state_dir = Path(state_dir or Path.home() / ".ghostchimera").expanduser()
        self.kernel = kernel or ChimeraPilotKernel.default(
            autonomy_level=self.profile.name, include_deterministic_backend=True
        )

    @staticmethod
    def list_jobs() -> list[dict[str, Any]]:
        return [JOB_SPECS[name].to_dict() for name in sorted(JOB_SPECS)]

    def run(self, job_name: str, *, execute: bool = False) -> AutonomyJobResult:
        key = job_name.strip().lower().replace("_", "-")
        if key not in JOB_SPECS:
            available = ", ".join(sorted(JOB_SPECS))
            raise ValueError(f"Unknown autonomy job '{job_name}'. Available jobs: {available}")
        method = getattr(self, f"_run_{key.replace('-', '_')}")
        return method(execute=execute).finish()

    def _regression_timeout_seconds(self) -> int:
        raw = os.environ.get("GHOSTCHIMERA_AUTONOMY_TEST_TIMEOUT", "").strip()
        try:
            timeout = int(raw) if raw else 300
        except ValueError:
            timeout = 300
        return max(60, min(timeout, 1800))

    def _run_self_audit(self, *, execute: bool = False) -> AutonomyJobResult:
        status = self.kernel.status()
        findings: list[dict[str, Any]] = []
        for backend in status.get("backends", []):
            if not backend.get("available"):
                findings.append({"severity": "warning", "area": "backend", "detail": backend})
        if self.profile.allow_background_jobs and self.profile.max_background_jobs > 0:
            findings.append(
                {"severity": "info", "area": "autonomy", "detail": "background jobs are enabled by profile"}
            )
        return AutonomyJobResult(
            job="self-audit",
            status="ok",
            profile=self.profile.name,
            summary=f"Audited {status.get('backend_count', 0)} Pilot backends.",
            findings=findings,
            artifacts={"pilot_status": status},
        )

    def _run_dependency_scan(self, *, execute: bool = False) -> AutonomyJobResult:
        minimind_status = (
            MiniMindLifecycle(
                profile_name=self.profile.local_model_profile,
                state_dir=self.state_dir,
            )
            .status()
            .to_dict()
        )
        checks = {
            "build": importlib.util.find_spec("build") is not None,
            "croniter": importlib.util.find_spec("croniter") is not None,
            "ruff": importlib.util.find_spec("ruff") is not None,
            "llama_cpp": importlib.util.find_spec("llama_cpp") is not None,
            "pyqpanda3": importlib.util.find_spec("pyqpanda3") is not None,
            "minimind": bool(minimind_status.get("inference_available")),
            "minimind_architecture": bool(minimind_status.get("architecture_embedded")),
        }
        findings = [
            {"severity": "info", "dependency": name, "available": available}
            for name, available in sorted(checks.items())
        ]
        return AutonomyJobResult(
            job="dependency-scan",
            status="ok",
            profile=self.profile.name,
            summary="Scanned optional runtime and development dependencies.",
            findings=findings,
            artifacts={"dependencies": checks, "minimind_status": minimind_status},
        )

    def _run_test_regression(self, *, execute: bool = False) -> AutonomyJobResult:
        command = [sys.executable, "-m", "pytest", "-q"]
        if not execute or not self.profile.allow_background_jobs:
            return AutonomyJobResult(
                job="test-regression",
                status="preview",
                profile=self.profile.name,
                summary="Regression command prepared but not executed by this profile/run.",
                artifacts={"command": command, "requires_execute": True},
            )
        timeout = self._regression_timeout_seconds()
        try:
            completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            return AutonomyJobResult(
                job="test-regression",
                status="error",
                profile=self.profile.name,
                summary=f"Regression suite timed out after {timeout} seconds.",
                findings=[
                    {
                        "severity": "error",
                        "area": "test-regression",
                        "detail": "Increase GHOSTCHIMERA_AUTONOMY_TEST_TIMEOUT or run a narrower focused suite.",
                    }
                ],
                artifacts={
                    "command": command,
                    "timeout_seconds": timeout,
                    "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
                    "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
                },
            )
        return AutonomyJobResult(
            job="test-regression",
            status="ok" if completed.returncode == 0 else "error",
            profile=self.profile.name,
            summary="Regression suite executed.",
            artifacts={
                "command": command,
                "timeout_seconds": timeout,
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            },
        )

    def _run_memory_refresh(self, *, execute: bool = False) -> AutonomyJobResult:
        payload = {
            "profile": self.profile.to_dict(),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "jobs": self.list_jobs(),
        }
        path = self.state_dir / "autonomy" / "memory_refresh.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return AutonomyJobResult(
            job="memory-refresh",
            status="ok",
            profile=self.profile.name,
            summary="Autonomy heartbeat artifact written.",
            artifacts={"path": str(path), "payload": payload},
        )

    def _run_model_health_check(self, *, execute: bool = False) -> AutonomyJobResult:
        minimind = MiniMindLifecycle(profile_name=self.profile.local_model_profile, state_dir=self.state_dir)
        status = minimind.status().to_dict()
        findings = [{"severity": "warning", "area": "minimind", "detail": error} for error in status.get("errors", [])]
        return AutonomyJobResult(
            job="model-health-check",
            status="ok" if status["available"] else "preview",
            profile=self.profile.name,
            summary=f"MiniMind profile resolved to {status['profile']}.",
            findings=findings,
            artifacts={"minimind": status},
        )

    def _run_repair_preview(self, *, execute: bool = False) -> AutonomyJobResult:
        audit = self._run_self_audit(execute=False).finish()
        dependency = self._run_dependency_scan(execute=False).finish()
        plan = [
            "Collect failing checks and unavailable backends.",
            "Generate a minimal patch plan scoped to failing surfaces.",
            "Run adversarial review against the plan before edits.",
            "Run focused tests, then the release validator.",
            "Require human approval before source mutation or training.",
        ]
        return AutonomyJobResult(
            job="repair-preview",
            status="preview",
            profile=self.profile.name,
            summary="Generated preview-only repair plan; no source files were modified.",
            findings=audit.findings + dependency.findings,
            artifacts={"plan": plan, "self_audit": audit.to_dict(), "dependency_scan": dependency.to_dict()},
        )


__all__ = ["AutonomyJobResult", "AutonomyJobRunner", "AutonomyJobSpec", "JOB_SPECS"]
