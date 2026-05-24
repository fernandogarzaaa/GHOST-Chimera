"""Measured public superiority scorecard for Ghost Chimera.

The scorecard is deliberately bounded: it measures operator experience,
platform breadth, and autonomy depth from concrete local surfaces.  It does
not claim sentience, AGI, or universal superiority.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEY_PARTS = ("api_key", "token", "secret", "password", "credential", "client_secret")
WINDOWS_PRIVATE_PATH = re.compile(r"[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\\\s\"]+", re.IGNORECASE)
TOKEN_LIKE = re.compile(r"\b(?:sk|ghp|github_pat|hf|xoxb|ya29)[-_A-Za-z0-9]{8,}\b")


@dataclass(frozen=True)
class ScorecardEvidence:
    """Concrete artifact proving a scorecard criterion."""

    id: str
    label: str
    status: str
    surface: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "surface": self.surface,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class NextBestAction:
    """Action that moves an operator toward first useful value."""

    id: str
    label: str
    tab: str
    priority: int
    reason: str
    command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "tab": self.tab,
            "priority": self.priority,
            "reason": self.reason,
            "command": self.command,
        }


@dataclass(frozen=True)
class SuperiorityDimension:
    """One weighted dimension in the public scorecard."""

    id: str
    label: str
    score: float
    weight: float
    evidence: list[ScorecardEvidence] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "score": round(self.score, 3),
            "weight": self.weight,
            "weighted_score": round(self.score * self.weight, 3),
            "evidence": [item.to_dict() for item in self.evidence],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class OperatorJourneyCase:
    """Deterministic browser/operator proof case."""

    id: str
    label: str
    required_surface: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "required_surface": self.required_surface,
            "status": self.status,
        }


@dataclass(frozen=True)
class SuperiorityScorecard:
    """Bounded scorecard suitable for CI, Console, and public docs."""

    dimensions: list[SuperiorityDimension]
    next_best_actions: list[NextBestAction]
    journey_cases: list[OperatorJourneyCase]
    generated_from: str = "local-static-and-console-surfaces"

    @property
    def score_ratio(self) -> float:
        total_weight = sum(item.weight for item in self.dimensions) or 1.0
        return round(sum(item.score * item.weight for item in self.dimensions) / total_weight, 3)

    @property
    def ok(self) -> bool:
        return self.score_ratio >= 0.85 and not any(item.blockers for item in self.dimensions)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "score_ratio": self.score_ratio,
            "grade": _grade(self.score_ratio),
            "dimensions": [item.to_dict() for item in self.dimensions],
            "next_best_actions": [item.to_dict() for item in self.next_best_actions],
            "journey_cases": [item.to_dict() for item in self.journey_cases],
            "claim_boundary": {
                "bounded_claim": "measured operator UX, platform breadth, and autonomy-depth advantage",
                "no_sentience_claim": True,
                "no_agi_claim": True,
                "proof": "executable scorecard plus browser E2E contract",
            },
            "generated_from": self.generated_from,
            "secret_policy": {"secrets_are_write_only": True, "raw_secret_values_returned": False},
        }
        return _redact_value(payload)


def build_superiority_scorecard(
    *,
    operator_summary: dict[str, Any] | None = None,
    capabilities: dict[str, Any] | None = None,
    routes: list[str] | None = None,
    static_html: str = "",
    static_app: str = "",
    e2e_artifacts: dict[str, Any] | None = None,
) -> SuperiorityScorecard:
    """Build a deterministic scorecard from local Console and repo surfaces."""

    summary = _redact_value(operator_summary or {})
    caps = _redact_value(capabilities or {})
    route_set = set(routes or [])
    html = static_html or _read_text("ghostchimera/control_plane/static/index.html")
    app = static_app or _read_text("ghostchimera/control_plane/static/app.js")

    dimensions = [
        _operator_ux_dimension(summary, route_set, html, app),
        _platform_breadth_dimension(summary, caps, route_set, html, app),
        _autonomy_depth_dimension(summary, route_set, html, app),
    ]
    scorecard = SuperiorityScorecard(
        dimensions=dimensions,
        next_best_actions=_next_best_actions(summary, dimensions),
        journey_cases=_journey_cases(html, app, route_set, e2e_artifacts or {}),
    )
    return scorecard


def build_local_operator_summary(
    *,
    state_dir: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a secret-safe local operator summary for CLI and offline scorecards."""

    from .capability_admission import CapabilityAdmissionStore
    from .config import GhostChimeraConfig
    from .control_plane.config import CONFIG_FILE, load_config
    from .control_plane.evolution import list_candidates, list_sources
    from .integrations.remote_control import RemoteControlStore
    from .personalization.path_state import get_active_ghost_path
    from .trust_runtime import TrustRuntimeStore

    runtime_config = GhostChimeraConfig.from_env()
    resolved_state_dir = Path(state_dir).expanduser() if state_dir else runtime_config.state_dir
    resolved_config_path = Path(config_path).expanduser() if config_path else CONFIG_FILE
    config = load_config(resolved_config_path)
    model_config = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    sources: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    trust_payload: dict[str, Any] = {"ready": False, "warnings": ["Trust Runtime status unavailable."]}
    remote_payload: dict[str, Any] = {"counts": {}}
    admission_payload: dict[str, Any] = {"production_ready": False, "counts": {}}

    with contextlib.suppress(Exception):
        sources = list_sources(resolved_state_dir)
    with contextlib.suppress(Exception):
        candidates = list_candidates(resolved_state_dir)
    with contextlib.suppress(Exception):
        trust_payload = TrustRuntimeStore(resolved_state_dir).trust_status()
    with contextlib.suppress(Exception):
        remote_payload = RemoteControlStore(resolved_state_dir).status()
    with contextlib.suppress(Exception):
        admission_payload = CapabilityAdmissionStore(resolved_state_dir).summary()

    approved_sources = sum(1 for item in sources if str(item.get("consent_status") or "") == "approved")
    pending_candidates = sum(1 for item in candidates if str(item.get("status") or "") in {"discovered", "reviewed"})
    warnings: list[str] = []
    if not str(model_config.get("provider") or "").strip():
        warnings.append("No active model provider configured.")
    warnings.extend(str(item) for item in trust_payload.get("warnings", []) if str(item).strip())
    warnings.extend(str(item) for item in admission_payload.get("warnings", []) if str(item).strip())

    summary = {
        "ok": not warnings,
        "state_dir_configured": bool(resolved_state_dir),
        "config_path_configured": bool(resolved_config_path),
        "active_path": get_active_ghost_path(config=config),
        "model": {
            "provider": str(model_config.get("provider") or ""),
            "model": str(model_config.get("model") or ""),
            "base_url": str(model_config.get("base_url") or ""),
            "api_key_configured": bool(model_config.get("api_key") or model_config.get("oauth_token")),
        },
        "counts": {
            "learning_sources": len(sources),
            "approved_sources": approved_sources,
            "candidates": len(candidates),
            "pending_candidates": pending_candidates,
        },
        "trust": trust_payload,
        "remote": {"counts": remote_payload.get("counts", {})},
        "capability_admission": admission_payload,
        "production_readiness": {
            "ready": bool(trust_payload.get("ready")) and bool(admission_payload.get("production_ready")),
            "trust": trust_payload.get("production_readiness", {}),
            "capability_admission": {
                "production_ready": admission_payload.get("production_ready", False),
                "counts": admission_payload.get("counts", {}),
            },
        },
        "warnings": list(dict.fromkeys(warnings)),
    }
    return _redact_value(summary)


