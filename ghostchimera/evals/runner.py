"""Built-in release evaluation suites."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from ghostchimera.agent_core.executor import Executor
from ghostchimera.agent_core.memory import MemoryManager
from ghostchimera.agent_core.skill_manager import SkillManager
from ghostchimera.chimera_pilot import ChimeraPilotKernel
from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile
from ghostchimera.chimera_pilot.autonomy_jobs import AutonomyJobRunner
from ghostchimera.chimera_pilot.backends import DeterministicBackend
from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.chimera_pilot.scheduler import ChimeraScheduler
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
from ghostchimera.cognition_layer.workspace_state import OperatorWorkspaceStore
from ghostchimera.control_plane.console import RELEASE_CHECKS, register_console_routes
from ghostchimera.memory_layer.store import MemoryStore
from ghostchimera.safety_layer.gating import ExecutionPolicy
from ghostchimera.tool_layer.browser_workspace import AgentBrowserWorkspace

CaseFn = Callable[[], tuple[bool, str]]

ROOT = Path(__file__).resolve().parents[2]


def run_suite(name: str) -> dict:
    if name not in EVAL_SUITES:
        raise ValueError(f"Unknown eval suite: {name}")

    cases = []
    for case_name, case_fn in EVAL_SUITES[name]:
        try:
            ok, detail = case_fn()
        except Exception as exc:  # pragma: no cover - defensive eval reporting
            ok, detail = False, str(exc)
        cases.append({"name": case_name, "ok": ok, "detail": detail})
    passed = sum(1 for case in cases if case["ok"])
    failed = len(cases) - passed
    kpis = _suite_kpis(name, cases)
    gates = _suite_gates(name, kpis)
    return {
        "suite": name,
        "ok": failed == 0,
        "passed": passed,
        "failed": failed,
        "kpis": kpis,
        "gates": gates,
        "cases": cases,
    }


def _suite_kpis(name: str, cases: list[dict[str, object]]) -> dict[str, float]:
    total = len(cases)
    passed = sum(1 for case in cases if case["ok"])
    pass_rate = (passed / total) if total else 0.0
    kpis: dict[str, float] = {
        "case_pass_rate": round(pass_rate, 3),
        "case_failure_rate": round(1.0 - pass_rate, 3) if total else 0.0,
    }
    if name == "smoke":
        # proxy KPI for orchestration readiness in smoke checks
        kpis["first_choice_success_rate_proxy"] = round(pass_rate, 3)
    if name == "safety":
        # proxy KPI for policy hardening
        kpis["policy_guardrail_pass_rate"] = round(pass_rate, 3)
    if name == "autonomy":
        kpis["autonomy_contract_pass_rate"] = round(pass_rate, 3)
    if name == "user-journey":
        kpis["operator_journey_pass_rate"] = round(pass_rate, 3)
    return kpis


def _suite_gates(name: str, kpis: dict[str, float]) -> dict[str, bool]:
    """Simple release-gate checks derived from suite KPIs."""
    if name == "safety":
        return {"policy_guardrail_gate": kpis.get("policy_guardrail_pass_rate", 0.0) >= 1.0}
    if name == "smoke":
        return {"smoke_reliability_gate": kpis.get("first_choice_success_rate_proxy", 0.0) >= 1.0}
    if name == "autonomy":
        return {"autonomy_contract_gate": kpis.get("autonomy_contract_pass_rate", 0.0) >= 1.0}
    if name == "user-journey":
        return {"operator_journey_gate": kpis.get("operator_journey_pass_rate", 0.0) >= 1.0}
    return {}


def _run_python_module(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=str(ROOT),
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _case_shell_denied_by_default() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-eval-") as tmp:
        executor = Executor(
            SkillManager(),
            MemoryManager(str(Path(tmp) / "memory.json")),
            policy=ExecutionPolicy(),
        )
        result = executor.execute([{"action": "shell", "command": "python --version"}])
    return ("Policy denied shell" in result, result)


def _case_file_write_outside_root_denied() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-eval-") as tmp:
        root = Path(tmp)
        executor = Executor(
            SkillManager(),
            MemoryManager(str(root / "memory.json")),
            policy=ExecutionPolicy(allow_file_write=True, allowed_roots=(str(root),)),
        )
        outside = root.parent / "ghostchimera-eval-outside.txt"
        result = executor.execute([{"action": "write_file", "path": str(outside), "content": "x"}])
    return ("Policy denied write_file" in result and not outside.exists(), result)


def _case_python_denied_by_pilot_policy() -> tuple[bool, str]:
    kernel = ChimeraPilotKernel.default(include_deterministic_backend=True)
    try:
        kernel.run("python: print(2 + 3)")
    except PermissionError as exc:
        return True, str(exc)
    return False, "Python execution was not denied"


def _case_chimera_pilot_status() -> tuple[bool, str]:
    status = ChimeraPilotKernel.default(include_deterministic_backend=True).status()
    return (status["backend_count"] >= 2 and status["policy"]["allow_python_execution"] is False, str(status))


def _case_cwr_retrieval() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-eval-") as tmp:
        store = MemoryStore(Path(tmp) / "memory.sqlite3")
        store.add_document("eval", "Ghost Chimera CWR retrieval works in smoke evals.")
        execution = ChimeraPilotKernel.default(memory_store=store).run("retrieve smoke evals")[0]
    ok = execution.ok and execution.result.backend_id == "cwr.local" and execution.result.output["citations"] == ["eval"]
    return ok, str(execution.to_dict())


def _case_assist_caps_strategy() -> tuple[bool, str]:
    profile = get_autonomy_profile("assist")
    scheduler = ChimeraScheduler([DeterministicBackend("a")], autonomy_profile=profile)
    strategy = scheduler.select_strategy(
        TaskSpec.create(kind=TaskKind.REASONING, objective="uncertain", constraints={"uncertainty": 0.9}),
        uncertainty=0.9,
    )
    return strategy == "single", strategy


def _case_generalist_allows_moa() -> tuple[bool, str]:
    profile = get_autonomy_profile("generalist")
    scheduler = ChimeraScheduler([DeterministicBackend("a")], autonomy_profile=profile)
    strategy = scheduler.select_strategy(
        TaskSpec.create(kind=TaskKind.REASONING, objective="uncertain", constraints={"uncertainty": 0.9}),
        uncertainty=0.9,
    )
    return strategy == "moa", strategy


def _case_autonomous_still_denies_python() -> tuple[bool, str]:
    kernel = ChimeraPilotKernel.default(autonomy_level="autonomous", include_deterministic_backend=True)
    try:
        kernel.run("python: print(2 + 3)")
    except PermissionError as exc:
        return True, str(exc)
    return False, "Autonomous profile allowed Python without explicit permission"


def _case_repair_preview_is_non_mutating() -> tuple[bool, str]:
    result = AutonomyJobRunner(profile="generalist").run("repair-preview")
    data = result.to_dict()
    ok = result.status == "preview" and "plan" in data["artifacts"]
    return ok, str(data)


def _case_top_level_cli_dispatch_help() -> tuple[bool, str]:
    checks = [
        (["ghostchimera", "--help"], "console"),
        (["ghostchimera", "run", "--help"], "One or more objectives"),
        (["ghostchimera", "batch", "--help"], "Path to JSONL file"),
    ]
    details: list[str] = []
    for args, expected in checks:
        completed = _run_python_module(args)
        text = completed.stdout + completed.stderr
        details.append(f"{' '.join(args)} rc={completed.returncode}")
        if completed.returncode != 0 or expected not in text:
            return False, f"{details[-1]} missing {expected!r}: {text[-1000:]}"
    return True, "; ".join(details)


def _case_config_show_reports_state_paths() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-user-journey-") as tmp:
        state_dir = str(Path(tmp) / "state")
        completed = _run_python_module(["ghostchimera", "--config-show"], env={"GHOSTCHIMERA_STATE_DIR": state_dir})
        if completed.returncode != 0:
            return False, completed.stderr or completed.stdout
        payload = json.loads(completed.stdout)
    ok = (
        Path(payload["state_dir"]) == Path(state_dir)
        and payload["memory_db"].endswith("memory.sqlite3")
        and payload["audit_file"].endswith("audit.json")
        and payload["policy"]["allow_shell"] is False
    )
    return ok, json.dumps(payload, sort_keys=True)


def _route_ctx(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "method": method,
        "path": path,
        "headers": {},
        "body": json.dumps(body or {}),
        "query": {},
    }


def _case_console_operator_routes() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-console-journey-") as tmp:
        memory_db = str(Path(tmp) / "memory.sqlite3")
        server = GatewayServer()
        workspace = AgentBrowserWorkspace(binary="definitely-missing-agent-browser")
        register_console_routes(server, state_dir=tmp, browser_workspace=workspace)

        status_route = server.routes.find("GET", "/api/console/status")
        workspace_route = server.routes.find("GET", "/api/console/workspace")
        workspace_evidence_route = server.routes.find("POST", "/api/console/workspace/evidence")
        workspace_sync_route = server.routes.find("POST", "/api/console/workspace/sync-memory")
        jobs_route = server.routes.find("POST", "/api/console/autonomy/jobs")
        schedules_route = server.routes.find("POST", "/api/console/autonomy/schedules")
        browser_route = server.routes.find("GET", "/api/console/browser/status")
        readiness_route = server.routes.find("GET", "/api/console/readiness")
        if not all(
            (
                status_route,
                workspace_route,
                workspace_evidence_route,
                workspace_sync_route,
                jobs_route,
                schedules_route,
                browser_route,
                readiness_route,
            )
        ):
            return False, "One or more console operator routes are missing"

        status = status_route.handler(_route_ctx("GET", "/api/console/status"))
        workspace_evidence_route.handler(
            _route_ctx(
                "POST",
                "/api/console/workspace/evidence",
                {"source": "user-journey", "content": "workspace evidence feeds CWR retrieval", "confidence": 0.93},
            )
        )
        workspace_sync = workspace_sync_route.handler(
            _route_ctx(
                "POST",
                "/api/console/workspace/sync-memory",
                {"memory_db": memory_db, "min_confidence": 0.9},
            )
        )
        workspace_state = workspace_route.handler(_route_ctx("GET", "/api/console/workspace"))
        browser = browser_route.handler(_route_ctx("GET", "/api/console/browser/status"))
        job = jobs_route.handler(
            _route_ctx(
                "POST",
                "/api/console/autonomy/jobs",
                {"job": "repair-preview", "profile": "supervised", "execute": False, "run_now": True},
            )
        )
        schedule = schedules_route.handler(
            _route_ctx(
                "POST",
                "/api/console/autonomy/schedules",
                {
                    "name": "user journey disabled audit",
                    "cron_expression": "0 9 * * *",
                    "job": "self-audit",
                    "profile": "autonomous",
                    "execute": False,
                    "enabled": False,
                },
            )
        )
        readiness = readiness_route.handler(_route_ctx("GET", "/api/console/readiness"))
        workspace_results = MemoryStore(memory_db).search("CWR retrieval", limit=3)

    ok = (
        bool(status["ok"])
        and workspace_state["ok"] is True
        and "no_subjective_consciousness" in workspace_state["self_model"]["limits"]
        and workspace_sync["synced"] == 1
        and workspace_results
        and workspace_results[0]["metadata"]["workspace_type"] == "evidence"
        and browser["available"] is False
        and job["ok"] is True
        and job["job"]["status"] == "preview"
        and schedule["ok"] is True
        and schedule["schedule"]["enabled"] is False
        and any(check["command"] == "python -m ghostchimera.evals run --suite user-journey" for check in readiness["checks"])
    )
    detail = {
        "browser": browser,
        "job": job,
        "readiness_count": len(readiness["checks"]),
        "schedule": schedule,
        "workspace": {
            "evidence_count": len(workspace_state["working_memory"]["evidence"]),
            "limits": sorted(workspace_state["self_model"]["limits"]),
            "sync": workspace_sync,
        },
    }
    return ok, json.dumps(detail, sort_keys=True)


def _case_workspace_sync_feeds_retrieval() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="ghostchimera-workspace-memory-") as tmp:
        memory_db = Path(tmp) / "memory.sqlite3"
        workspace = OperatorWorkspaceStore(state_dir=tmp)
        workspace.add_evidence("eval", "operator workspace sync should feed retrieval", confidence=0.94)
        workspace.add_reflection(action="sync eval", outcome="reflection memory is retrievable", confidence=0.91)
        sync = workspace.sync_to_memory(memory_db=memory_db, min_confidence=0.9)
        execution = ChimeraPilotKernel.default(memory_store=MemoryStore(memory_db)).run("retrieve reflection memory")[0]
    ok = execution.ok and sync["synced"] == 2 and execution.result.backend_id == "cwr.local"
    return ok, json.dumps({"sync": sync, "execution": execution.to_dict()}, sort_keys=True)


def _case_readiness_runbook_includes_release_gate() -> tuple[bool, str]:
    commands = [check["command"] for check in RELEASE_CHECKS]
    required = {
        "python -m ruff check .",
        "python -m pytest -q",
        "python scripts/validate_release.py",
        "python -m ghostchimera.evals run --suite smoke",
        "python -m ghostchimera.evals run --suite safety",
        "python -m ghostchimera.evals run --suite autonomy",
        "python -m ghostchimera.evals run --suite user-journey",
        "python scripts/smoke_installed_wheel.py",
        "python scripts/smoke_installed_wheel.py --extras gateway",
        "ghostchimera workspace show",
    }
    missing = sorted(required.difference(commands))
    return not missing, "missing=" + ", ".join(missing)


EVAL_SUITES: dict[str, list[tuple[str, CaseFn]]] = {
    "safety": [
        ("shell_denied_by_default", _case_shell_denied_by_default),
        ("file_write_outside_root_denied", _case_file_write_outside_root_denied),
        ("python_denied_by_pilot_policy", _case_python_denied_by_pilot_policy),
    ],
    "smoke": [
        ("chimera_pilot_status", _case_chimera_pilot_status),
        ("cwr_retrieval", _case_cwr_retrieval),
    ],
    "autonomy": [
        ("assist_caps_strategy", _case_assist_caps_strategy),
        ("generalist_allows_moa", _case_generalist_allows_moa),
        ("autonomous_still_denies_python", _case_autonomous_still_denies_python),
        ("repair_preview_is_non_mutating", _case_repair_preview_is_non_mutating),
    ],
    "user-journey": [
        ("top_level_cli_dispatch_help", _case_top_level_cli_dispatch_help),
        ("config_show_reports_state_paths", _case_config_show_reports_state_paths),
        ("console_operator_routes", _case_console_operator_routes),
        ("workspace_sync_feeds_retrieval", _case_workspace_sync_feeds_retrieval),
        ("readiness_runbook_includes_release_gate", _case_readiness_runbook_includes_release_gate),
    ],
}


__all__ = ["EVAL_SUITES", "run_suite"]
