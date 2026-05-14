"""Competitive capability inspection for Ghost Chimera.

This module keeps the release conversation grounded in real repo surfaces.  It
does not claim a feature is market-leading because it exists in a roadmap; it
checks whether the files and symbols that implement that capability are present.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CapabilitySurface:
    """A source surface required for a competitive capability."""

    path: str
    symbol: str = ""
    description: str = ""


@dataclass(frozen=True)
class CompetitiveCapability:
    """A benchmark capability Ghost Chimera should expose and release-gate."""

    id: str
    name: str
    benchmark: str
    competitors: tuple[str, ...]
    priority: int
    description: str
    required_surfaces: tuple[CapabilitySurface, ...]
    improvement: str
    release_gate: str


COMPETITIVE_CAPABILITIES: tuple[CompetitiveCapability, ...] = (
    CompetitiveCapability(
        id="background_task_orchestration",
        name="Background Task Orchestration",
        benchmark="Codex-style cloud/background delegation plus recurring autonomous work.",
        competitors=("OpenAI Codex", "Claude Code background agents", "Hermes Agent"),
        priority=5,
        description="Queue, schedule, and inspect long-running autonomy jobs from CLI and console surfaces.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/chimera_pilot/autonomy_queue.py", "AutonomyJobQueue", "persistent job queue"),
            CapabilitySurface("ghostchimera/chimera_pilot/cron_scheduler.py", "CronScheduler", "recurring scheduler"),
            CapabilitySurface("ghostchimera/control_plane/console.py", "/api/console/autonomy/jobs", "dashboard job routes"),
            CapabilitySurface("ghostchimera/control_plane/cli.py", "autonomy", "operator CLI"),
        ),
        improvement="Add distributed workers and resumable worktree sandboxes for multi-machine task execution.",
        release_gate="python -m ghostchimera.evals run --suite autonomy",
    ),
    CompetitiveCapability(
        id="repository_release_gates",
        name="Repository Release Gates",
        benchmark="Codex-style verifiable changes with logs, tests, package smokes, and runbook evidence.",
        competitors=("OpenAI Codex", "LangGraph", "CrewAI"),
        priority=5,
        description="Release validators, eval suites, build smokes, and console readiness make changes auditable.",
        required_surfaces=(
            CapabilitySurface("scripts/validate_release.py", "check_release_hardening", "release validator"),
            CapabilitySurface("docs/RELEASE_CHECKLIST.md", "Required checks", "operator checklist"),
            CapabilitySurface("ghostchimera/evals/runner.py", "EVAL_SUITES", "built-in eval registry"),
            CapabilitySurface("scripts/smoke_installed_wheel.py", "smoke", "installed artifact smoke"),
        ),
        improvement="Emit signed machine-readable release attestations from each validation run.",
        release_gate="python scripts/validate_release.py",
    ),
    CompetitiveCapability(
        id="browser_visual_validation",
        name="Browser And Visual Validation",
        benchmark="Codex app/browser-style UI validation for web work and operator diagnostics.",
        competitors=("OpenAI Codex", "Claude Code", "Hermes Agent"),
        priority=4,
        description="Gateway browser routes and optional agent-browser workspace let Ghost inspect rendered pages.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/tool_layer/browser_workspace.py", "AgentBrowserWorkspace", "browser session adapter"),
            CapabilitySurface("ghostchimera/control_plane/console.py", "/api/console/browser/snapshot", "dashboard browser snapshot route"),
            CapabilitySurface("tests/test_console.py", "test_console_registers_browser_workspace_routes", "route coverage"),
        ),
        improvement="Capture screenshot artifacts and pixel assertions in the release gate for frontend tasks.",
        release_gate="python -m ghostchimera.evals run --suite user-journey",
    ),
    CompetitiveCapability(
        id="hooks_policy_gateway",
        name="Hooks And Policy Gateway",
        benchmark="Claude Code hook/MCP permission model plus local safety controls.",
        competitors=("Claude Code", "OpenAI Codex", "OpenClaw"),
        priority=5,
        description="Pre/post hooks, approval policy, desktop policy, SSRF protection, and DPI safety checks.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/chimera_pilot/hooks.py", "HookRegistry", "tool hook registry"),
            CapabilitySurface("ghostchimera/safety_layer/approval.py", "ApprovalPolicy", "human approval gate"),
            CapabilitySurface("ghostchimera/safety_layer/ssrf.py", "SSRFPolicy", "network egress guard"),
            CapabilitySurface("ghostchimera/safety_layer/lobster_trap.py", "BuiltinDPIEngine", "prompt/data inspection"),
            CapabilitySurface("ghostchimera/chimera_pilot/desktop_policy.py", "DESKTOP_ACTION_CLASSES", "desktop action policy"),
        ),
        improvement="Expose policy simulation and hook dry-run diffs in the console before enabling live actions.",
        release_gate="python -m ghostchimera.evals run --suite safety",
    ),
    CompetitiveCapability(
        id="mcp_tool_gateway",
        name="MCP Tool Gateway",
        benchmark="Claude/Hermes-style dynamic external tool integration through MCP.",
        competitors=("Claude Code", "Hermes Agent", "OpenAI Codex"),
        priority=5,
        description="Native MCP server/client surfaces, Pilot MCP backend, and credential-aware wrapping.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/mcp/server.py", "MCPServer", "MCP server"),
            CapabilitySurface("ghostchimera/mcp/client.py", "MCPClient", "MCP client"),
            CapabilitySurface("ghostchimera/chimera_pilot/backends/mcp.py", "MCPBackend", "Pilot MCP backend"),
            CapabilitySurface("ghostchimera/chimera_pilot/mcp_wrapper.py", "MCPRegistry", "tool registry"),
        ),
        improvement="Add per-task MCP tool discovery/search so large tool registries do not bloat model context.",
        release_gate="python -m ghostchimera.evals run --suite smoke",
    ),
    CompetitiveCapability(
        id="isolated_subagents",
        name="Isolated Subagents And Agent Teams",
        benchmark="Claude subagent and CrewAI crew patterns for delegated specialist work.",
        competitors=("Claude Code", "CrewAI", "OpenAI Codex"),
        priority=5,
        description="Subagents, agent pools, and Mixture-of-Agents scoring support delegated reasoning.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/chimera_pilot/subagent.py", "SubagentPool", "subagent contract"),
            CapabilitySurface("ghostchimera/chimera_pilot/agent_pool.py", "BatchAgent", "batch agent pool"),
            CapabilitySurface("ghostchimera/chimera_pilot/mixture_of_agents.py", "MixtureOfAgents", "MoA scorer"),
            CapabilitySurface("tests/test_subagent.py", "MixtureOfAgentsTests", "subagent and MoA coverage"),
        ),
        improvement="Add role templates with explicit tool allowlists and isolated run state per agent.",
        release_gate="python -m ghostchimera.evals run --suite coverage",
    ),
    CompetitiveCapability(
        id="durable_stateful_flows",
        name="Durable Stateful Flows",
        benchmark="LangGraph/CrewAI-style persistent, resumable workflows for long-horizon tasks.",
        competitors=("LangGraph", "CrewAI", "OpenAI Codex"),
        priority=5,
        description="Checkpoints, workspace state, queue records, and telemetry preserve execution context.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/chimera_pilot/checkpoint.py", "CheckpointManager", "checkpoint manager"),
            CapabilitySurface("ghostchimera/cognition_layer/workspace_state.py", "OperatorWorkspaceStore", "workspace state"),
            CapabilitySurface("ghostchimera/chimera_pilot/autonomy_queue.py", "list_jobs", "job history"),
            CapabilitySurface("ghostchimera/chimera_pilot/telemetry.py", "InMemoryTelemetryStore", "telemetry"),
        ),
        improvement="Introduce deterministic replay IDs for side-effecting tool calls and workflow resumes.",
        release_gate="python -m ghostchimera.evals run --suite workspace",
    ),
    CompetitiveCapability(
        id="personal_local_context",
        name="Personal Local Context",
        benchmark="Local-first personal memory and RAG handoff beyond generic coding-agent context.",
        competitors=("OpenAI Codex", "Claude Code", "Hermes Agent"),
        priority=4,
        description="Personal MiniMind grants scoped consent, ingests local/email context, and builds RAG handoffs.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/model_layer/minimind_personal_agent.py", "MiniMindPersonalAgent", "personal agent"),
            CapabilitySurface("ghostchimera/personalization/document_ingester.py", "DocumentIngester", "document ingestion"),
            CapabilitySurface("ghostchimera/personalization/email_ingester.py", "EmailIngester", "email ingestion"),
            CapabilitySurface("docs/PERSONAL_MINIMIND_PRIVACY.md", "whole-machine", "privacy documentation"),
        ),
        improvement="Add encrypted local memory storage and per-source retention controls for public beta.",
        release_gate="ghostchimera minimind personal-status",
    ),
    CompetitiveCapability(
        id="model_routing_local_runtime",
        name="Model Routing And Local Runtime",
        benchmark="Provider-flexible execution with optional local quantized inference.",
        competitors=("OpenAI Codex", "Claude Code", "Hermes Agent", "OpenClaw"),
        priority=4,
        description="Provider router, local profiles, MiniMind contracts, llama.cpp runtime, and specialization hints.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/model_layer/router.py", "ModelRouter", "provider router"),
            CapabilitySurface("ghostchimera/model_layer/local_profiles.py", "list_local_model_profiles", "local profiles"),
            CapabilitySurface("ghostchimera/model_layer/llamacpp_runtime.py", "LlamaCppRuntime", "GGUF runtime"),
            CapabilitySurface("ghostchimera/model_layer/minimind_runtime.py", "MiniMindTransformersRuntime", "MiniMind runtime"),
            CapabilitySurface("ghostchimera/model_layer/runtime_specialization.py", "warm_runtime_specialization_cache", "runtime specialization"),
        ),
        improvement="Benchmark local profiles on first run and auto-select the fastest acceptable model plan.",
        release_gate="ghostchimera local-model check",
    ),
    CompetitiveCapability(
        id="redteam_safety_eval",
        name="Red-Team Safety Evals",
        benchmark="Agent safety hardening against prompt injection, exfiltration, PII, and unsafe tool use.",
        competitors=("OpenAI Codex", "Claude Code", "OpenClaw"),
        priority=5,
        description="Red-team evals, DPI detection, security monitor, and production doctor form safety gates.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/evals/runner.py", "redteam", "red-team suite"),
            CapabilitySurface("ghostchimera/safety_layer/security_monitor.py", "SecurityMonitor", "event monitor"),
            CapabilitySurface("ghostchimera/control_plane/doctor.py", "run_doctor", "production doctor"),
            CapabilitySurface("SECURITY.md", "Reporting", "security policy"),
        ),
        improvement="Add adversarial MCP/tool-schema tests and stored runbooks for every blocked class.",
        release_gate="python -m ghostchimera.evals run --suite redteam",
    ),
    CompetitiveCapability(
        id="automated_code_review",
        name="Automated Code Review",
        benchmark="Codex auto-review: compare PR intent, diff, codebase context, and tests.",
        competitors=("OpenAI Codex", "Claude Code"),
        priority=4,
        description="Ghost reviews local PR diffs for blocking release, security, and test-coverage risks.",
        required_surfaces=(
            CapabilitySurface("ghostchimera/chimera_pilot/pr_review.py", "run_pr_review", "deterministic PR review engine"),
            CapabilitySurface("ghostchimera/skill_layer/code_search.py", "CodeSearchSkill", "code search"),
            CapabilitySurface("ghostchimera/evals/runner.py", "EVAL_SUITES", "eval runner"),
            CapabilitySurface("ghostchimera/control_plane/cli.py", "review-pr", "operator CLI"),
            CapabilitySurface("ghostchimera/control_plane/console.py", "/api/console/review-pr", "dashboard route"),
            CapabilitySurface("tests/test_pr_review.py", "PRReviewTests", "review tests"),
        ),
        improvement="Optional next step: post review findings directly to GitHub PR conversations when credentials are configured.",
        release_gate="ghostchimera review-pr --base HEAD --head HEAD",
    ),
)


def _surface_status(surface: CapabilitySurface, root: Path) -> dict[str, Any]:
    path = root / surface.path
    present = path.exists()
    symbol_present = False
    if present and surface.symbol:
        try:
            symbol_present = surface.symbol in path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            symbol_present = False
    else:
        symbol_present = present
    return {
        "path": surface.path,
        "symbol": surface.symbol,
        "description": surface.description,
        "present": present,
        "symbol_present": symbol_present,
        "ok": present and symbol_present,
    }


def inspect_capabilities(root: str | Path | None = None) -> dict[str, Any]:
    """Return a competitive capability report for the current checkout."""

    base = Path(root).resolve() if root else ROOT
    capabilities: list[dict[str, Any]] = []
    weighted_score = 0.0
    weighted_max = 0.0
    for capability in COMPETITIVE_CAPABILITIES:
        surfaces = [_surface_status(surface, base) for surface in capability.required_surfaces]
        present_count = sum(1 for surface in surfaces if surface["ok"])
        total = len(surfaces)
        coverage = present_count / total if total else 0.0
        if coverage >= 1.0:
            status = "complete"
        elif coverage > 0.0:
            status = "partial"
        else:
            status = "missing"
        weighted_score += capability.priority * coverage
        weighted_max += capability.priority
        capabilities.append(
            {
                "id": capability.id,
                "name": capability.name,
                "status": status,
                "coverage": round(coverage, 3),
                "present_surfaces": present_count,
                "required_surfaces": total,
                "priority": capability.priority,
                "benchmark": capability.benchmark,
                "competitors": list(capability.competitors),
                "description": capability.description,
                "surfaces": surfaces,
                "missing_surfaces": [surface for surface in surfaces if not surface["ok"]],
                "improvement": capability.improvement,
                "release_gate": capability.release_gate,
            }
        )
    score_ratio = weighted_score / weighted_max if weighted_max else 0.0
    if score_ratio >= 0.9:
        grade = "superior-beta"
    elif score_ratio >= 0.75:
        grade = "competitive-beta"
    elif score_ratio >= 0.5:
        grade = "emerging"
    else:
        grade = "incomplete"
    gaps = sorted(
        (cap for cap in capabilities if cap["status"] != "complete"),
        key=lambda item: (-int(item["priority"]), float(item["coverage"]), str(item["name"])),
    )
    return {
        "ok": score_ratio >= 0.75 and not any(cap["status"] == "missing" and cap["priority"] >= 5 for cap in capabilities),
        "root": str(base),
        "score": round(weighted_score, 2),
        "max_score": round(weighted_max, 2),
        "score_ratio": round(score_ratio, 3),
        "grade": grade,
        "capability_count": len(capabilities),
        "complete_count": sum(1 for cap in capabilities if cap["status"] == "complete"),
        "partial_count": sum(1 for cap in capabilities if cap["status"] == "partial"),
        "missing_count": sum(1 for cap in capabilities if cap["status"] == "missing"),
        "benchmarks": sorted({competitor for cap in capabilities for competitor in cap["competitors"]}),
        "capabilities": capabilities,
        "top_gaps": gaps[:5],
        "positioning": (
            "Ghost Chimera is strongest where agent orchestration, local-first memory, MCP, hooks, "
            "desktop/browser control, automated PR review, and release evals converge. The next beta focus "
            "is direct GitHub review posting and deeper replayable workflow durability."
        ),
    }


def format_capability_report(payload: dict[str, Any]) -> str:
    """Render a compact Markdown report for humans."""

    lines = [
        "# Ghost Chimera Competitive Capability Report",
        "",
        f"- Grade: {payload['grade']}",
        f"- Score: {payload['score']} / {payload['max_score']} ({payload['score_ratio']})",
        f"- Complete: {payload['complete_count']} / {payload['capability_count']}",
        f"- Benchmarks: {', '.join(payload['benchmarks'])}",
        "",
        "## Capabilities",
    ]
    for cap in payload["capabilities"]:
        missing = len(cap["missing_surfaces"])
        lines.append(
            f"- **{cap['name']}**: {cap['status']} ({cap['coverage']}) "
            f"against {', '.join(cap['competitors'])}; release gate: `{cap['release_gate']}`"
        )
        if missing:
            lines.append(f"  - Gap: {cap['improvement']}")
    lines.extend(["", "## Positioning", payload["positioning"]])
    return "\n".join(lines) + "\n"


__all__ = [
    "COMPETITIVE_CAPABILITIES",
    "CapabilitySurface",
    "CompetitiveCapability",
    "format_capability_report",
    "inspect_capabilities",
]