def format_superiority_markdown(payload: dict[str, Any]) -> str:
    """Format a scorecard payload as compact Markdown."""

    lines = [
        "# Ghost Chimera Public Superiority Scorecard",
        "",
        f"- Status: {'PASS' if payload.get('ok') else 'REVIEW'}",
        f"- Score Ratio: {payload.get('score_ratio')}",
        f"- Grade: {payload.get('grade')}",
        "- Claim Boundary: measured operator UX, platform breadth, and autonomy depth only",
        "",
        "## Dimensions",
    ]
    for dimension in payload.get("dimensions", []):
        lines.append(f"- {dimension['label']}: {dimension['score']} ({len(dimension.get('evidence', []))} evidence items)")
    lines.append("")
    lines.append("## Next Best Actions")
    for action in payload.get("next_best_actions", [])[:8]:
        lines.append(f"- [{action['tab']}] {action['label']}: {action['reason']}")
    return "\n".join(lines) + "\n"


def _operator_ux_dimension(summary: dict[str, Any], routes: set[str], html: str, app: str) -> SuperiorityDimension:
    checks = [
        ("operator_workbench", "Operator Workbench shell", "operatorWorkbench" in html, "static/index.html"),
        ("command_search", "Command/search intake", "operatorCommandSearch" in html, "static/index.html"),
        ("next_actions", "Next best actions", "nextBestActions" in html and "/api/console/superiority" in app, "Console"),
        ("guided_setup", "Guided no-code setup", "setupSteps" in html and "operator/setup-step" in app, "Console"),
        ("conversation", "Always-on conversation", "ghostConversationPanel" in html, "Console"),
        ("config_no_code", "No-code config and model discovery", "modelDiscoveryGrid" in html and "providerAuthGrid" in html, "Config"),
        ("trust_visibility", "Trust and evidence visibility", "trust" in html and "/api/console/trust/summary" in app, "Trust Runtime"),
        ("recovery_guidance", "Warnings and recovery guidance", bool(summary.get("warnings") is not None), "operator summary"),
        ("recent_runs", "Run/history surfaces", "runHistory" in html and "homeRunObjective" in html, "Run"),
        ("browser_e2e", "Browser E2E proof marker", "browserE2EStatus" in html, "E2E"),
    ]
    return _dimension("operator_ux", "Operator UX", checks, weight=0.4)


def _platform_breadth_dimension(
    summary: dict[str, Any], capabilities: dict[str, Any], routes: set[str], html: str, app: str
) -> SuperiorityDimension:
    capability_count = int(capabilities.get("capability_count") or 0)
    checks = [
        ("capability_matrix", "Competitive capability matrix", bool(capabilities.get("ok")) and capability_count >= 10, "capabilities"),
        ("models", "Model discovery/provider modularity", "/api/console/models/discovery" in routes or "modelDiscoveryGrid" in html, "Models"),
        ("rag", "MiniMind and RAG builder", "ragBuildPlan" in html and "personalMiniMindStatus" in html, "RAG"),
        ("mcp", "MCP and trust registry", "/api/console/mcp/trust" in routes or "mcpStatus" in html, "MCP"),
        ("skills", "Skill discovery/evolution", "discoverSkills" in html and "evolutionCandidateList" in html, "Skills"),
        ("remote", "Remote control surface", "/api/console/remote/status" in routes or "Remote Control" in html, "Remote"),
        ("local_models", "Local model inventory", "/api/console/local-models/inventory" in routes or "localModelCards" in html, "Local Models"),
        ("saas", "Public SaaS foundation", (ROOT / "ghostchimera" / "saas").is_dir(), "SaaS"),
        ("voice_conversation", "Voice/conversation hooks", "conversationVoiceSelect" in html, "Conversation"),
        ("capability_pack", "Native capability pack", "/api/console/capability-pack" in routes or "capabilityPackList" in html, "Capability Pack"),
    ]
    return _dimension("platform_breadth", "Platform Breadth", checks, weight=0.3)


def _autonomy_depth_dimension(summary: dict[str, Any], routes: set[str], html: str, app: str) -> SuperiorityDimension:
    trust_ready = bool((summary.get("trust") or {}).get("ready"))
    checks = [
        ("durable_trust", "Durable Trust Runtime", trust_ready or "/api/console/trust/runs" in routes, "Trust Runtime"),
        ("approval_queue", "Resumable approval queue", "/api/console/trust/approvals" in routes or "trustApprovals" in html, "Approvals"),
        ("autonomy_jobs", "Autonomy jobs and schedules", "/api/console/autonomy/jobs" in routes and "/api/console/autonomy/schedules" in routes, "Autonomy"),
        ("sandbox", "Sandbox journey", "/api/console/sandbox/journey" in routes or "sandboxSteps" in html, "Sandbox"),
        ("self_evolution", "Consent-gated self-evolution", "/api/console/evolution/candidates" in routes or "evolutionCandidateList" in html, "Self-Evolution"),
        ("remote_execution_gates", "Remote execution gates", "/api/console/remote/approvals/" in routes or "remoteApprovals" in html, "Remote"),
        ("full_bypass_visible", "Visible bypass controls", "conversationFullBypass" in html and "conversationBypassBanner" in html, "Conversation"),
        ("trace_export", "Trace export", "/api/console/trust/traces/" in routes or "trustTrace" in app, "Trace"),
        ("eval_baseline", "Trust/eval baseline", "/api/console/trust/evals" in routes or "trustEvals" in html, "Evals"),
        ("stop_all", "Emergency stop", "conversationStopAll" in html, "Safety"),
    ]
    return _dimension("autonomy_depth", "Autonomy Depth", checks, weight=0.3)


def _dimension(
    id_: str,
    label: str,
    checks: list[tuple[str, str, bool, str]],
    *,
    weight: float,
) -> SuperiorityDimension:
    evidence = [
        ScorecardEvidence(
            id=check_id,
            label=check_label,
            status="present" if present else "missing",
            surface=surface,
            detail="verified locally" if present else "not found in current surfaces",
        )
        for check_id, check_label, present, surface in checks
    ]
    missing = [check_label for _, check_label, present, _ in checks if not present]
    score = (len(checks) - len(missing)) / len(checks) if checks else 0.0
    blockers = missing[:3] if score < 0.7 else []
    warnings = missing[:5] if missing and not blockers else []
    return SuperiorityDimension(id=id_, label=label, score=score, weight=weight, evidence=evidence, blockers=blockers, warnings=warnings)


def _next_best_actions(summary: dict[str, Any], dimensions: list[SuperiorityDimension]) -> list[NextBestAction]:
    actions: list[NextBestAction] = []
    model = summary.get("model") if isinstance(summary.get("model"), dict) else {}
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}

    if not model.get("provider"):
        actions.append(NextBestAction("connect_model", "Connect or select a model provider", "config", 100, "No active provider is configured."))
    if counts.get("approved_sources", 0) == 0:
        actions.append(NextBestAction("approve_learning_source", "Approve a learning source", "evolution", 90, "Self-Evolution needs an approved source before recommendations matter."))
    if (summary.get("trust") or {}).get("ready") is not True:
        actions.append(NextBestAction("create_trust_baseline", "Create a trust baseline", "trust", 80, "Production readiness depends on fresh Trust Runtime evidence.", "ghostchimera trust eval baseline"))
    if summary.get("warnings"):
        actions.append(NextBestAction("resolve_readiness", "Resolve readiness warnings", "operator", 70, str(summary.get("warnings", ["Review warnings"])[0])))

    for dimension in dimensions:
        if dimension.score < 1.0:
            actions.append(
                NextBestAction(
                    f"improve_{dimension.id}",
                    f"Improve {dimension.label}",
                    "operator",
                    60 - int(dimension.score * 10),
                    (dimension.warnings or dimension.blockers or ["Close scorecard gaps."])[0],
                )
            )

    if not actions:
        actions.append(
            NextBestAction(
                "run_sandbox_workflow",
                "Run a sandbox workflow and review trace evidence",
                "sandbox",
                50,
                "The system is ready for an operator proof run.",
                "ghostchimera sandbox journey",
            )
        )
    return sorted(actions, key=lambda item: item.priority, reverse=True)[:8]


def _journey_cases(html: str, app: str, routes: set[str], artifacts: dict[str, Any]) -> list[OperatorJourneyCase]:
    checks = [
        ("load_workbench", "Load Operator Workbench", "operatorWorkbench" in html, "static/index.html"),
        ("search_action", "Use command search", "operatorCommandSearch" in html, "static/index.html"),
        ("open_scorecard", "Render superiority scorecard", "renderSuperiorityScorecard" in app, "static/app.js"),
        (
            "call_api",
            "Call scorecard API",
            "/api/console/superiority" in routes or "/api/console/superiority" in app,
            "Console API",
        ),
        ("walk_trust", "Reach trust evidence", "trust" in html, "Trust Runtime"),
        (
            "capture_artifact",
            "Capture browser proof artifact",
            bool(artifacts.get("artifact_path")) or "browserE2EStatus" in html,
            "E2E artifact",
        ),
    ]
    return [
        OperatorJourneyCase(check_id, label, surface, "passed" if ok else "missing")
        for check_id, label, ok, surface in checks
    ]


def _read_text(relative_path: str) -> str:
    path = ROOT / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _grade(score: float) -> str:
    if score >= 0.95:
        return "A"
    if score >= 0.85:
        return "B"
    if score >= 0.7:
        return "C"
    return "review"


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lower = str(key).lower()
            if lower in {"secret_policy", "secrets_are_write_only", "raw_secret_values_returned"}:
                redacted[key] = _redact_value(item)
            elif any(part in lower for part in SECRET_KEY_PARTS):
                redacted[key] = "[REDACTED]" if item else ""
            else:
                redacted[key] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        cleaned = TOKEN_LIKE.sub("[REDACTED]", value)
        cleaned = WINDOWS_PRIVATE_PATH.sub("[REDACTED_PATH]", cleaned)
        return cleaned
    return value


def contains_secret_like_text(value: Any) -> bool:
    """Return True when text appears to include raw secrets or private paths."""

    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    return bool(TOKEN_LIKE.search(text) or WINDOWS_PRIVATE_PATH.search(text))


def dumps_scorecard(scorecard: SuperiorityScorecard) -> str:
    """Serialize a scorecard with stable key order."""

    return json.dumps(scorecard.to_dict(), indent=2, sort_keys=True)


__all__ = [
    "NextBestAction",
    "OperatorJourneyCase",
    "ScorecardEvidence",
    "SuperiorityDimension",
    "SuperiorityScorecard",
    "build_superiority_scorecard",
    "build_local_operator_summary",
    "contains_secret_like_text",
    "dumps_scorecard",
    "format_superiority_markdown",
]
