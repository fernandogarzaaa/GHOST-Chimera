"""Browser-based Ghost Chimera control console."""

from __future__ import annotations

import contextlib
import hashlib
import html
import importlib.util
import json
import os
import re
import sys
import textwrap
import time
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..capability_admission import CapabilityAdmissionStore
from ..capability_pack import call_capability_tool, list_capability_tools
from ..chimera_pilot import ChimeraPilotKernel
from ..chimera_pilot.autonomy import get_autonomy_profile, list_autonomy_profiles
from ..chimera_pilot.autonomy_jobs import JOB_SPECS
from ..chimera_pilot.autonomy_queue import AutonomyJobQueue
from ..chimera_pilot.capability_intelligence import inspect_capabilities
from ..chimera_pilot.context_compressor import compress_text_query_aware
from ..chimera_pilot.desktop_policy import DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN
from ..chimera_pilot.gateway_server import GatewayServer, HttpResponse
from ..chimera_pilot.pr_review import run_pr_review
from ..cognition_layer.trust import GhostBelief, guard_belief, summarize_operational_trace
from ..cognition_layer.workspace_state import OperatorWorkspaceStore
from ..config import GhostChimeraConfig
from ..integrations.email_oauth import (
    crawl_email_provider,
    email_oauth_status,
    finish_gmail_browser_oauth,
    poll_email_oauth,
    start_email_oauth,
    start_gmail_browser_oauth,
)
from ..integrations.remote_control import RemoteControlStore, normalize_remote_payload, verify_remote_webhook_signature
from ..memory_layer.store import MemoryStore
from ..model_layer.auth_profiles import AuthProfile
from ..model_layer.codex_cli_provider import codex_login_command, get_codex_cli_status, launch_codex_login_flow
from ..model_layer.local_model_inventory import discover_local_model_inventory, resolve_model_source
from ..model_layer.minimind_lifecycle import MiniMindLifecycle
from ..model_layer.minimind_personal_agent import MiniMindPersonalAgent
from ..model_layer.model_discovery import get_model_discovery, refresh_model_discovery, select_discovered_model
from ..model_layer.provider_auth import (
    get_provider_auth_spec,
    list_provider_options,
    provider_auth_setup_url,
    provider_auth_summary,
    provider_env_keys,
)
from ..model_layer.provider_oauth_connectors import (
    exchange_openrouter_code,
    poll_huggingface_device_flow,
    start_google_adc_flow,
    start_huggingface_device_flow,
    start_openrouter_pkce,
)
from ..model_layer.providers import get_provider
from ..sandbox.journey import run_sandbox_journey
from ..superiority import build_superiority_scorecard
from ..tool_layer.browser import http_get
from ..tool_layer.browser_workspace import AgentBrowserWorkspace
from ..trust_runtime import TrustRuntimeStore
from .config import CONFIG_FILE, config_to_env_vars, get_autonomy_config, get_default_config, load_config, save_config
from .conversation import ConversationalLoopController, ConversationStore
from .evolution import (
    create_learning_source,
    list_candidates,
    list_sources,
    read_timeline,
    readiness_summary,
    record_timeline_event,
    set_candidate_status,
    set_source_consent,
    upsert_candidate,
)
from .latency import latency_summary, record_latency_event

RunObjective = Callable[[str], dict[str, Any]]
FetchUrl = Callable[[str], str]


RELEASE_CHECKS: list[dict[str, str]] = [
    {
        "name": "ruff lint",
        "command": "python -m ruff check .",
        "purpose": "Checks import order and static Python lint rules.",
    },
    {
        "name": "pytest suite",
        "command": "python -m pytest -q",
        "purpose": "Runs the full source test suite.",
    },
    {
        "name": "release validator",
        "command": "python scripts/validate_release.py",
        "purpose": "Runs the repo release gate checks.",
    },
    {
        "name": "package build",
        "command": "python -m build",
        "purpose": "Builds source and wheel artifacts.",
    },
    {
        "name": "smoke eval",
        "command": "python -m ghostchimera.evals run --suite smoke",
        "purpose": "Runs the built-in smoke evaluation suite.",
    },
    {
        "name": "safety eval",
        "command": "python -m ghostchimera.evals run --suite safety",
        "purpose": "Runs the built-in safety evaluation suite.",
    },
    {
        "name": "autonomy eval",
        "command": "python -m ghostchimera.evals run --suite autonomy",
        "purpose": "Checks autonomy profile and job-runner contracts.",
    },
    {
        "name": "user journey eval",
        "command": "python -m ghostchimera.evals run --suite user-journey",
        "purpose": "Exercises first-run local operator CLI and console paths.",
    },
    {
        "name": "competitive capability eval",
        "command": "python -m ghostchimera.evals run --suite competitive",
        "purpose": "Checks Ghost Chimera against current agent-orchestration capability benchmarks.",
    },
    {
        "name": "public superiority eval",
        "command": "python -m ghostchimera.evals run --suite superiority",
        "purpose": "Measures operator UX, platform breadth, and autonomy-depth proof surfaces.",
    },
    {
        "name": "GitHub-connected eval",
        "command": "python -m ghostchimera.evals run --suite github-connected",
        "purpose": "Checks GitHub status, issue planning, and console route contracts.",
    },
    {
        "name": "path synthesis eval",
        "command": "python -m ghostchimera.evals run --suite path-synthesis",
        "purpose": "Checks multi-purpose role profiles, path synthesis, and external-source policy.",
    },
    {
        "name": "production doctor",
        "command": "GHOSTCHIMERA_DEPLOYMENT_MODE=production GHOSTCHIMERA_EXTERNAL_ISOLATION=container GHOSTCHIMERA_SECURITY_REVIEWED=1 GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1 ghostchimera doctor --production",
        "purpose": "Verifies production-mode guardrail configuration.",
    },
    {
        "name": "trust runtime status",
        "command": "ghostchimera trust status",
        "purpose": "Checks durable journals, approvals, MCP trust, trace health, and trust eval posture.",
    },
    {
        "name": "trust eval baseline",
        "command": "ghostchimera trust eval baseline",
        "purpose": "Creates a fresh local trust baseline before production deployment.",
    },
    {
        "name": "trust eval cases",
        "command": "ghostchimera trust eval-cases list",
        "purpose": "Lists promoted local trust regression cases for the eval flywheel.",
    },
    {
        "name": "capability admission",
        "command": "ghostchimera capability-admission list",
        "purpose": "Checks reviewed capability records before production activation.",
    },
    {
        "name": "base wheel smoke",
        "command": "python scripts/smoke_installed_wheel.py",
        "purpose": "Verifies the installed artifact without optional extras.",
    },
    {
        "name": "gateway wheel smoke",
        "command": "python scripts/smoke_installed_wheel.py --extras gateway",
        "purpose": "Verifies console and scheduler paths with gateway extras.",
    },
    {
        "name": "workspace state smoke",
        "command": "ghostchimera workspace show",
        "purpose": "Verifies the inspectable operator workspace CLI is reachable.",
    },
    {
        "name": "workspace memory sync smoke",
        "command": "ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30",
        "purpose": "Verifies high-confidence workspace evidence can feed local CWR memory with provenance.",
    },
    {
        "name": "competitive capability smoke",
        "command": "ghostchimera capabilities --format json",
        "purpose": "Verifies the competitive capability matrix is reachable from the CLI.",
    },
    {
        "name": "public superiority smoke",
        "command": "ghostchimera superiority score --format json",
        "purpose": "Verifies the bounded public superiority scorecard is reachable from the CLI.",
    },
    {
        "name": "native capability pack smoke",
        "command": "ghostchimera capability-pack list",
        "purpose": "Verifies built-in Chimera capability tools are reachable without external MCP servers.",
    },
    {
        "name": "local model inventory smoke",
        "command": "ghostchimera local-model inventory",
        "purpose": "Verifies local model inventory remains preview-only and self-contained.",
    },
    {
        "name": "cognition guard smoke",
        "command": "ghostchimera cognition guard --confidence 0.9 --variance 0.01",
        "purpose": "Verifies the confidence and variance guard CLI surface.",
    },
    {
        "name": "sandbox journey smoke",
        "command": "ghostchimera sandbox journey",
        "purpose": "Verifies the operator sandbox journey report is reachable.",
    },
    {
        "name": "remote control smoke",
        "command": "ghostchimera remote status",
        "purpose": "Verifies Ghost-native mobile/messaging remote control is reachable without external gateways.",
    },
    {
        "name": "GitHub connection smoke",
        "command": "ghostchimera github status",
        "purpose": "Verifies GitHub-connected workflow auth detection is reachable from the CLI.",
    },
    {
        "name": "PR review smoke",
        "command": "ghostchimera review-pr --base HEAD --head HEAD",
        "purpose": "Verifies first-party PR/diff review automation is reachable from the CLI.",
    },
]


CONSOLE_HTML = "<!-- Ghost Console -- served by static/index.html -->"

PROVIDER_OPTIONS: list[dict[str, Any]] = list_provider_options()

_MODEL_ENV_KEYS = provider_env_keys()
_EMAIL_OAUTH_ENV_KEYS = {
    "GMAIL_OAUTH_CLIENT_ID",
    "GMAIL_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "OUTLOOK_OAUTH_CLIENT_ID",
    "MS_GRAPH_CLIENT_ID",
    "OUTLOOK_TENANT_ID",
    "MICROSOFT_TENANT_ID",
}
_GITHUB_OAUTH_ENV_KEYS = {"GHOSTCHIMERA_GITHUB_CLIENT_ID", "GITHUB_CLIENT_ID"}
_CONFIG_ENV_KEYS = _MODEL_ENV_KEYS | _EMAIL_OAUTH_ENV_KEYS | _GITHUB_OAUTH_ENV_KEYS


def _redact_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "[configured]"
    return f"{value[:2]}...{value[-2:]}"


def _is_secret_env_key(key: str) -> bool:
    marker = key.upper()
    return any(part in marker for part in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))


def _option_ids() -> set[str]:
    return {str(option["id"]) for option in PROVIDER_OPTIONS}


def _config_file_for_console(config_path: str | Path | None = None) -> Path:
    return Path(config_path).expanduser() if config_path else CONFIG_FILE


def _load_console_config(config_file: Path) -> dict[str, Any]:
    config = load_config(config_file)
    if not config:
        config = get_default_config()
    config.setdefault("model", {})
    config.setdefault("gateway", get_default_config()["gateway"])
    config.setdefault("safety", get_default_config()["safety"])
    config.setdefault("autonomy", get_default_config()["autonomy"])
    return config


def _write_env_file(config_file: Path, env_vars: dict[str, str]) -> Path:
    env_file = config_file.parent / ".env"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in sorted(env_vars.items()) if value]
    env_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return env_file


def _apply_model_env(env_vars: dict[str, str], *, overwrite: bool) -> None:
    if overwrite:
        for key in _CONFIG_ENV_KEYS:
            os.environ.pop(key, None)
    for key, value in env_vars.items():
        if value and (overwrite or not os.environ.get(key)):
            os.environ[key] = value


def _apply_saved_config_env(config_path: str | Path | None = None, *, overwrite: bool = False) -> None:
    config_file = _config_file_for_console(config_path)
    config = load_config(config_file)
    if not config:
        return
    _apply_model_env(config_to_env_vars(config), overwrite=overwrite)


def _safe_config_payload(config: dict[str, Any], config_file: Path) -> dict[str, Any]:
    model = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    email_oauth = config.get("email_oauth", {}) if isinstance(config.get("email_oauth"), dict) else {}
    github_oauth = config.get("github_oauth", {}) if isinstance(config.get("github_oauth"), dict) else {}
    env_vars = config_to_env_vars(config)
    provider = str(model.get("provider") or os.environ.get("GHOSTCHIMERA_MODEL_PROVIDER") or "").strip()
    runtime = GhostChimeraConfig.from_env().to_dict()
    return {
        "ok": True,
        "config_path": str(config_file),
        "env_file": str(config_file.parent / ".env"),
        "provider_options": PROVIDER_OPTIONS,
        "model": {
            "provider": provider,
            "model": str(model.get("model") or ""),
            "base_url": str(model.get("base_url") or ""),
            "api_key_configured": bool(model.get("api_key")),
            "oauth_token_configured": bool(model.get("oauth_token")),
            "api_key_preview": _redact_secret(str(model.get("api_key") or "")),
        },
        "env_preview": {
            key: (_redact_secret(value) if _is_secret_env_key(key) else value)
            for key, value in sorted(env_vars.items())
            if value
        },
        "provider_auth": provider_auth_summary(config),
        "email_oauth": {
            "gmail_client_id_configured": bool(email_oauth.get("gmail_client_id"))
            or bool(os.environ.get("GMAIL_OAUTH_CLIENT_ID") or os.environ.get("GOOGLE_OAUTH_CLIENT_ID")),
            "gmail_client_secret_configured": bool(email_oauth.get("gmail_client_secret"))
            or bool(os.environ.get("GMAIL_OAUTH_CLIENT_SECRET") or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")),
            "outlook_client_id_configured": bool(email_oauth.get("outlook_client_id"))
            or bool(os.environ.get("OUTLOOK_OAUTH_CLIENT_ID") or os.environ.get("MS_GRAPH_CLIENT_ID")),
            "microsoft_tenant_id_configured": bool(email_oauth.get("microsoft_tenant_id"))
            or bool(os.environ.get("MICROSOFT_TENANT_ID") or os.environ.get("OUTLOOK_TENANT_ID")),
            "gmail_client_id_preview": _redact_secret(str(email_oauth.get("gmail_client_id") or "")),
            "gmail_client_secret_preview": _redact_secret(str(email_oauth.get("gmail_client_secret") or "")),
            "outlook_client_id_preview": _redact_secret(str(email_oauth.get("outlook_client_id") or "")),
            "microsoft_tenant_id_preview": _redact_secret(str(email_oauth.get("microsoft_tenant_id") or "")),
            "read_only_scopes": True,
            "tokens_are_write_only": True,
        },
        "github_oauth": {
            "client_id_configured": bool(github_oauth.get("client_id"))
            or bool(os.environ.get("GHOSTCHIMERA_GITHUB_CLIENT_ID") or os.environ.get("GITHUB_CLIENT_ID")),
            "client_id_preview": _redact_secret(str(github_oauth.get("client_id") or "")),
            "device_flow_enabled": bool(github_oauth.get("client_id"))
            or bool(os.environ.get("GHOSTCHIMERA_GITHUB_CLIENT_ID") or os.environ.get("GITHUB_CLIENT_ID")),
            "tokens_are_write_only": True,
        },
        "runtime": runtime,
        "modules": [
            {"id": "path", "label": "Ghost Paths", "tab": "path", "enabled": True},
            {"id": "github", "label": "GitHub", "tab": "github", "enabled": True},
            {"id": "remote", "label": "Remote Control", "tab": "remote", "enabled": True},
            {"id": "operator", "label": "Operator Home", "tab": "operator", "enabled": True},
            {"id": "thinking", "label": "Thinking", "tab": "thinking", "enabled": True},
            {"id": "evolution", "label": "Self-Evolution", "tab": "evolution", "enabled": True},
            {"id": "memory", "label": "Memory", "tab": "memory", "enabled": True},
            {"id": "minimind", "label": "MiniMind", "tab": "minimind", "enabled": True},
            {"id": "jobs", "label": "Autonomy Jobs", "tab": "jobs", "enabled": True},
            {"id": "schedules", "label": "Schedules", "tab": "schedules", "enabled": True},
            {"id": "security", "label": "Security", "tab": "security", "enabled": True},
            {"id": "browser", "label": "Browser", "tab": "browser", "enabled": True},
        ],
        "restart_required": False,
        "security": {
            "secrets_are_write_only": True,
            "raw_secret_values_returned": False,
            "storage": "local Ghost Chimera config directory",
        },
    }


def _json_body(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Parse and return the JSON object from a request-like context's body.

    Parameters:
        ctx (dict[str, Any]): Request context containing a "body" key whose value is the raw request payload.

    Returns:
        dict[str, Any]: The parsed JSON object, or an empty dict if the body is absent or blank.

    Raises:
        ValueError: If the parsed JSON is not a JSON object (i.e., not a dict).
        json.JSONDecodeError: If the body contains invalid JSON.
    """
    raw = str(ctx.get("body") or "").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _suffix(ctx: dict[str, Any], prefix: str) -> str:
    return str(ctx.get("path") or "")[len(prefix) :].strip("/")


def _default_run_objective(objective: str) -> dict[str, Any]:
    autonomy = get_autonomy_config(load_config())
    true_autonomy_desktop = _as_bool(autonomy.get("true_autonomy_desktop"), default=False)
    enable_personal_context = _as_bool(autonomy.get("personal_context"), default=True)
    try:
        desktop_max_live_actions = int(autonomy.get("desktop_max_live_actions") or 25)
    except (TypeError, ValueError):
        desktop_max_live_actions = 25
    try:
        desktop_max_session_seconds = float(autonomy.get("desktop_max_session_seconds") or 300.0)
    except (TypeError, ValueError):
        desktop_max_session_seconds = 300.0
    runtime = GhostChimeraConfig.from_env()
    memory_store = MemoryStore(runtime.memory_db)
    if true_autonomy_desktop:
        kernel = ChimeraPilotKernel.default(
            include_deterministic_backend=True,
            allow_network=True,
            allow_python_execution=True,
            allow_desktop_control=True,
            enable_desktop_backend=True,
            enable_live_desktop=True,
            ghost_mode="possess",
            desktop_action_classes=("read_only", "mutating", "destructive"),
            desktop_confirmation_token=DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN,
            desktop_max_live_actions=desktop_max_live_actions,
            desktop_max_session_seconds=desktop_max_session_seconds,
            autonomy_level=str(autonomy.get("level") or "supervised"),
            memory_store=memory_store,
            enable_personal_context=enable_personal_context,
        )
    else:
        kernel = ChimeraPilotKernel.default(
            include_deterministic_backend=True,
            autonomy_level=str(autonomy.get("level") or "supervised"),
            memory_store=memory_store,
            enable_personal_context=enable_personal_context,
        )
    executions = kernel.run(objective)
    payload = [execution.to_dict() for execution in executions]
    return {"ok": all(item.get("ok") for item in payload), "executions": payload}


def _status_payload(server: GatewayServer) -> dict[str, Any]:
    config = load_config()
    autonomy = get_autonomy_config(config)
    profile = get_autonomy_profile(str(autonomy.get("level") or "supervised"))
    if "personal_context" not in autonomy:
        autonomy["personal_context"] = True
    return {
        "ok": True,
        "timestamp": time.time(),
        "gateway": server.status(),
        "runtime": GhostChimeraConfig.from_env().to_dict(),
        "autonomy": {
            "config": autonomy,
            "resolved_profile": profile.to_dict(),
        },
        "profiles": [profile.to_dict() for profile in list_autonomy_profiles()],
    }


def _scheduled_executor(queue: AutonomyJobQueue):
    from ..chimera_pilot.cron_scheduler import CronJob, CronJobResult

    def execute(job: CronJob) -> CronJobResult:
        job_name = str(job.metadata.get("autonomy_job") or "").strip()
        profile = str(job.metadata.get("profile") or "supervised")
        run_execute = _as_bool(job.metadata.get("execute"), default=False)
        if not job_name:
            return CronJobResult(
                job_id=job.id,
                job_name=job.name,
                objective=job.objective,
                success=False,
                error="Scheduled console job is missing autonomy_job metadata.",
            )
        try:
            record = queue.enqueue(
                job_name,
                profile=profile,
                execute=run_execute,
                source="schedule",
                schedule_id=job.id,
            )
        except Exception as exc:
            return CronJobResult(
                job_id=job.id,
                job_name=job.name,
                objective=job.objective,
                success=False,
                error=str(exc),
            )
        return CronJobResult(
            job_id=job.id,
            job_name=job.name,
            objective=job.objective,
            success=record.get("status") not in {"error", "cancelled"},
            output=json.dumps(record, sort_keys=True)[:3000],
            error=record.get("error"),
        )

    return execute


def _security_events_handler(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return recent security / DPI events from the SecurityMonitor."""
    try:
        from ..safety_layer.security_monitor import get_monitor
    except ImportError:
        return {"ok": False, "error": "Security monitor unavailable"}
    query = ctx.get("query") or {}
    limit = int(query.get("limit") or 100)
    blocked_only = str(query.get("blocked_only") or "").lower() in {"1", "true"}
    min_risk = float(query.get("min_risk") or 0.0)
    category = query.get("category")
    session_id = query.get("session_id")
    events = get_monitor().get_events(
        limit=limit,
        blocked_only=blocked_only,
        min_risk=min_risk,
        threat_category=category or None,
        session_id=session_id or None,
    )
    return {"ok": True, "events": events, "count": len(events)}


def _security_summary_handler(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return aggregated threat statistics and risk timeline."""
    try:
        from ..safety_layer.security_monitor import get_monitor
    except ImportError:
        return {"ok": False, "error": "Security monitor unavailable"}
    monitor = get_monitor()
    bucket_minutes = int((ctx.get("query") or {}).get("bucket_minutes") or 5)
    return {
        "ok": True,
        "summary": monitor.get_threat_summary(),
        "risk_timeline": monitor.get_risk_timeline(bucket_minutes=bucket_minutes),
    }


def _security_audit_handler(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return audit log entries and verify chain integrity."""
    try:
        from ..safety_layer.audit import AuditLog
    except ImportError:
        return {"ok": False, "error": "Audit module unavailable"}
    audit = AuditLog()
    ok, msg = audit.verify_integrity()
    entries = audit.get_entries()
    return {
        "ok": True,
        "chain_integrity": ok,
        "integrity_message": msg,
        "entry_count": len(entries),
        "entries": entries[-100:],
    }


def register_console_routes(
    server: GatewayServer,
    *,
    run_objective: RunObjective | None = None,
    fetch_url: FetchUrl | None = None,
    browser_workspace: AgentBrowserWorkspace | None = None,
    state_dir: str | Path | None = None,
    autonomy_queue: AutonomyJobQueue | None = None,
    cron_scheduler: Any | None = None,
    operator_workspace: OperatorWorkspaceStore | None = None,
    console_token: str = "",
    config_path: str | Path | None = None,
) -> None:
    """Register browser console routes on an existing GatewayServer."""

    objective_runner = run_objective or _default_run_objective
    url_fetcher = fetch_url or http_get
    workspace = browser_workspace or AgentBrowserWorkspace()
    queue = autonomy_queue or AutonomyJobQueue(state_dir=state_dir or server.config.state_dir)
    workspace_store = operator_workspace or OperatorWorkspaceStore(state_dir=state_dir or server.config.state_dir)
    console_state_dir = Path(state_dir or server.config.state_dir)
    remote_store = RemoteControlStore(console_state_dir)
    trust_store = TrustRuntimeStore(console_state_dir)
    admission_store = CapabilityAdmissionStore(console_state_dir)
    conversation_store = ConversationStore(console_state_dir)
    conversation_controller = ConversationalLoopController(
        state_dir=console_state_dir,
        store=conversation_store,
        trust_store=trust_store,
        objective_runner=objective_runner,
        timeline_recorder=lambda event_type, detail: record_timeline_event(console_state_dir, event_type, detail),
    )
    path_config_file = Path(config_path).expanduser() if config_path else None
    console_config_file = _config_file_for_console(config_path)
    scheduler = cron_scheduler
    scheduler_error = ""
    if scheduler is None:
        try:
            from ..chimera_pilot.cron_scheduler import CronScheduler

            scheduler = CronScheduler(
                state_dir=state_dir or server.config.state_dir, job_executor=_scheduled_executor(queue)
            )
        except Exception as exc:  # pragma: no cover - depends on optional croniter availability
            scheduler_error = str(exc)

    # Auth settings for API routes: use token auth when a console token is configured.
    _api_auth = "token" if console_token else "open"
    _api_token = console_token

    def _api_register(
        path: str, handler: Any, *, method: str = "GET", prefix: bool = False, description: str = ""
    ) -> None:
        """Register an API route with the appropriate auth mode."""
        def timed_handler(ctx: dict[str, Any]) -> Any:
            started = time.perf_counter()
            ok = False
            error = ""
            try:
                result = handler(ctx)
                ok = not (isinstance(result, dict) and result.get("ok") is False)
                return result
            except Exception as exc:
                error = exc.__class__.__name__
                raise
            finally:
                record_latency_event(
                    console_state_dir,
                    route=path,
                    method=method,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    ok=ok,
                    error=error,
                )

        server.routes.register(
            path,
            timed_handler,
            method=method,
            auth=_api_auth,
            token=_api_token,
            prefix=prefix,
            description=description,
        )

    def _github_console_auth_path() -> Path:
        return console_state_dir / "github_console_auth.json"

    def _read_github_console_auth() -> dict[str, Any]:
        path = _github_console_auth_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_github_console_auth(payload: dict[str, Any]) -> None:
        console_state_dir.mkdir(parents=True, exist_ok=True)
        _github_console_auth_path().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _delete_github_console_auth() -> None:
        with contextlib.suppress(FileNotFoundError):
            _github_console_auth_path().unlink()

    def _github_client_with_console_token():
        from ..integrations.github_client import GitHubAuth, GitHubClient

        stored = _read_github_console_auth()
        token = str(stored.get("token") or "").strip()
        if token:
            return GitHubClient(auth=GitHubAuth(mode="token", token=token))
        return GitHubClient(auth=GitHubAuth.discover())

    def _workspace_skills_dir() -> Path:
        root = os.environ.get("GHOSTCHIMERA_SKILLS_DIR") or str(Path.home() / ".ghostchimera" / "skills")
        return Path(root).expanduser().resolve()

    def _skill_slug(name: str) -> str:
        slug = re.sub(r"[^a-z0-9_]+", "_", name.lower())
        slug = re.sub(r"_+", "_", slug).strip("_")
        if slug:
            return slug
        return f"github_skill_{hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]}"

    def _skill_class_name(slug: str) -> str:
        parts = [part for part in slug.split("_") if part]
        label = "".join(part.capitalize() for part in parts)
        return f"{label}Skill" if label else "GithubSkill"

    def _write_compat_skill(candidate: dict[str, Any]) -> dict[str, Any]:
        repo = str(candidate.get("full_name") or "").strip()
        if not repo:
            raise ValueError("Missing repository full_name")
        slug = _skill_slug(repo.replace("/", "_"))
        class_name = _skill_class_name(slug)
        repo_literal = json.dumps(repo)
        url_literal = json.dumps(str(candidate.get("html_url") or "").strip())
        slug_literal = json.dumps(slug)
        compat_action_literal = json.dumps(f"github_compat_{slug}")
        description_literal = json.dumps(f"GitHub compatibility skill generated from {repo}.")
        skill_dir = _workspace_skills_dir() / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "skill.py"
        skill_path.write_text(
            textwrap.dedent(
                f"""\
                from __future__ import annotations

                from typing import Any

                from ghostchimera.skill_layer.base import Skill


                class {class_name}(Skill):
                    name = {slug_literal}
                    description = {description_literal}
                    actions = [{slug_literal}, {compat_action_literal}]
                    domain = "github-compatible"

                    def run(self, task: dict[str, Any]) -> Any:
                        query = str(task.get("query") or task.get("input") or "").strip()
                        return {{
                            "ok": True,
                            "skill": self.name,
                            "source_repo": {repo_literal},
                            "source_url": {url_literal},
                            "message": "Compatibility skill scaffold generated from GitHub metadata.",
                            "query": query,
                        }}
                """
            ),
            encoding="utf-8",
        )
        return {"repo": repo, "skill_name": slug, "path": str(skill_path)}

    def _move_admission_to_review(record: dict[str, Any], *, reason: str) -> dict[str, Any]:
        current = str(record.get("status") or "discovered")
        record_id = str(record.get("id") or "")
        if current == "discovered":
            moved = admission_store.transition(record_id, "inspected", reviewer="console", reason=reason)
            if moved.get("ok"):
                record = moved["record"]
                current = str(record.get("status") or "inspected")
        if current == "inspected":
            moved = admission_store.transition(record_id, "review_required", reviewer="console", reason=reason)
            if moved.get("ok"):
                record = moved["record"]
        return record

    def _move_admission_to_active(record: dict[str, Any], *, reason: str) -> dict[str, Any]:
        current = str(record.get("status") or "discovered")
        record_id = str(record.get("id") or "")
        if current in {"revoked", "quarantined"}:
            return record
        record = _move_admission_to_review(record, reason=reason)
        current = str(record.get("status") or "")
        if current == "review_required":
            moved = admission_store.transition(record_id, "approved", reviewer="console", reason=reason)
            if moved.get("ok"):
                record = moved["record"]
                current = str(record.get("status") or "")
        if current == "approved":
            moved = admission_store.transition(record_id, "active", reviewer="console", reason=reason)
            if moved.get("ok"):
                record = moved["record"]
        return record

    def _admission_gate(
        *,
        capability_kind: str,
        name: str,
        source: str,
        risk_level: str = "medium",
        risk_ceiling: str = "medium",
        requested_permissions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inspection: dict[str, Any] | None = None,
        reason: str,
    ) -> dict[str, Any]:
        payload = admission_store.register_or_update(
            capability_kind=capability_kind,
            name=name,
            source=source,
            risk_level=risk_level,
            risk_ceiling=risk_ceiling,
            requested_permissions=requested_permissions,
            metadata=metadata,
            inspection=inspection,
        )
        if not payload.get("ok"):
            return payload
        record = payload.get("record") or {}
        status_value = str(record.get("status") or "discovered")
        if status_value == "active":
            return {"ok": True, "record": record}
        if status_value in {"revoked", "quarantined"}:
            return {
                "ok": False,
                "admission_required": True,
                "error": f"Capability admission record is {status_value}.",
                "record": record,
            }
        record = _move_admission_to_review(record, reason=reason)
        return {
            "ok": False,
            "admission_required": True,
            "error": "Capability Admission approval and activation are required before this can be used.",
            "record": record,
        }

    def _find_evolution_candidate(candidate_id: str) -> dict[str, Any] | None:
        for item in list_candidates(console_state_dir):
            if str(item.get("id") or "") == candidate_id:
                return item
        return None

    def console_page(ctx: dict[str, Any]) -> HttpResponse:
        query = ctx.get("query") or {}
        state = str(query.get("state") or "").strip()
        code = str(query.get("code") or "").strip()
        provider_error = str(query.get("error") or "").strip()
        provider_error_description = str(query.get("error_description") or "").strip()
        if state and (code or provider_error):
            if provider_error:
                safe_error = html.escape(provider_error_description or provider_error)
                return HttpResponse(
                    body=(
                        "<html><body><h1>Gmail connection failed</h1>"
                        f"<p>{safe_error}</p><p>You can close this tab and return to Ghost Console.</p>"
                        "</body></html>"
                    ),
                    status=400,
                    content_type="text/html",
                )
            result = finish_gmail_browser_oauth(server.config.state_dir, state, code)
            if result.get("ok"):
                return HttpResponse(
                    body=(
                        "<html><body><h1>Gmail connected</h1>"
                        "<p>Read-only Gmail OAuth is connected. You can close this tab and return to Ghost Console.</p>"
                        "</body></html>"
                    ),
                    content_type="text/html",
                )
            safe_error = html.escape(str(result.get("error") or "OAuth callback failed."))
            return HttpResponse(
                body=(
                    "<html><body><h1>Gmail connection failed</h1>"
                    f"<p>{safe_error}</p><p>You can close this tab and return to Ghost Console.</p>"
                    "</body></html>"
                ),
                status=400,
                content_type="text/html",
            )
        return HttpResponse(body=CONSOLE_HTML, content_type="text/html; charset=utf-8")

    def status(ctx: dict[str, Any]) -> dict[str, Any]:
        payload = _status_payload(server)
        payload["browser_workspace"] = workspace.status()
        return payload

    def dashboard_config(ctx: dict[str, Any]) -> dict[str, Any]:
        config = _load_console_config(console_config_file)
        if ctx.get("method") == "GET":
            return _safe_config_payload(config, console_config_file)

        body = _json_body(ctx)
        model = config.setdefault("model", {})
        provider = str(body.get("provider") or model.get("provider") or "").strip().lower()
        if provider not in _option_ids():
            return {"ok": False, "error": "Choose a supported provider."}
        model_name = str(body.get("model") or "").strip()
        base_url = str(body.get("base_url") or "").strip()
        api_key = str(body.get("api_key") or "").strip()
        clear_api_key = _as_bool(body.get("clear_api_key"), default=False)
        gmail_client_id = str(body.get("gmail_client_id") or "").strip()
        gmail_client_secret = str(body.get("gmail_client_secret") or "").strip()
        outlook_client_id = str(body.get("outlook_client_id") or "").strip()
        microsoft_tenant_id = str(body.get("microsoft_tenant_id") or "").strip()
        github_client_id = str(body.get("github_client_id") or "").strip()
        clear_gmail_client_id = _as_bool(body.get("clear_gmail_client_id"), default=False)
        clear_gmail_client_secret = _as_bool(body.get("clear_gmail_client_secret"), default=False)
        clear_outlook_client_id = _as_bool(body.get("clear_outlook_client_id"), default=False)
        clear_microsoft_tenant_id = _as_bool(body.get("clear_microsoft_tenant_id"), default=False)
        clear_github_client_id = _as_bool(body.get("clear_github_client_id"), default=False)

        if base_url and not (base_url.startswith("https://") or base_url.startswith("http://")):
            return {"ok": False, "error": "Base URL must start with http:// or https://."}
        if len(model_name) > 200:
            return {"ok": False, "error": "Model name is too long."}
        if len(base_url) > 500:
            return {"ok": False, "error": "Base URL is too long."}
        if len(api_key) > 2000:
            return {"ok": False, "error": "API key is too long."}
        for label, value in (
            ("Gmail OAuth client ID", gmail_client_id),
            ("Gmail OAuth client secret", gmail_client_secret),
            ("Outlook OAuth client ID", outlook_client_id),
            ("Microsoft tenant ID", microsoft_tenant_id),
            ("GitHub OAuth client ID", github_client_id),
        ):
            if len(value) > 500:
                return {"ok": False, "error": f"{label} is too long."}

        option = next(item for item in PROVIDER_OPTIONS if item["id"] == provider)
        model["provider"] = provider
        if model_name:
            model["model"] = model_name
        elif option.get("models") and option["models"][0]:
            model["model"] = option["models"][0]
        else:
            model["model"] = ""
        if base_url:
            model["base_url"] = base_url
        elif option.get("default_base_url"):
            model["base_url"] = str(option["default_base_url"])
        else:
            model.pop("base_url", None)
        if clear_api_key:
            model.pop("api_key", None)
        elif api_key:
            model["api_key"] = api_key

        config["model"] = model
        provider_auth = config.setdefault("provider_auth", {})
        if isinstance(provider_auth, dict):
            auth_record = provider_auth.setdefault(provider, {})
            if isinstance(auth_record, dict):
                auth_record["provider"] = provider
                auth_record["method"] = "api_key" if model.get("api_key") else "local"
                auth_record["model"] = model.get("model", "")
                auth_record["base_url"] = model.get("base_url", "")
                if clear_api_key:
                    auth_record.pop("api_key", None)
                elif api_key:
                    auth_record["api_key"] = api_key
        email_oauth = config.setdefault("email_oauth", {})
        if not isinstance(email_oauth, dict):
            email_oauth = {}
            config["email_oauth"] = email_oauth
        if clear_gmail_client_id:
            email_oauth.pop("gmail_client_id", None)
        elif gmail_client_id:
            email_oauth["gmail_client_id"] = gmail_client_id
        if clear_gmail_client_secret:
            email_oauth.pop("gmail_client_secret", None)
        elif gmail_client_secret:
            email_oauth["gmail_client_secret"] = gmail_client_secret
        if clear_outlook_client_id:
            email_oauth.pop("outlook_client_id", None)
        elif outlook_client_id:
            email_oauth["outlook_client_id"] = outlook_client_id
        if clear_microsoft_tenant_id:
            email_oauth.pop("microsoft_tenant_id", None)
        elif microsoft_tenant_id:
            email_oauth["microsoft_tenant_id"] = microsoft_tenant_id
        github_oauth = config.setdefault("github_oauth", {})
        if not isinstance(github_oauth, dict):
            github_oauth = {}
            config["github_oauth"] = github_oauth
        if clear_github_client_id:
            github_oauth.pop("client_id", None)
        elif github_client_id:
            github_oauth["client_id"] = github_client_id

        save_config(config, console_config_file)
        env_vars = config_to_env_vars(config)
        env_file = _write_env_file(console_config_file, env_vars)
        _apply_model_env(env_vars, overwrite=True)
        record_timeline_event(
            console_state_dir,
            "config_saved",
            {
                "provider": provider,
                "model": model.get("model", ""),
                "api_key_configured": bool(model.get("api_key")),
                "email_oauth_configured": {
                    "gmail": bool(email_oauth.get("gmail_client_id")),
                    "outlook": bool(email_oauth.get("outlook_client_id")),
                },
                "github_oauth_configured": bool(github_oauth.get("client_id")),
            },
        )
        payload = _safe_config_payload(config, console_config_file)
        payload.update({"saved": True, "env_file": str(env_file)})
        return payload

    def provider_auth_vault(ctx: dict[str, Any]) -> dict[str, Any]:
        config = _load_console_config(console_config_file)
        if ctx.get("method") == "GET":
            return provider_auth_summary(config)

        body = _json_body(ctx)
        provider = str(body.get("provider") or "").strip().lower()
        method = str(body.get("method") or "api_key").strip().lower()
        make_active = _as_bool(body.get("make_active"), default=False)
        clear_secret = _as_bool(body.get("clear_secret"), default=False)
        api_key = str(body.get("api_key") or "").strip()
        oauth_token = str(body.get("oauth_token") or "").strip()
        model_name = str(body.get("model") or "").strip()
        base_url = str(body.get("base_url") or "").strip()
        if provider not in _option_ids():
            return {"ok": False, "error": "Choose a supported provider."}
        spec = get_provider_auth_spec(provider)
        if not spec:
            return {"ok": False, "error": "Provider metadata is not available."}
        allowed_methods = {choice.get("method") for choice in spec.to_console_option().get("auth_methods", [])}
        if method not in allowed_methods:
            return {"ok": False, "error": "This auth method is not offered for the selected provider."}
        selected_choice = next((choice for choice in spec.auth_choices if choice.method == method), None)
        if make_active and selected_choice and not selected_choice.supports_runtime_activation:
            return {
                "ok": False,
                "error": "This OAuth method needs an ExternalAuthProvider connector before it can run models.",
            }
        codex_oauth = method == "oauth" and provider in {"openai", "codex_cli"}
        codex_status = get_codex_cli_status() if codex_oauth else None
        if make_active and codex_oauth and (not codex_status or not codex_status.logged_in):
            return {
                "ok": False,
                "error": f"Codex CLI is not logged in. Run: {codex_login_command()}",
                "login_command": codex_login_command(),
                "connector_status": codex_status.to_dict() if codex_status else {},
            }
        if len(api_key) > 2000 or len(oauth_token) > 4000:
            return {"ok": False, "error": "Credential is too long."}
        if len(model_name) > 300 or len(base_url) > 500:
            return {"ok": False, "error": "Model or base URL is too long."}
        if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
            return {"ok": False, "error": "Base URL must start with http:// or https://."}

        provider_auth = config.setdefault("provider_auth", {})
        if not isinstance(provider_auth, dict):
            provider_auth = {}
            config["provider_auth"] = provider_auth
        record = provider_auth.setdefault(provider, {})
        if not isinstance(record, dict):
            record = {}
            provider_auth[provider] = record
        record.update(
            {
                "provider": provider,
                "method": method,
                "model": model_name or record.get("model", ""),
                "base_url": base_url or record.get("base_url", ""),
                "updated_at": time.time(),
            }
        )
        if codex_oauth:
            record["oauth_connector"] = "codex_cli"
            record["connector_status"] = "connected" if codex_status and codex_status.logged_in else "needs_login"
            record["login_command"] = codex_login_command()
        if clear_secret:
            record.pop("api_key", None)
            record.pop("oauth_token", None)
        elif method == "api_key" and api_key:
            record["api_key"] = api_key
        elif method == "oauth" and oauth_token:
            record["oauth_token"] = oauth_token

        if make_active:
            active_provider = "codex_cli" if codex_oauth else provider
            active_spec = get_provider_auth_spec(active_provider) or spec
            model = config.setdefault("model", {})
            if not isinstance(model, dict):
                model = {}
                config["model"] = model
            model["provider"] = active_provider
            model["auth_method"] = method
            if codex_oauth:
                model["oauth_connector"] = "codex_cli"
            if model_name:
                model["model"] = model_name
            elif record.get("model"):
                model["model"] = record["model"]
            elif active_spec.models and active_spec.models[0]:
                model["model"] = active_spec.models[0]
            if base_url:
                model["base_url"] = base_url
            elif record.get("base_url"):
                model["base_url"] = record["base_url"]
            elif active_spec.default_base_url:
                model["base_url"] = active_spec.default_base_url
            if clear_secret:
                model.pop("api_key", None)
                model.pop("oauth_token", None)
            elif method == "api_key" and (api_key or record.get("api_key")):
                model["api_key"] = api_key or record["api_key"]
            elif method == "oauth" and (oauth_token or record.get("oauth_token")):
                model["oauth_token"] = oauth_token or record["oauth_token"]

        save_config(config, console_config_file)
        env_vars = config_to_env_vars(config)
        env_file = _write_env_file(console_config_file, env_vars)
        _apply_model_env(env_vars, overwrite=True)
        record_timeline_event(
            console_state_dir,
            "provider_auth_saved",
            {
                "provider": provider,
                "method": method,
                "make_active": make_active,
                "oauth_connector": "codex_cli" if codex_oauth else "",
                "secret_configured": bool(
                    api_key
                    or oauth_token
                    or record.get("api_key")
                    or record.get("oauth_token")
                    or record.get("oauth_connector")
                ),
            },
        )
        payload = _safe_config_payload(config, console_config_file)
        payload.update({"saved": True, "env_file": str(env_file), "provider_auth": provider_auth_summary(config)})
        return payload

    def provider_auth_connect(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        provider = str(body.get("provider") or "").strip().lower()
        method = str(body.get("method") or "oauth").strip().lower()
        launch = bool(body.get("launch"))
        spec = get_provider_auth_spec(provider)
        if not spec:
            return {"ok": False, "error": "Provider metadata is not available."}
        choice = next((item for item in spec.auth_choices if item.method == method), None)
        if not choice:
            return {"ok": False, "error": "This auth method is not offered for the selected provider."}
        if choice.method != "oauth":
            setup_url = provider_auth_setup_url(provider) or spec.docs_url
            return {
                "ok": True,
                "provider": provider,
                "method": method,
                "status": "manual_secret_entry",
                "message": (
                    "Open the provider setup page, create or copy the supported credential, then paste it into "
                    "Ghost's write-only Config field."
                    if choice.method in {"api_key", "token", "custom"}
                    else choice.setup_hint or "Start the local provider runtime, then save this provider in Config."
                ),
                "auth_url": setup_url,
                "setup_url": setup_url,
                "login_launched": False,
                "runtime_activation_supported": choice.supports_runtime_activation,
                "activation_provider": provider,
                "raw_secret_returned": False,
                "policy": {
                    "secrets_are_write_only": True,
                    "oauth_requires_provider_connector": False,
                    "no_browser_cookie_scraping": True,
                    "token_files_read": False,
                    "api_key_only_provider": choice.method in {"api_key", "token", "custom"},
                },
            }
        if provider in {"openai", "codex_cli"}:
            status = get_codex_cli_status()
            connected = status.available and status.logged_in
            login_launch = None if connected or not launch else launch_codex_login_flow()
            return {
                "ok": True,
                "provider": provider,
                "method": method,
                "status": "connected" if connected else "needs_login",
                "runtime_activation_supported": connected,
                "activation_provider": "codex_cli",
                "message": (
                    "Codex CLI is logged in with ChatGPT/Codex and can be activated as a Ghost model bridge."
                    if connected
                    else (
                        login_launch.detail
                        if login_launch is not None
                        else f"Open a terminal and run the official Codex login flow: {codex_login_command()}"
                    )
                ),
                "auth_url": "",
                "login_command": codex_login_command(),
                "login_launched": bool(login_launch and login_launch.launched),
                "login_launch": login_launch.to_dict() if login_launch is not None else None,
                "manual_required": not connected,
                "raw_secret_returned": False,
                "connector_status": status.to_dict(),
                "policy": {
                    "secrets_are_write_only": True,
                    "oauth_requires_provider_connector": False,
                    "no_browser_cookie_scraping": True,
                    "token_files_read": False,
                },
            }
        if provider == "openrouter":
            payload = start_openrouter_pkce(ctx, console_state_dir, launch=launch).to_dict()
            payload.update(
                {
                    "method": method,
                    "raw_secret_returned": False,
                    "policy": {
                        "secrets_are_write_only": True,
                        "oauth_requires_provider_connector": False,
                        "no_browser_cookie_scraping": True,
                        "token_files_read": False,
                    },
                }
            )
            return payload
        if provider == "huggingface":
            payload = start_huggingface_device_flow(console_state_dir, launch=launch).to_dict()
            payload.update(
                {
                    "method": method,
                    "raw_secret_returned": False,
                    "poll_supported": bool(payload.get("pending_id")),
                    "policy": {
                        "secrets_are_write_only": True,
                        "oauth_requires_provider_connector": False,
                        "no_browser_cookie_scraping": True,
                        "token_files_read": False,
                    },
                }
            )
            return payload
        if provider == "gemini":
            payload = start_google_adc_flow(launch=launch).to_dict()
            payload.update(
                {
                    "method": method,
                    "raw_secret_returned": False,
                    "policy": {
                        "secrets_are_write_only": True,
                        "oauth_requires_provider_connector": False,
                        "no_browser_cookie_scraping": True,
                        "token_files_read": False,
                        "runtime_requires_adc_provider_support": True,
                    },
                }
            )
            return payload
        return {
            "ok": True,
            "provider": provider,
            "method": method,
            "status": choice.status,
            "runtime_activation_supported": choice.supports_runtime_activation,
            "message": choice.setup_hint or choice.description,
            "auth_url": provider_auth_setup_url(provider) or spec.docs_url,
            "setup_url": provider_auth_setup_url(provider) or spec.docs_url,
            "manual_required": True,
            "raw_secret_returned": False,
            "policy": {
                "secrets_are_write_only": True,
                "oauth_requires_provider_connector": True,
                "no_browser_cookie_scraping": True,
                "token_files_read": False,
            },
        }

    def _save_oauth_api_key(
        *,
        provider: str,
        api_key: str,
        model: str = "",
        base_url: str = "",
        make_active: bool = True,
    ) -> dict[str, Any]:
        config = _load_console_config(console_config_file)
        provider_auth = config.setdefault("provider_auth", {})
        provider_auth[provider] = {
            "provider": provider,
            "method": "oauth",
            "api_key": api_key,
            "model": model,
            "base_url": base_url,
            "updated_at": time.time(),
            "oauth_connector": f"{provider}_oauth",
        }
        if make_active:
            spec = get_provider_auth_spec(provider)
            config["model"] = {
                "provider": provider,
                "model": model or (spec.models[0] if spec and spec.models else ""),
                "base_url": base_url,
                "api_key": api_key,
                "api_key_configured": True,
                "oauth_connector": f"{provider}_oauth",
            }
        save_config(config, console_config_file)
        env_vars = config_to_env_vars(config)
        env_file = _write_env_file(console_config_file, env_vars)
        _apply_model_env(env_vars, overwrite=True)
        record_timeline_event(
            console_state_dir,
            "provider_oauth_connected",
            {"provider": provider, "method": "oauth", "secret_configured": bool(api_key)},
        )
        payload = _safe_config_payload(config, console_config_file)
        payload.update({"saved": True, "env_file": str(env_file), "provider_auth": provider_auth_summary(config)})
        return payload

    def provider_auth_openrouter_callback(ctx: dict[str, Any]) -> HttpResponse:
        query = ctx.get("query") or {}
        state = str(query.get("state") or "").strip()
        code = str(query.get("code") or "").strip()
        result = exchange_openrouter_code(console_state_dir, state=state, code=code)
        if result.ok:
            payload = _save_oauth_api_key(
                provider="openrouter",
                api_key=result.api_key,
                model="openai/gpt-5.2",
                make_active=True,
            )
            status = "connected"
            body = (
                "<html><body><h1>OpenRouter connected</h1>"
                "<p>Ghost Chimera stored the returned API key write-only and activated OpenRouter.</p>"
                "<p>You can close this tab and return to Ghost Console.</p>"
                f"<pre>{json.dumps({'ok': True, 'status': status, 'active_provider': payload.get('model', {}).get('provider')}, indent=2)}</pre>"
                "</body></html>"
            )
            return HttpResponse(body=body, content_type="text/html")
        body = (
            "<html><body><h1>OpenRouter connection failed</h1>"
            f"<p>{json.dumps(result.error)}</p>"
            "<p>Return to Ghost Console and try Connect again.</p>"
            "</body></html>"
        )
        return HttpResponse(body=body, status=400, content_type="text/html")

    def provider_auth_oauth_poll(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        provider = str(body.get("provider") or "").strip().lower()
        pending_id = str(body.get("pending_id") or "").strip()
        if provider != "huggingface":
            return {"ok": False, "error": "OAuth polling is currently available for Hugging Face device flow only."}
        result = poll_huggingface_device_flow(console_state_dir, pending_id)
        if not result.ok:
            return {
                "ok": False,
                "provider": provider,
                "status": result.status or "pending",
                "error": result.error,
                "raw_secret_returned": False,
            }
        payload = _save_oauth_api_key(
            provider="huggingface",
            api_key=result.api_key,
            model="meta-llama/Llama-3.3-70B-Instruct",
            make_active=bool(body.get("make_active", True)),
        )
        payload.update({"ok": True, "provider": provider, "status": "connected", "raw_secret_returned": False})
        return payload

    def model_discovery(ctx: dict[str, Any]) -> dict[str, Any]:
        query = ctx.get("query") or {}
        config = _load_console_config(console_config_file)
        try:
            return get_model_discovery(
                config=config,
                state_dir=console_config_file.parent,
                sources=_as_list(query.get("source") or query.get("sources")),
                capabilities=_as_list(query.get("capability") or query.get("capabilities")),
                compatibility=_as_list(query.get("compatibility")),
                query=str(query.get("query") or ""),
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    def model_discovery_refresh(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        config = _load_console_config(console_config_file)
        try:
            refreshed = refresh_model_discovery(
                config=config,
                state_dir=console_config_file.parent,
                sources=_as_list(body.get("sources")),
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": refreshed.get("ok", False),
            "cache_path": refreshed.get("cache_path", ""),
            "sources": refreshed.get("sources", {}),
            "alerts": refreshed.get("alerts", []),
            "model_count": refreshed.get("model_count", 0),
            "policy": refreshed.get("policy", {}),
        }

    def model_discovery_select(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        provider = str(body.get("provider") or "").strip().lower()
        model_id = str(body.get("model_id") or "").strip()
        source = str(body.get("source") or "").strip().lower()
        if not provider or not model_id:
            return {"ok": False, "error": "Select a provider and model."}
        config = _load_console_config(console_config_file)
        selected = select_discovered_model(
            config=config,
            state_dir=console_config_file.parent,
            provider=provider,
            model_id=model_id,
            source=source,
        )
        if not selected.get("ok"):
            return selected
        selected_model = selected.get("selected_model") or {}
        admission = _admission_gate(
            capability_kind="model",
            name=f"{provider}/{model_id}",
            source=source or provider,
            risk_level="medium",
            risk_ceiling="medium",
            requested_permissions=[
                "model_inference",
                "network_provider",
                *([] if not selected.get("requires_api_key", False) else ["api_key"]),
            ],
            metadata=selected_model if isinstance(selected_model, dict) else {},
            inspection={
                "compatibility_status": selected_model.get("compatibility_status") if isinstance(selected_model, dict) else "",
                "requires_api_key": bool(selected.get("requires_api_key", False)),
            },
            reason="Model selection from discovery requires explicit capability admission.",
        )
        if not admission.get("ok"):
            return {
                "ok": False,
                "admission_required": True,
                "error": admission.get("error"),
                "admission_record": admission.get("record"),
                "selected_model": selected_model,
            }
        next_config = selected["config"]
        save_config(next_config, console_config_file)
        env_vars = config_to_env_vars(next_config)
        env_file = _write_env_file(console_config_file, env_vars)
        _apply_model_env(env_vars, overwrite=True)
        record_timeline_event(
            console_state_dir,
            "model_activated",
            {
                "source": source,
                "provider": provider,
                "model_id": model_id,
                "requires_api_key": bool(selected.get("requires_api_key", False)),
                "admission_record": admission.get("record", {}).get("id"),
            },
        )
        upsert_candidate(
            console_state_dir,
            {
                "candidate_type": "model_recommendation",
                "title": f"{provider}/{model_id}",
                "status": "approved",
                "metadata": selected_model if isinstance(selected_model, dict) else {},
                "safety_notes": ["Activated only after explicit operator selection."],
            },
        )
        payload = _safe_config_payload(next_config, console_config_file)
        payload.update(
            {
                "saved": True,
                "env_file": str(env_file),
                "selected_model": selected_model,
                "requires_api_key": selected.get("requires_api_key", False),
                "admission_record": admission.get("record"),
            }
        )
        return payload

    def model_discovery_ping(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        provider_name = str(body.get("provider") or "").strip().lower()
        model_id = str(body.get("model_id") or "").strip()
        base_url = str(body.get("base_url") or "").strip()
        if not provider_name or not model_id:
            return {"ok": False, "error": "Select a provider and model to ping."}
        if len(provider_name) > 80 or len(model_id) > 300 or len(base_url) > 500:
            return {"ok": False, "error": "Ping request is too long."}
        if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
            return {"ok": False, "error": "Base URL must start with http:// or https://."}

        config = _load_console_config(console_config_file)
        active_model = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
        api_key = str(active_model.get("api_key") or "") if active_model.get("provider") == provider_name else ""
        profile = AuthProfile(provider=provider_name, api_key=api_key, base_url=base_url, model=model_id)
        provider = get_provider(provider_name, profile=profile)
        if provider is None:
            return {"ok": False, "error": "Ghost Chimera does not have a provider for this model yet."}
        errors = provider.validate_config()
        if errors:
            return {"ok": False, "error": "Provider is not ready.", "details": errors[:3]}
        try:
            reply = provider.chat(
                "You are Ghost Chimera's model compatibility checker. Reply with a short OK sentence.",
                "Confirm this model can answer a Ghost Chimera console compatibility ping.",
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:500]}
        return {
            "ok": True,
            "provider": provider_name,
            "model_id": model_id,
            "reply_preview": str(reply).strip()[:500],
            "raw_secret_values_returned": False,
        }

    def autonomy(ctx: dict[str, Any]) -> dict[str, Any]:
        if ctx.get("method") == "GET":
            return _status_payload(server)["autonomy"]
        body = _json_body(ctx)
        config = load_config()
        active = get_autonomy_config(config)
        if "level" in body:
            profile = get_autonomy_profile(str(body["level"]))
            active["level"] = profile.name
        for key in (
            "max_tool_rounds",
            "max_parallel_tasks",
            "local_model_profile",
            "require_approval_for_high_impact",
            "true_autonomy_desktop",
            "personal_context",
            "desktop_max_live_actions",
            "desktop_max_session_seconds",
        ):
            if key in body:
                active[key] = body[key]
        config["autonomy"] = active
        save_config(config)
        return {"ok": True, "autonomy": _status_payload(server)["autonomy"]}

    def run(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        objective = str(body.get("objective") or "").strip()
        if not objective:
            return {"ok": False, "error": "Missing objective"}
        trust_run = trust_store.create_run(
            agent_name="ghost_console",
            objective=objective,
            source="console",
            metadata={"route": "/api/console/run"},
        )
        previous_trust_run_id = os.environ.get("GHOSTCHIMERA_TRUST_RUN_ID")
        os.environ["GHOSTCHIMERA_TRUST_RUN_ID"] = trust_run["run_id"]
        try:
            trust_store.record_step(
                trust_run["run_id"],
                step_type="goal_intake",
                status="completed",
                inputs={"objective": objective},
                idempotency_key=f"{trust_run['run_id']}:goal-intake",
            )
            result = objective_runner(objective)
            ok = not (isinstance(result, dict) and result.get("ok") is False)
            trust_store.record_step(
                trust_run["run_id"],
                step_type="execution_result",
                status="completed" if ok else "failed",
                outputs=result if isinstance(result, dict) else {"result": result},
                idempotency_key=f"{trust_run['run_id']}:execution-result",
            )
            if isinstance(result, dict):
                result.setdefault("trust_run", trust_store.get_run(trust_run["run_id"]))
                return result
            return {"ok": True, "result": result, "trust_run": trust_store.get_run(trust_run["run_id"])}
        except PermissionError as exc:
            trust_store.record_step(
                trust_run["run_id"],
                step_type="policy_check",
                status="blocked",
                outputs={"error": str(exc), "type": "permission"},
                policy_decision={"decision": "blocked", "reason": str(exc)},
                idempotency_key=f"{trust_run['run_id']}:permission-error",
            )
            return {"ok": False, "error": str(exc), "type": "permission"}
        except Exception as exc:
            trust_store.record_step(
                trust_run["run_id"],
                step_type="execution_result",
                status="failed",
                outputs={"error": str(exc), "type": "runtime"},
                idempotency_key=f"{trust_run['run_id']}:runtime-error",
            )
            return {"ok": False, "error": str(exc), "type": "runtime"}
        finally:
            if previous_trust_run_id is None:
                os.environ.pop("GHOSTCHIMERA_TRUST_RUN_ID", None)
            else:
                os.environ["GHOSTCHIMERA_TRUST_RUN_ID"] = previous_trust_run_id

    def conversation_sessions(ctx: dict[str, Any]) -> dict[str, Any]:
        if ctx.get("method") == "GET":
            return conversation_store.list_sessions()
        body = _json_body(ctx)
        session = conversation_controller.create_session(
            session_id=str(body.get("session_id") or ""),
            title=str(body.get("title") or "Ghost Conversation"),
            always_listening=_as_bool(body.get("always_listening"), default=True),
        )
        return {"ok": True, "session": session, "settings": conversation_store.settings()}

    def conversation_session_action(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/conversation/sessions/")
        parts = [part for part in suffix.split("/") if part]
        if not parts:
            return {"ok": False, "error": "session_id is required"}
        session_id = parts[0]
        if len(parts) == 1 and ctx.get("method") == "GET":
            try:
                return {"ok": True, "session": conversation_store.get_session(session_id)}
            except KeyError:
                return {"ok": False, "error": "Conversation session not found"}
        if len(parts) != 2:
            return {"ok": False, "error": "Expected /api/console/conversation/sessions/{id}/{action}"}
        action = parts[1]
        body = _json_body(ctx)
        if action in {"turn", "voice-turn"}:
            message = str(body.get("message") or body.get("text") or body.get("objective") or "").strip()
            return conversation_controller.handle_turn(
                session_id,
                message,
                input_mode="voice" if action == "voice-turn" else str(body.get("input_mode") or "text"),
            )
        if action == "approve":
            return conversation_controller.handle_turn(
                session_id,
                "approve",
                input_mode=str(body.get("input_mode") or "text"),
            )
        if action == "deny":
            return conversation_controller.handle_turn(session_id, "deny", input_mode=str(body.get("input_mode") or "text"))
        if action == "stop":
            return conversation_controller.stop(session_id)
        return {"ok": False, "error": f"Unsupported conversation action: {action}"}

    def conversation_status(ctx: dict[str, Any]) -> dict[str, Any]:
        return conversation_controller.status()

    def conversation_settings(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        allowed = {
            key: body[key]
            for key in ("always_listening", "hands_free", "full_bypass", "voice_provider", "voice_id")
            if key in body
        }
        payload = conversation_controller.update_settings(**allowed)
        if "full_bypass" in allowed:
            record_timeline_event(
                console_state_dir,
                "conversation_full_bypass_changed",
                {"enabled": bool(payload.get("settings", {}).get("full_bypass"))},
            )
        return payload

    def browser_fetch(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        url = str(body.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "Missing url"}
        try:
            content = url_fetcher(url)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "url": url, "content": content[:100_000], "truncated": len(content) > 100_000}

    def browser_workspace_status(ctx: dict[str, Any]) -> dict[str, Any]:
        return workspace.status()

    def browser_open(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        url = str(body.get("url") or "").strip()
        session = str(body.get("session") or "default").strip() or "default"
        if not url:
            return {"ok": False, "error": "Missing url"}
        try:
            return workspace.open(url, session=session)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def browser_snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        url = str(body.get("url") or "").strip()
        session = str(body.get("session") or "default").strip() or "default"
        try:
            return workspace.snapshot(url=url, session=session)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def operator_workspace_snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
        return workspace_store.snapshot()

    def operator_workspace_evidence(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        try:
            return workspace_store.add_evidence(
                str(body.get("source") or "").strip(),
                str(body.get("content") or "").strip(),
                confidence=float(body.get("confidence", 0.5)),
            )
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def operator_workspace_reflection(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        try:
            return workspace_store.add_reflection(
                action=str(body.get("action") or body.get("reflection_action") or "").strip(),
                outcome=str(body.get("outcome") or "").strip(),
                confidence=float(body.get("confidence", 0.5)),
            )
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def operator_workspace_goal(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        try:
            return workspace_store.set_goal(
                str(body.get("name") or body.get("goal") or "").strip(),
                str(body.get("description") or "").strip(),
            )
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def operator_workspace_sync_memory(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        try:
            return workspace_store.sync_to_memory(
                memory_db=str(body.get("memory_db") or server.config.memory_db),
                min_confidence=float(body.get("min_confidence", 0.0)),
                stale_after_days=float(body.get("stale_after_days", 30.0)),
            )
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def memory_status(ctx: dict[str, Any]) -> dict[str, Any]:
        store = MemoryStore(server.config.memory_db)
        return {"ok": True, "memory_db": str(store.db_path), "count": store.count()}

    def memory_ingest(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        source = str(body.get("source") or "").strip()
        content = str(body.get("content") or "").strip()
        metadata = dict(body.get("metadata") or {})
        if not source:
            return {"ok": False, "error": "Missing source"}
        if not content:
            return {"ok": False, "error": "Missing content"}
        store = MemoryStore(server.config.memory_db)
        row_id = store.add_document(source, content, metadata=metadata)
        return {"ok": True, "id": row_id, "count": store.count()}

    def memory_ingest_email(ctx: dict[str, Any]) -> dict[str, Any]:
        """Ingest email content into personal memory.

        Accepts either a ``raw`` email string (RFC 2822 format pasted
        directly) or a ``path`` pointing to a ``.eml`` or ``.mbox`` file
        on the server.  The two fields are mutually exclusive; ``raw``
        takes priority.
        """
        from ..personalization.email_ingester import EmailIngester

        body = _json_body(ctx)
        raw = str(body.get("raw") or "").strip()
        path = str(body.get("path") or "").strip()

        store = MemoryStore(server.config.memory_db)
        ingester = EmailIngester(store)

        if raw:
            result = ingester.ingest_raw_email(raw)
        elif path:
            p = Path(path).expanduser()
            if not p.exists():
                return {"ok": False, "error": f"File not found: {path}"}
            result = ingester.ingest_mbox_file(p) if p.suffix.lower() == ".mbox" else ingester.ingest_eml_file(p)
        else:
            return {"ok": False, "error": "Provide 'raw' email text or a 'path' to a .eml/.mbox file"}

        return {
            "ok": True,
            "ingested": result.ingested,
            "skipped": result.skipped,
            "errors": result.errors,
            "count": store.count(),
        }

    def memory_ingest_file(ctx: dict[str, Any]) -> dict[str, Any]:
        """Ingest a local document file into personal memory.

        Accepts a ``path`` to a supported text file (``.txt``, ``.md``,
        ``.py``, ``.json``, etc.) or a directory.  Directories are
        ingested recursively (up to 500 files).
        """
        from ..personalization.document_ingester import DocumentIngester

        body = _json_body(ctx)
        path = str(body.get("path") or "").strip()
        source = str(body.get("source") or "").strip()
        max_files = int(body.get("max_files") or 500)

        if not path:
            return {"ok": False, "error": "Provide a 'path' to a file or directory"}

        p = Path(path).expanduser()
        if not p.exists():
            return {"ok": False, "error": f"Path not found: {path}"}

        store = MemoryStore(server.config.memory_db)
        ingester = DocumentIngester(store)

        if p.is_dir():
            result = ingester.ingest_directory(p, max_files=max_files)
        else:
            result = ingester.ingest_file(p, source_prefix=source)

        return {
            "ok": True,
            "ingested": result.ingested,
            "skipped": result.skipped,
            "chunks": result.chunks,
            "errors": result.errors,
            "count": store.count(),
        }

    def memory_search(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        query = str(body.get("query") or "").strip()
        limit = int(body.get("limit") or 5)
        stale_after_days = body.get("stale_after_days")
        store = MemoryStore(server.config.memory_db)
        results = store.search(
            query,
            limit=limit,
            stale_after_days=float(stale_after_days) if stale_after_days is not None else None,
        )
        return {"ok": True, "query": query, "results": results}

    def training_status(ctx: dict[str, Any]) -> dict[str, Any]:
        """Return MiniMind training setup status including dataset record count."""
        autonomy_cfg = get_autonomy_config(load_config())
        profile_name = str(autonomy_cfg.get("local_model_profile") or "tiny")
        lifecycle = MiniMindLifecycle(profile_name=profile_name, state_dir=server.config.state_dir)
        status = lifecycle.status().to_dict()
        dataset_path = Path(server.config.state_dir) / "minimind" / "datasets" / "dataset.jsonl"
        dataset_count = 0
        if dataset_path.exists():
            with contextlib.suppress(Exception):
                dataset_count = sum(1 for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip())
        status["dataset_path"] = str(dataset_path)
        status["dataset_count"] = dataset_count
        return {"ok": True, "status": status}

    def training_teach(ctx: dict[str, Any]) -> dict[str, Any]:
        """Append a prompt/response pair to the MiniMind training dataset.

        This is Ghost's primary learning interface: every time Ghost gives
        a good answer, you can record it here to build a personal training
        corpus.  The dataset grows over time and can later be used for
        local MiniMind fine-tuning.
        """
        body = _json_body(ctx)
        prompt = str(body.get("prompt") or "").strip()
        response = str(body.get("response") or "").strip()
        if not prompt:
            return {"ok": False, "error": "Missing 'prompt'"}
        if not response:
            return {"ok": False, "error": "Missing 'response'"}
        autonomy_cfg = get_autonomy_config(load_config())
        profile_name = str(autonomy_cfg.get("local_model_profile") or "tiny")
        lifecycle = MiniMindLifecycle(profile_name=profile_name, state_dir=server.config.state_dir)
        path = lifecycle.generate_dataset([{"prompt": prompt, "response": response}])
        dataset_count = 0
        with contextlib.suppress(Exception):
            dataset_count = sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())
        return {"ok": True, "path": str(path), "dataset_count": dataset_count}

    def minimind_status(ctx: dict[str, Any]) -> dict[str, Any]:
        autonomy_cfg = get_autonomy_config(load_config())
        profile_name = str(autonomy_cfg.get("local_model_profile") or "tiny")
        status = MiniMindLifecycle(profile_name=profile_name, state_dir=server.config.state_dir).status()
        return {"ok": True, "status": status.to_dict()}

    def minimind_dataset(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        records = list(body.get("records") or [])
        output_path = str(body.get("output_path") or "").strip() or None
        autonomy_cfg = get_autonomy_config(load_config())
        profile_name = str(autonomy_cfg.get("local_model_profile") or "tiny")
        lifecycle = MiniMindLifecycle(profile_name=profile_name, state_dir=server.config.state_dir)
        path = lifecycle.generate_dataset(records, output_path=output_path)
        return {"ok": True, "path": str(path), "count": len(records)}

    def personal_minimind() -> MiniMindPersonalAgent:
        autonomy_cfg = get_autonomy_config(load_config())
        profile_name = str(autonomy_cfg.get("local_model_profile") or server.config.local_model_profile or "tiny")
        return MiniMindPersonalAgent(
            state_dir=server.config.state_dir,
            memory_db=server.config.memory_db,
            profile_name=profile_name,
        )

    def minimind_personal_status(ctx: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": personal_minimind().status()}

    def minimind_personal_consent(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        return personal_minimind().grant_consent(
            admin_controls=bool(body.get("admin_controls", False)),
            allow_system_specs=bool(body.get("allow_system_specs", False)),
            allow_files=bool(body.get("allow_files", False)),
            allow_email=bool(body.get("allow_email", False)),
            allow_machine_crawl=bool(body.get("allow_machine_crawl", False)),
            allow_email_crawl=bool(body.get("allow_email_crawl", False)),
            allow_autonomy=bool(body.get("allow_autonomy", False)),
            allow_training=bool(body.get("allow_training", False)),
            file_paths=list(body.get("file_paths") or []),
            email_paths=list(body.get("email_paths") or []),
            crawl_roots=list(body.get("crawl_roots") or []),
            exclude_paths=list(body.get("exclude_paths") or []),
            operator=str(body.get("operator") or "operator"),
        )

    def minimind_personal_revoke(ctx: dict[str, Any]) -> dict[str, Any]:
        return personal_minimind().revoke_consent()

    def minimind_personal_bootstrap(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        return personal_minimind().bootstrap(
            file_paths=list(body.get("file_paths") or []),
            email_paths=list(body.get("email_paths") or []),
            include_system_specs=bool(body.get("include_system_specs", False)),
            max_files=int(body.get("max_files") or 500),
            max_emails=int(body.get("max_emails") or 1000),
        )

    def minimind_personal_handoff(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        objective = str(body.get("objective") or "").strip()
        if not objective:
            return {"ok": False, "error": "Missing objective"}
        return personal_minimind().build_handoff(objective)

    def minimind_post_training_action(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        objective = str(body.get("objective") or "").strip() or (
            "Use the current Personal MiniMind dataset and memory handoff to identify the next safe Ghost improvement."
        )
        status = personal_minimind().status()
        readiness = status.get("readiness") if isinstance(status.get("readiness"), dict) else {}
        autonomy_cfg = get_autonomy_config(load_config())
        lifecycle = MiniMindLifecycle(
            profile_name=str(autonomy_cfg.get("local_model_profile") or server.config.local_model_profile or "tiny"),
            state_dir=server.config.state_dir,
        )
        lifecycle.generate_dataset(
            [
                {
                    "prompt": objective,
                    "response": (
                        "Summarize learned context, run safe readiness checks, stage one reviewed "
                        "Self-Evolution candidate, and require explicit approval before promotion."
                    ),
                }
            ]
        )
        local_adapter = lifecycle.train_local_adapter()
        local_inference = lifecycle.infer(objective) if local_adapter.get("ok") else {"ok": False, "answer": ""}
        training = training_status({"method": "GET", "path": "/api/console/training/status", "headers": {}, "body": "", "query": {}})
        training_state = training.get("status") if isinstance(training.get("status"), dict) else {}
        status = personal_minimind().status()
        readiness = status.get("readiness") if isinstance(status.get("readiness"), dict) else readiness
        handoff = personal_minimind().build_handoff(objective)
        source = create_learning_source(
            console_state_dir,
            {
                "source_type": "manual_note",
                "label": "Personal MiniMind post-training review",
                "scope": "global",
                "consent_status": "approved" if readiness.get("consent_ready") else "pending",
                "risk_level": "low",
                "provenance": {
                    "dataset_count": training_state.get("dataset_count", 0),
                    "memory_count": status.get("memory_count", 0),
                    "handoff_ready": bool(readiness.get("primary_model_handoff_ready")),
                    "inference_ready": bool(readiness.get("inference_ready")),
                },
                "notes": "Generated from explicit operator post-training action.",
            },
        )
        candidate = upsert_candidate(
            console_state_dir,
            {
                "candidate_type": "config_improvement",
                "title": "Post-training Ghost readiness improvement",
                "source_id": source["id"],
                "status": "reviewed",
                "required_permissions": ["operator_review", "readiness_check"],
                "safety_notes": [
                    "Review candidate before promotion.",
                    "No email scraping, file mutation, MCP enablement, skill activation, or model switching was performed.",
                    "Local MiniMind inference uses the Ghost-native dataset adapter; neural weight fine-tuning remains optional future work.",
                ],
                "metadata": {
                    "objective": objective,
                    "dataset_count": training_state.get("dataset_count", 0),
                    "memory_count": status.get("memory_count", 0),
                    "readiness": readiness,
                    "handoff_context_chars": len(str(handoff.get("personal_context") or "")),
                    "handoff_sources": len(handoff.get("sources") or []) if isinstance(handoff.get("sources"), list) else 0,
                    "local_adapter": local_adapter.get("adapter", {}),
                    "local_inference": {
                        "ok": bool(local_inference.get("ok")),
                        "confidence": local_inference.get("confidence", 0.0),
                        "record_id": local_inference.get("record_id", ""),
                    },
                },
            },
        )
        jobs: list[dict[str, Any]] = []
        for job_name in ("self-audit", "model-health-check", "memory-refresh"):
            with contextlib.suppress(Exception):
                jobs.append(queue.enqueue(job_name, profile="supervised", execute=False, run_now=True))
        summary = _operator_summary_payload()
        record_timeline_event(
            console_state_dir,
            "minimind_post_training_action_run",
            {
                "candidate_id": candidate.get("id"),
                "dataset_count": training_state.get("dataset_count", 0),
                "jobs": [job.get("name") for job in jobs],
                "handoff_ready": bool(readiness.get("primary_model_handoff_ready")),
            },
        )
        return {
            "ok": True,
            "objective": objective,
            "mode": "review_then_activate",
            "status": status,
            "training": training_state,
            "handoff": {
                "ok": bool(handoff.get("ok")),
                "personal_context_chars": len(str(handoff.get("personal_context") or "")),
                "source_count": len(handoff.get("sources") or []) if isinstance(handoff.get("sources"), list) else 0,
                "primary_model_prompt_chars": len(str(handoff.get("primary_model_prompt") or "")),
            },
            "local_adapter": local_adapter,
            "local_inference": local_inference,
            "learning_source": source,
            "candidate": candidate,
            "jobs": jobs,
            "summary": summary,
            "next_approvals": [
                "Review the Self-Evolution candidate.",
                "Promote only after checking the safety notes and required permissions.",
                (
                    "Optional: install MiniMind weights and training dependencies only if you need neural fine-tuning beyond the local dataset adapter."
                    if local_adapter.get("ok")
                    else "Train or configure a local MiniMind adapter before expecting local inference."
                ),
            ],
        }

    def email_oauth_status_route(ctx: dict[str, Any]) -> dict[str, Any]:
        return email_oauth_status(server.config.state_dir)

    def email_oauth_start_route(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        provider = str(body.get("provider") or "").strip().lower()
        return start_email_oauth(provider, server.config.state_dir)

    def _console_redirect_uri(ctx: dict[str, Any]) -> str:
        headers = {str(k).lower(): str(v) for k, v in dict(ctx.get("headers") or {}).items()}
        host = headers.get("host") or f"127.0.0.1:{server.http_port}"
        scheme = headers.get("x-forwarded-proto") or ("https" if headers.get("x-forwarded-ssl") == "on" else "http")
        return f"{scheme}://{host}"

    def email_oauth_browser_start_route(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        provider = str(body.get("provider") or "gmail").strip().lower()
        if provider != "gmail":
            return {
                "ok": False,
                "provider": provider,
                "status": "unsupported_browser_flow",
                "error": "Browser OAuth is currently available for Gmail. Use device login for Outlook.",
            }
        return start_gmail_browser_oauth(server.config.state_dir, _console_redirect_uri(ctx))

    def email_oauth_browser_callback_route(ctx: dict[str, Any]) -> HttpResponse:
        query = ctx.get("query") or {}
        state = str(query.get("state") or "").strip()
        code = str(query.get("code") or "").strip()
        provider_error = str(query.get("error") or "").strip()
        provider_error_description = str(query.get("error_description") or "").strip()
        if provider_error:
            safe_error = html.escape(provider_error_description or provider_error)
            return HttpResponse(
                body=(
                    "<html><body><h1>Gmail connection failed</h1>"
                    f"<p>{safe_error}</p><p>You can close this tab and return to Ghost Console.</p>"
                    "</body></html>"
                ),
                status=400,
                content_type="text/html",
            )
        result = finish_gmail_browser_oauth(server.config.state_dir, state, code)
        if result.get("ok"):
            return HttpResponse(
                body=(
                    "<html><body><h1>Gmail connected</h1>"
                    "<p>Read-only Gmail OAuth is connected. You can close this tab and return to Ghost Console.</p>"
                    "</body></html>"
                ),
                content_type="text/html",
            )
        safe_error = html.escape(str(result.get("error") or "OAuth callback failed."))
        return HttpResponse(
            body=(
                "<html><body><h1>Gmail connection failed</h1>"
                f"<p>{safe_error}</p><p>You can close this tab and return to Ghost Console.</p>"
                "</body></html>"
            ),
            status=400,
            content_type="text/html",
        )

    def email_oauth_poll_route(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        provider = str(body.get("provider") or "").strip().lower()
        pending_id = str(body.get("pending_id") or "").strip()
        return poll_email_oauth(provider, server.config.state_dir, pending_id)

    def email_oauth_crawl_route(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        provider = str(body.get("provider") or "").strip().lower()
        max_messages = int(body.get("max_messages") or 10)
        query = str(body.get("query") or "")
        consent = personal_minimind().load_consent()
        if not consent.enabled or not consent.allow_email_crawl:
            return {
                "ok": False,
                "type": "consent_required",
                "error": "Enable Personal MiniMind admin controls and email crawl consent before OAuth email crawling.",
            }
        result = crawl_email_provider(
            provider,
            server.config.state_dir,
            memory_db=server.config.memory_db,
            max_messages=max_messages,
            query=query,
            generate_training=consent.allow_training,
        )
        if result.get("ok"):
            record_timeline_event(
                console_state_dir,
                "email_oauth_crawl_run",
                {
                    "provider": provider,
                    "messages_seen": result.get("messages_seen", 0),
                    "ingested": result.get("ingested", 0),
                    "raw_secret_returned": False,
                },
            )
        return result

    def capabilities(ctx: dict[str, Any]) -> dict[str, Any]:
        return inspect_capabilities()

    def role_profiles(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..personalization.role_profiles import list_role_profiles

        return {"ok": True, "profiles": [profile.to_dict() for profile in list_role_profiles()]}

    def synthesize_role_path(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..personalization.path_synthesizer import synthesize_path

        body = _json_body(ctx)
        profile_id = str(body.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        preferences = body.get("preferences") or {}
        if not isinstance(preferences, dict):
            return {"ok": False, "error": "preferences must be an object"}
        return {"ok": True, "path": synthesize_path(profile_id, preferences=preferences)}

    def confirm_path_minimind(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..personalization.path_synthesizer import synthesize_path

        body = _json_body(ctx)
        profile_id = str(body.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        preferences = body.get("preferences") or {}
        if not isinstance(preferences, dict):
            return {"ok": False, "error": "preferences must be an object"}
        path = synthesize_path(profile_id, preferences=preferences)
        minimind_intake = path.get("minimind_intake") if isinstance(path, dict) else {}
        if not isinstance(minimind_intake, dict):
            minimind_intake = {}
        record_timeline_event(
            console_state_dir,
            "minimind_permission_changed",
            {"profile_id": profile_id, "confirmation": str(minimind_intake.get("confirmation") or "")},
        )
        return {
            "ok": True,
            "profile_id": profile_id,
            "preferences": preferences,
            "confirmation": str(minimind_intake.get("confirmation") or ""),
            "minimind_intake": minimind_intake,
            "path": path,
        }

    def active_role_path(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..personalization.path_state import get_active_ghost_path, set_active_ghost_path

        if ctx.get("method") == "GET":
            return {"ok": True, "path": get_active_ghost_path(config_path=path_config_file)}
        body = _json_body(ctx)
        profile_id = str(body.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        preferences = body.get("preferences") or {}
        if not isinstance(preferences, dict):
            return {"ok": False, "error": "preferences must be an object"}
        try:
            path = set_active_ghost_path(profile_id, preferences=preferences, config_path=path_config_file)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        record_timeline_event(
            console_state_dir,
            "path_selected",
            {
                "profile_id": profile_id,
                "training_mode": preferences.get("training_mode"),
                "approval_level": preferences.get("approval_level"),
            },
        )
        return {"ok": True, "path": path}

    def thinking_trace(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..personalization.path_state import get_active_ghost_path

        status_payload = _status_payload(server)
        active_path = get_active_ghost_path(config_path=path_config_file)
        workspace_snapshot = workspace_store.snapshot()
        minimind = personal_minimind().status()
        capability_payload = inspect_capabilities()
        resolved_profile = status_payload.get("autonomy", {}).get("resolved_profile", {})
        capability_count = len(capability_payload.get("capabilities") or [])
        covered_count = sum(1 for item in capability_payload.get("capabilities") or [] if item.get("status") == "covered")
        nodes = [
            {
                "id": "objective",
                "label": "Objective Intake",
                "layer": "operator",
                "status": "ready",
                "detail": "Receives the user's current goal and selected Ghost Path.",
            },
            {
                "id": "policy",
                "label": "Policy Gate",
                "layer": "safety",
                "status": "active",
                "detail": "Checks autonomy level, approval rules, and high-impact controls.",
            },
            {
                "id": "path",
                "label": "Ghost Path",
                "layer": "personalization",
                "status": "active" if active_path.get("profile_id") else "ready",
                "detail": f"Active profile: {active_path.get('profile_id') or 'default'}",
            },
            {
                "id": "memory",
                "label": "Memory / RAG",
                "layer": "context",
                "status": "active" if minimind.get("readiness", {}).get("ready") else "guarded",
                "detail": "Uses consented MiniMind and workspace context when available.",
            },
            {
                "id": "planner",
                "label": "Planner",
                "layer": "reasoning",
                "status": "ready",
                "detail": "Decomposes work into ordered, auditable steps.",
            },
            {
                "id": "scheduler",
                "label": "Scheduler",
                "layer": "orchestration",
                "status": "ready",
                "detail": f"Autonomy profile: {resolved_profile.get('name') or 'unknown'}",
            },
            {
                "id": "tools",
                "label": "Tool Router",
                "layer": "execution",
                "status": "ready",
                "detail": "Chooses allowed backends, skills, GitHub actions, browser, or local tools.",
            },
            {
                "id": "verification",
                "label": "Verification",
                "layer": "quality",
                "status": "ready",
                "detail": f"Capability matrix: {covered_count}/{capability_count} covered.",
            },
            {
                "id": "audit",
                "label": "Audit Handoff",
                "layer": "governance",
                "status": "ready",
                "detail": "Returns evidence, decisions, approvals, and next safe action.",
            },
        ]
        edges = [
            ("objective", "policy"),
            ("policy", "path"),
            ("path", "memory"),
            ("memory", "planner"),
            ("planner", "scheduler"),
            ("scheduler", "tools"),
            ("tools", "verification"),
            ("verification", "audit"),
        ]
        return {
            "ok": True,
            "note": "This is an explainability trace of Ghost Chimera runtime signals, not a claim of literal consciousness.",
            "active_path": active_path,
            "workspace": {
                "evidence_count": len(workspace_snapshot.get("evidence") or []),
                "reflection_count": len(workspace_snapshot.get("reflections") or []),
                "goal_count": len(workspace_snapshot.get("goals") or []),
            },
            "minimind": {
                "ready": bool(minimind.get("readiness", {}).get("ready")),
                "reasons": list(minimind.get("readiness", {}).get("reasons") or []),
            },
            "autonomy": resolved_profile,
            "capabilities": {"covered": covered_count, "total": capability_count},
            "nodes": nodes,
            "edges": [{"from": left, "to": right} for left, right in edges],
        }

    def github_status(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..integrations.github_client import GitHubAuth, github_oauth_client_id

        auth = GitHubAuth.discover()
        stored = _read_github_console_auth()
        has_stored_token = bool(stored.get("token"))
        user = stored.get("user") if isinstance(stored.get("user"), dict) else {}
        return {
            "ok": True,
            "auth_mode": "console-device-token" if has_stored_token else auth.mode,
            "has_token": has_stored_token or bool(auth.token),
            "token_source": "console_state" if has_stored_token else ("environment" if auth.token else "gh-cli"),
            "user": {
                "login": user.get("login", ""),
                "name": user.get("name", ""),
                "html_url": user.get("html_url", ""),
            },
            "device_flow_configured": bool(github_oauth_client_id()),
            "device_flow_required_env": "GHOSTCHIMERA_GITHUB_CLIENT_ID",
            "self_evolution_policy": {
                "mode": "preview_only",
                "requires_user_approval": True,
                "requires_license": True,
                "requires_commit": True,
                "allowed_training_licenses": ["Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0", "MIT"],
                "blocked": [
                    "unknown-license training",
                    "private repo ingestion without explicit user approval",
                    "automatic dependency installation",
                    "unreviewed MCP or skill activation",
                ],
            },
        }

    def github_device_start(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..integrations.github_client import github_oauth_client_id, start_device_flow

        client_id = github_oauth_client_id()
        if not client_id:
            return {
                "ok": False,
                "error": "GitHub device sign-in is disabled until GHOSTCHIMERA_GITHUB_CLIENT_ID is configured.",
                "setup": "Create a GitHub OAuth app with device flow enabled, then set GHOSTCHIMERA_GITHUB_CLIENT_ID.",
            }
        body = _json_body(ctx)
        scope = str(body.get("scope") or "read:user repo").strip() or "read:user repo"
        try:
            code = start_device_flow(client_id=client_id, scope=scope)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        payload = code.to_dict()
        payload.update({"ok": True, "scope": scope})
        return payload

    def github_device_poll(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..integrations.github_client import fetch_authenticated_user, github_oauth_client_id, poll_device_flow

        client_id = github_oauth_client_id()
        if not client_id:
            return {"ok": False, "error": "GitHub device sign-in is disabled."}
        body = _json_body(ctx)
        device_code = str(body.get("device_code") or "").strip()
        if not device_code:
            return {"ok": False, "error": "device_code is required"}
        try:
            result = poll_device_flow(client_id=client_id, device_code=device_code)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if result.get("error"):
            return {
                "ok": False,
                "pending": result.get("error") == "authorization_pending",
                "error": str(result.get("error_description") or result.get("error")),
            }
        token = str(result.get("access_token") or "")
        if not token:
            return {"ok": False, "pending": True, "error": "No token returned yet."}
        try:
            user = fetch_authenticated_user(token)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        _write_github_console_auth(
            {
                "token": token,
                "scope": str(result.get("scope") or ""),
                "token_type": str(result.get("token_type") or "bearer"),
                "user": {
                    "login": user.get("login", ""),
                    "name": user.get("name", ""),
                    "html_url": user.get("html_url", ""),
                },
                "created_at": int(time.time()),
            }
        )
        return {
            "ok": True,
            "auth_mode": "console-device-token",
            "has_token": True,
            "user": {"login": user.get("login", ""), "name": user.get("name", ""), "html_url": user.get("html_url", "")},
        }

    def github_logout(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..integrations.github_client import GitHubAuth

        _delete_github_console_auth()
        return {"ok": True, "auth_mode": GitHubAuth.discover().mode}

    def github_self_evolution_preview(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..integrations.source_discovery import SourceCandidate, filter_allowed_sources

        body = _json_body(ctx)
        requested = [str(item).strip() for item in body.get("materials") or [] if str(item).strip()]
        repos = [str(item).strip() for item in body.get("repos") or [] if str(item).strip()]
        candidates = [
            SourceCandidate(url=f"https://github.com/{repo}", kind="repository", license="", commit="") for repo in repos
        ]
        candidates.extend(
            [
                SourceCandidate(url="https://github.com/modelcontextprotocol/servers", kind="mcp_catalog", license="MIT"),
                SourceCandidate(url="https://github.com/github/docs", kind="open_source_docs", license="CC0-1.0"),
            ]
        )
        allowed_for_training = filter_allowed_sources(candidates, intended_use="dataset_generation")
        return {
            "ok": True,
            "mode": "preview_only",
            "requested_materials": requested or ["verified_skills", "mcp_servers", "open_source_reference_materials"],
            "requires_user_approval": True,
            "actions": [
                "discover GitHub repositories selected by the signed-in user",
                "read license metadata before any dataset or fine-tuning use",
                "record immutable commit SHA for every source",
                "stage candidate skills/MCP servers in review mode",
                "run safety, license, and capability checks before activation",
            ],
            "blocked_actions": [
                "silent scraping of private repositories",
                "training on unknown-license material",
                "auto-installing MCP servers without review",
                "changing Ghost behavior without an audit record",
            ],
            "candidate_count": len(candidates),
            "allowed_for_training": [candidate.to_dict() for candidate in allowed_for_training],
            "review_required": [candidate.to_dict() for candidate in candidates if candidate not in allowed_for_training],
        }

    def github_plan(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..integrations.github_tasks import GitHubIssue, issue_to_objective

        body = _json_body(ctx)
        repo = str(body.get("repo") or "").strip()
        issue_number = int(body.get("issue") or 0)
        if not repo or issue_number <= 0:
            return {"ok": False, "error": "repo and issue are required"}
        issue = GitHubIssue(
            repo=repo,
            number=issue_number,
            title=str(body.get("title") or f"Issue {issue_number}"),
            body=str(body.get("body") or ""),
            labels=[str(label) for label in body.get("labels") or []],
        )
        return {"ok": True, "objective": issue_to_objective(issue)}

    def github_policy_simulate(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..integrations.github_policy import simulate_github_action_policy

        body = _json_body(ctx)
        action = body.get("action") or {}
        controls = body.get("controls") or {}
        if not isinstance(action, dict) or not isinstance(controls, dict):
            return {"ok": False, "error": "action and controls must be objects"}
        return simulate_github_action_policy(action, controls)

    def review_pr(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        report = run_pr_review(
            base=str(body.get("base") or "origin/main"),
            head=str(body.get("head") or "HEAD"),
            max_diff_bytes=int(body.get("max_diff_bytes") or 500_000),
        )
        return report.to_dict()

    def readiness(ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "checks": [dict(check) for check in RELEASE_CHECKS],
            "note": "Run these checks locally before tagging or pushing a beta release.",
        }

    def rag_builder_status(ctx: dict[str, Any]) -> dict[str, Any]:
        status = personal_minimind().status()
        return {
            "ok": True,
            "status": status,
            "note": "Use RAG Builder to confirm open-source intake policy and produce a guided MiniMind build plan.",
        }

    def rag_builder_plan(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..integrations.source_discovery import SourceCandidate, filter_allowed_sources
        from ..personalization.path_synthesizer import synthesize_path

        body = _json_body(ctx)
        profile_id = str(body.get("profile_id") or "").strip()
        if not profile_id:
            return {"ok": False, "error": "profile_id is required"}
        objective = str(body.get("objective") or "").strip()
        training_mode = str(body.get("training_mode") or "rag-first").strip() or "rag-first"
        approval_level = str(body.get("approval_level") or "supervised").strip() or "supervised"
        execute_bootstrap = _as_bool(body.get("execute_bootstrap"), default=False)
        include_system_specs = _as_bool(body.get("include_system_specs"), default=False)
        max_files = int(body.get("max_files") or 500)
        max_emails = int(body.get("max_emails") or 1000)
        repos = [str(item).strip() for item in body.get("open_source_repos") or [] if str(item).strip()]
        path = synthesize_path(profile_id, preferences={"training_mode": training_mode, "approval_level": approval_level})
        intake = path.get("minimind_intake") if isinstance(path, dict) else {}
        if not isinstance(intake, dict):
            intake = {}

        github = _github_client_with_console_token()
        candidates: list[SourceCandidate] = []
        for repo in repos:
            try:
                details = github.get_json(f"repos/{repo}")
            except Exception:
                candidates.append(SourceCandidate(url=f"https://github.com/{repo}", kind="repository", license="", commit=""))
                continue
            if not isinstance(details, dict):
                candidates.append(SourceCandidate(url=f"https://github.com/{repo}", kind="repository", license="", commit=""))
                continue
            license_id = ""
            license_data = details.get("license")
            if isinstance(license_data, dict):
                license_id = str(license_data.get("spdx_id") or "").strip()
            branch = str(details.get("default_branch") or "main").strip() or "main"
            commit_sha = ""
            with contextlib.suppress(Exception):
                commit_payload = github.get_json(f"repos/{repo}/commits/{branch}")
                if isinstance(commit_payload, dict):
                    commit_sha = str(commit_payload.get("sha") or "").strip()
            candidates.append(
                SourceCandidate(
                    url=str(details.get("html_url") or f"https://github.com/{repo}"),
                    kind="repository",
                    license=license_id,
                    commit=commit_sha,
                )
            )

        intended_use = "dataset_generation" if training_mode in {"dataset_generation", "local_fine_tuning"} else "rag"
        allowed_sources = filter_allowed_sources(candidates, intended_use=intended_use)
        blocked_sources = [candidate for candidate in candidates if candidate not in allowed_sources]
        bootstrap = {"ok": False, "skipped": True}
        if execute_bootstrap:
            bootstrap = personal_minimind().bootstrap(
                include_system_specs=include_system_specs,
                max_files=max_files,
                max_emails=max_emails,
            )
        for candidate in candidates:
            candidate_payload = candidate.to_dict()
            source = create_learning_source(
                console_state_dir,
                {
                    "source_type": "github_repo",
                    "label": candidate_payload.get("url", "GitHub repository"),
                    "uri": candidate_payload.get("url", ""),
                    "scope": "path-specific",
                    "consent_status": "pending",
                    "risk_level": "medium" if candidate in blocked_sources else "low",
                    "provenance": {
                        "profile_id": profile_id,
                        "intended_use": intended_use,
                        "license": candidate_payload.get("license", ""),
                        "commit": candidate_payload.get("commit", ""),
                    },
                },
            )
            upsert_candidate(
                console_state_dir,
                {
                    "candidate_type": "rag_knowledge_update",
                    "title": f"RAG source for {profile_id}: {candidate_payload.get('url', '')}",
                    "source_id": source["id"],
                    "status": "reviewed" if candidate in allowed_sources else "discovered",
                    "required_permissions": ["learning_source_approval"],
                    "safety_notes": ["Review license and consent before indexing."],
                    "metadata": candidate_payload,
                },
            )
        record_timeline_event(
            console_state_dir,
            "rag_plan_generated",
            {
                "profile_id": profile_id,
                "training_mode": training_mode,
                "requested_sources": len(candidates),
                "allowed_sources": len(allowed_sources),
                "review_required": len(blocked_sources),
                "bootstrap_executed": bool(execute_bootstrap),
            },
        )
        return {
            "ok": True,
            "objective": objective,
            "path": path,
            "minimind_intake": intake,
            "open_source_sources": {
                "requested": [candidate.to_dict() for candidate in candidates],
                "allowed_for_training": [candidate.to_dict() for candidate in allowed_sources],
                "review_required": [candidate.to_dict() for candidate in blocked_sources],
            },
            "bootstrap": bootstrap,
            "recommendation": intake.get("confirmation")
            or "Review source licenses and explicit consent before dataset generation.",
        }

    def mcp_status(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..chimera_pilot.mcp_wrapper import get_default_registry

        registry = get_default_registry()
        client = registry.get("chimeralang")
        tools = []
        if client and client.available:
            tools = [tool.get("name") for tool in client.tools if isinstance(tool, dict)]
        return {
            "ok": True,
            "registered": client is not None,
            "enabled": bool(client and client.available),
            "tool_count": len(tools),
            "tools": tools,
            "module_detected": bool(importlib.util.find_spec("chimeralang_mcp")),
            "trust": trust_store.mcp_trust_list().get("servers", []),
        }

    def mcp_enable_chimeralang(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..chimera_pilot.mcp_wrapper import connect_mcp_servers, get_default_registry, register_mcp_server

        registry = get_default_registry()
        if registry.get("chimeralang") is None:
            register_mcp_server(
                "chimeralang",
                command=sys.executable or "python3",
                args=["-m", "chimeralang_mcp.server", "--transport", "stdio"],
                timeout=180,
            )
        try:
            connect_mcp_servers()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        result = mcp_status(ctx)
        trust_store.mcp_trust_set(
            "chimeralang",
            status="reviewed",
            risk_ceiling="medium",
            tools=[str(tool) for tool in result.get("tools", []) if str(tool).strip()],
        )
        upsert_candidate(
            console_state_dir,
            {
                "candidate_type": "mcp_capability",
                "title": "chimeralang MCP server",
                "status": "approved" if result.get("enabled") else "reviewed",
                "required_permissions": ["mcp_enable"],
                "safety_notes": ["MCP capability was enabled through the Console control."],
                "metadata": {"tool_count": result.get("tool_count", 0), "tools": result.get("tools", [])},
            },
        )
        record_timeline_event(
            console_state_dir,
            "mcp_enabled",
            {"server": "chimeralang", "enabled": bool(result.get("enabled")), "tool_count": result.get("tool_count", 0)},
        )
        return result

    def mcp_disable_chimeralang(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..chimera_pilot.mcp_wrapper import disconnect_mcp_servers

        try:
            disconnect_mcp_servers()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        trust_store.mcp_trust_set("chimeralang", status="revoked", risk_ceiling="low", tools=[])
        record_timeline_event(console_state_dir, "mcp_disabled", {"server": "chimeralang"})
        return {"ok": True, "enabled": False, "tool_count": 0, "tools": []}

    def skills_list(ctx: dict[str, Any]) -> dict[str, Any]:
        """Return all registered skills (bundled + workspace) for the Skills tab."""
        try:
            from ..skill_layer.registry import get_registry

            registry = get_registry()
            skills = [
                {
                    "name": name,
                    "domain": getattr(skill, "domain", "general"),
                    "description": getattr(skill, "description", ""),
                }
                for name, skill in registry.list_skills().items()
            ]
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "skills": []}
        return {"ok": True, "skills": skills, "count": len(skills)}

    def skills_discover(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..skill_layer.registry import get_registry

        body = _json_body(ctx)
        query = str(body.get("query") or "ghost chimera skill language:Python").strip()
        limit = max(1, min(int(body.get("limit") or 5), 20))
        install = _as_bool(body.get("install"), default=False)
        repos = [str(item).strip() for item in body.get("repos") or [] if str(item).strip()]
        candidates: list[dict[str, Any]] = []
        github = _github_client_with_console_token()

        if repos:
            for repo in repos:
                try:
                    payload = github.get_json(f"repos/{repo}")
                except Exception as exc:
                    candidates.append(
                        {"full_name": repo, "html_url": f"https://github.com/{repo}", "description": "", "error": str(exc)}
                    )
                    continue
                if isinstance(payload, dict):
                    candidates.append(
                        {
                            "full_name": str(payload.get("full_name") or repo),
                            "html_url": str(payload.get("html_url") or f"https://github.com/{repo}"),
                            "description": str(payload.get("description") or ""),
                            "language": str(payload.get("language") or ""),
                            "stars": int(payload.get("stargazers_count") or 0),
                            "default_branch": str(payload.get("default_branch") or "main"),
                        }
                    )
        else:
            params = urllib.parse.urlencode({"q": query, "per_page": str(limit)})
            try:
                payload = github.get_json(f"search/repositories?{params}")
            except Exception as exc:
                return {"ok": False, "error": str(exc), "query": query, "candidate_count": 0, "candidates": []}
            items = payload.get("items") if isinstance(payload, dict) else []
            for item in items[:limit] if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                candidates.append(
                    {
                        "full_name": str(item.get("full_name") or ""),
                        "html_url": str(item.get("html_url") or ""),
                        "description": str(item.get("description") or ""),
                        "language": str(item.get("language") or ""),
                        "stars": int(item.get("stargazers_count") or 0),
                        "default_branch": str(item.get("default_branch") or "main"),
                    }
                )

        installed: list[dict[str, Any]] = []
        if install:
            for candidate in candidates:
                if not candidate.get("full_name") or candidate.get("error"):
                    continue
                with contextlib.suppress(Exception):
                    installed.append(_write_compat_skill(candidate))
            if installed:
                get_registry(reset=True)
        for candidate in candidates:
            repo = str(candidate.get("full_name") or "").strip()
            if not repo:
                continue
            source = create_learning_source(
                console_state_dir,
                {
                    "source_type": "github_repo",
                    "label": repo,
                    "uri": str(candidate.get("html_url") or f"https://github.com/{repo}"),
                    "scope": "global",
                    "consent_status": "pending",
                    "risk_level": "medium",
                    "provenance": {
                        "language": candidate.get("language", ""),
                        "stars": candidate.get("stars", 0),
                        "default_branch": candidate.get("default_branch", ""),
                    },
                },
            )
            upsert_candidate(
                console_state_dir,
                {
                    "candidate_type": "skill_scaffold",
                    "title": repo,
                    "source_id": source["id"],
                    "status": "approved" if install else "reviewed",
                    "required_permissions": ["skill_review", "local_skill_write"] if install else ["skill_review"],
                    "safety_notes": ["Compatibility skill stays reviewable through Self-Evolution."],
                    "metadata": candidate,
                },
            )
        record_timeline_event(
            console_state_dir,
            "skill_candidate_reviewed",
            {"query": query, "candidate_count": len(candidates), "installed_count": len(installed)},
        )
        return {
            "ok": True,
            "query": query,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "installed_count": len(installed),
            "installed": installed,
            "skills_dir": str(_workspace_skills_dir()),
        }

    def _superiority_payload(summary: dict[str, Any]) -> dict[str, Any]:
        static_dir = Path(__file__).resolve().parent / "static"
        html_text = ""
        app_text = ""
        with contextlib.suppress(OSError):
            html_text = (static_dir / "index.html").read_text(encoding="utf-8")
        with contextlib.suppress(OSError):
            app_text = (static_dir / "app.js").read_text(encoding="utf-8")
        capability_payload = inspect_capabilities(Path(__file__).resolve().parents[2])
        routes = [str(route.get("path") or "") for route in server.routes.list_all()]
        return build_superiority_scorecard(
            operator_summary=summary,
            capabilities=capability_payload,
            routes=routes,
            static_html=html_text,
            static_app=app_text,
        ).to_dict()

    def _operator_summary_payload(*, include_superiority: bool = True) -> dict[str, Any]:
        from ..personalization.path_state import get_active_ghost_path

        config = _load_console_config(console_config_file)
        active_path = get_active_ghost_path(config_path=path_config_file)
        rag_payload: dict[str, Any] = {"enabled": False}
        with contextlib.suppress(Exception):
            rag_payload = personal_minimind().status()
        mcp_payload: dict[str, Any] = {"enabled": False}
        with contextlib.suppress(Exception):
            mcp_payload = mcp_status({"method": "GET", "path": "/api/console/mcp/status", "headers": {}, "body": "", "query": {}})
        sources = list_sources(console_state_dir)
        candidates = list_candidates(console_state_dir)
        latency_payload = latency_summary(console_state_dir, limit=200)
        summary = readiness_summary(
            config=config,
            active_path=active_path,
            rag_status=rag_payload,
            mcp_status=mcp_payload,
            sources=sources,
            candidates=candidates,
            latency=latency_payload,
        )
        remote_payload = remote_store.status()
        trust_payload = trust_store.trust_status()
        admission_payload = admission_store.summary()
        conversation_payload = conversation_controller.status()
        combined_warnings = list(summary.get("warnings") or [])
        combined_warnings.extend(str(item) for item in trust_payload.get("warnings", []) if str(item).strip())
        combined_warnings.extend(str(item) for item in admission_payload.get("warnings", []) if str(item).strip())
        summary["warnings"] = list(dict.fromkeys(combined_warnings))
        production_ready = bool(trust_payload.get("ready")) and bool(admission_payload.get("production_ready"))
        summary["production_readiness"] = {
            "ready": production_ready,
            "status": "ready" if production_ready and not summary["warnings"] else "review",
            "trust": trust_payload.get("production_readiness", {}),
            "capability_admission": {
                "production_ready": admission_payload.get("production_ready", False),
                "counts": admission_payload.get("counts", {}),
            },
        }
        if isinstance(summary.get("cards"), list):
            summary["cards"].append(
                {
                    "id": "conversation",
                    "label": "Conversation",
                    "status": (
                        "bypass"
                        if conversation_payload.get("settings", {}).get("full_bypass")
                        else str((conversation_payload.get("active_session") or {}).get("mode") or "ready")
                    ),
                    "action": "operator",
                }
            )
            summary["cards"].append(
                {
                    "id": "remote",
                    "label": "Remote Control",
                    "status": "paired" if remote_payload.get("counts", {}).get("paired_peers") else "setup",
                    "action": "remote",
                }
            )
            summary["cards"].append(
                {
                    "id": "trust-runtime",
                    "label": "Trust Runtime",
                    "status": trust_payload.get("production_readiness", {}).get("status", "review"),
                    "action": "trust",
                }
            )
            summary["cards"].append(
                {
                    "id": "capability-admission",
                    "label": "Capability Admission",
                    "status": "ready" if admission_payload.get("production_ready") else "review",
                    "action": "trust",
                }
            )
        summary.update(
            {
                "active_path": active_path,
                "model": _safe_config_payload(config, console_config_file)["model"],
                "rag": rag_payload,
                "mcp": mcp_payload,
                "latency": latency_payload,
                "evolution": {
                    "sources": sources,
                    "candidates": candidates,
                    "advisory_only": True,
                    "automatic_promotion_enabled": False,
                },
                "remote": {
                    "counts": remote_payload.get("counts", {}),
                    "policy": remote_payload.get("policy", {}),
                },
                "trust": trust_payload,
                "capability_admission": admission_payload,
                "conversation": conversation_payload,
            }
        )
        if include_superiority:
            superiority = _superiority_payload(summary)
            summary["superiority"] = superiority
            summary["next_best_actions"] = superiority.get("next_best_actions", [])
        return summary

    def operator_summary(ctx: dict[str, Any]) -> dict[str, Any]:
        return _operator_summary_payload()

    def superiority_scorecard(ctx: dict[str, Any]) -> dict[str, Any]:
        summary = _operator_summary_payload(include_superiority=False)
        payload = _superiority_payload(summary)
        record_timeline_event(
            console_state_dir,
            "superiority_scorecard_viewed",
            {"score_ratio": payload.get("score_ratio")},
        )
        return payload

    def operator_timeline(ctx: dict[str, Any]) -> dict[str, Any]:
        query = ctx.get("query") or {}
        try:
            limit = int(query.get("limit") or 50)
        except (TypeError, ValueError):
            limit = 50
        return {"ok": True, "events": read_timeline(console_state_dir, limit=limit)}

    def operator_latency(ctx: dict[str, Any]) -> dict[str, Any]:
        query = ctx.get("query") or {}
        try:
            limit = int(query.get("limit") or 200)
        except (TypeError, ValueError):
            limit = 200
        return latency_summary(console_state_dir, limit=limit)

    def operator_readiness(ctx: dict[str, Any]) -> dict[str, Any]:
        summary = _operator_summary_payload()
        record_timeline_event(
            console_state_dir,
            "readiness_check_run",
            {"warning_count": len(summary.get("warnings") or []), "counts": summary.get("counts", {})},
        )
        return summary

    def operator_setup_step(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        step = str(body.get("step") or "").strip().lower()
        allowed = {
            "choose_path",
            "configure_model",
            "confirm_minimind",
            "select_learning_sources",
            "generate_rag_plan",
            "review_mcp",
            "review_skills",
            "run_readiness",
        }
        if step not in allowed:
            return {"ok": False, "error": "Unsupported setup step.", "allowed_steps": sorted(allowed)}
        record_timeline_event(console_state_dir, "setup_step_completed", {"step": step})
        return {"ok": True, "step": step, "summary": _operator_summary_payload()}

    def _record_remote_trust_run(command_payload: dict[str, Any], *, channel: str, peer_id: str, text: str) -> None:
        command = str(command_payload.get("command") or "").strip()
        if command not in {"run", "/run"}:
            return
        objective = str(command_payload.get("objective") or text.removeprefix("/run").strip()).strip()
        approval_payload = command_payload.get("approval") if isinstance(command_payload.get("approval"), dict) else {}
        trust_run = trust_store.create_run(
            agent_name="ghost_remote_control",
            objective=objective,
            source=f"remote:{channel}",
            metadata={
                "peer_id": peer_id,
                "command": command,
                "mode": command_payload.get("mode", ""),
                "approval_id": command_payload.get("approval_id", "") or approval_payload.get("id", ""),
            },
        )
        trust_store.record_step(
            trust_run["run_id"],
            step_type="goal_intake",
            status="completed",
            inputs={"objective": objective, "channel": channel, "peer_id": peer_id},
            idempotency_key=f"{trust_run['run_id']}:remote-goal-intake",
        )
        if command_payload.get("mode") == "approval_required":
            checkpoint = trust_store.create_approval(
                trust_run["run_id"],
                step_id=str(command_payload.get("approval_id") or approval_payload.get("id") or "remote-run-approval"),
                reason="Remote /run command requires operator approval before execution.",
                requested_by=peer_id or channel,
                metadata={
                    "remote_approval_id": command_payload.get("approval_id", "") or approval_payload.get("id", ""),
                    "channel": channel,
                },
            )
            command_payload["trust_approval"] = checkpoint
        else:
            trust_store.record_step(
                trust_run["run_id"],
                step_type="approval_boundary",
                status="completed",
                outputs={"mode": command_payload.get("mode", ""), "direct_execution": True},
                idempotency_key=f"{trust_run['run_id']}:approval-boundary",
            )
        command_payload["trust_run"] = trust_store.get_run(trust_run["run_id"])

    def trust_summary(ctx: dict[str, Any]) -> dict[str, Any]:
        return trust_store.trust_status()

    def trust_runs(ctx: dict[str, Any]) -> dict[str, Any]:
        return trust_store.list_runs()

    def trust_run_detail(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/trust/runs/")
        parts = [part for part in suffix.split("/") if part]
        if not parts:
            return {"ok": False, "error": "Run id is required."}
        run_id = parts[0]
        if len(parts) == 2 and parts[1] == "resume":
            payload = trust_store.resume_run(run_id)
            if payload.get("ok"):
                record_timeline_event(console_state_dir, "trust_run_resumed", {"run_id": run_id})
            return payload
        if len(parts) != 1:
            return {"ok": False, "error": "Expected /api/console/trust/runs/{id} or /resume."}
        return trust_store.get_run(run_id)

    def trust_approvals(ctx: dict[str, Any]) -> dict[str, Any]:
        return trust_store.pending_approvals()

    def trust_approval_action(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/trust/approvals/")
        parts = [part for part in suffix.split("/") if part]
        if len(parts) != 2 or parts[1] not in {"approve", "deny"}:
            return {"ok": False, "error": "Expected /api/console/trust/approvals/{id}/approve or /deny."}
        status_value = "approved" if parts[1] == "approve" else "denied"
        payload = trust_store.resolve_approval(parts[0], status_value, reviewer="console")
        if payload.get("ok"):
            record_timeline_event(
                console_state_dir,
                "trust_approval_resolved",
                {"approval_id": parts[0], "status": status_value},
            )
        return payload

    def trust_trace_export(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/trust/traces/")
        run_id = suffix.removesuffix("/export").strip("/")
        if run_id == "latest":
            runs = trust_store.list_runs(limit=1).get("runs", [])
            if not runs:
                return {"ok": False, "error": "No trust runs available."}
            run_id = str(runs[0].get("run_id") or "")
        if not run_id:
            return {"ok": False, "error": "Run id is required."}
        return trust_store.export_trace(run_id)

    def trust_run_replay(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/trust/replay/")
        run_id = suffix.strip("/")
        if not run_id:
            return {"ok": False, "error": "Run id is required."}
        body = _json_body(ctx)
        disabled_tools = [str(item) for item in (body.get("disabled_tools") or []) if str(item).strip()]
        payload = trust_store.simulate_replay(
            run_id,
            mode=str(body.get("mode") or "same_policy"),
            model_provider=str(body.get("model_provider") or ""),
            disabled_tools=disabled_tools,
            stricter_policy=_as_bool(body.get("stricter_policy"), default=False),
        )
        if payload.get("ok"):
            record_timeline_event(
                console_state_dir,
                "trust_run_replay_previewed",
                {
                    "run_id": run_id,
                    "mode": payload.get("simulation", {}).get("mode"),
                    "projected_status": payload.get("simulation", {}).get("projected_status"),
                },
            )
        return payload

    def trust_evals(ctx: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "baseline": trust_store.trust_status().get("eval_baseline", {}), "comparison": trust_store.eval_compare()}

    def trust_eval_baseline(ctx: dict[str, Any]) -> dict[str, Any]:
        payload = trust_store.eval_baseline()
        record_timeline_event(
            console_state_dir,
            "trust_eval_baseline_created",
            {"trust_score": payload.get("trust_score"), "case_count": payload.get("case_count")},
        )
        return payload

    def trust_eval_cases(ctx: dict[str, Any]) -> dict[str, Any]:
        query = ctx.get("query") or {}
        try:
            limit = int(query.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        return trust_store.list_eval_cases(limit=limit)

    def trust_eval_case_promote(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        run_id = str(body.get("run_id") or "").strip()
        if not run_id:
            return {"ok": False, "error": "run_id is required."}
        payload = trust_store.promote_run_to_eval_case(
            run_id,
            label=str(body.get("label") or "").strip(),
            severity=str(body.get("severity") or "P2").strip().upper(),
        )
        if payload.get("ok"):
            record_timeline_event(
                console_state_dir,
                "trust_eval_case_promoted",
                {"run_id": run_id, "case_id": payload.get("case", {}).get("case_id"), "severity": payload.get("case", {}).get("severity")},
            )
        return payload

    def capability_admission_route(ctx: dict[str, Any]) -> dict[str, Any]:
        if ctx.get("method") == "GET":
            query = ctx.get("query") or {}
            payload = admission_store.list_records(
                status=str(query.get("status") or ""),
                capability_kind=str(query.get("kind") or query.get("capability_kind") or ""),
            )
            payload["summary"] = admission_store.summary()
            return payload
        body = _json_body(ctx)
        try:
            payload = admission_store.register_or_update(
                capability_kind=str(body.get("capability_kind") or body.get("kind") or "").strip(),
                name=str(body.get("name") or "").strip(),
                source=str(body.get("source") or "console").strip() or "console",
                risk_level=str(body.get("risk_level") or "medium"),
                risk_ceiling=str(body.get("risk_ceiling") or body.get("risk_level") or "medium"),
                requested_permissions=[str(item) for item in (body.get("requested_permissions") or body.get("permissions") or []) if str(item).strip()],
                metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
                inspection={"inspected_by": "console", "created_from": "dashboard"},
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        record_timeline_event(
            console_state_dir,
            "capability_admission_recorded",
            {
                "id": payload.get("record", {}).get("id"),
                "kind": payload.get("record", {}).get("capability_kind"),
                "risk_level": payload.get("record", {}).get("risk_level"),
            },
        )
        return payload

    def capability_admission_action(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/capability-admission/")
        parts = [part for part in suffix.split("/") if part]
        action_map = {
            "inspect": "inspected",
            "review": "review_required",
            "approve": "approved",
            "activate": "active",
            "revoke": "revoked",
            "quarantine": "quarantined",
        }
        if len(parts) != 2 or parts[1] not in action_map:
            return {"ok": False, "error": "Expected /api/console/capability-admission/{id}/{inspect|review|approve|activate|revoke|quarantine}."}
        body = _json_body(ctx)
        payload = admission_store.transition(
            parts[0],
            action_map[parts[1]],
            reviewer=str(body.get("reviewer") or "console"),
            reason=str(body.get("reason") or ""),
        )
        if payload.get("ok"):
            record_timeline_event(
                console_state_dir,
                "capability_admission_transitioned",
                {"id": parts[0], "status": action_map[parts[1]], "action": parts[1]},
            )
        return payload

    def mcp_trust_registry(ctx: dict[str, Any]) -> dict[str, Any]:
        return trust_store.mcp_trust_list()

    def mcp_trust_action(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/mcp/trust/")
        parts = [part for part in suffix.split("/") if part]
        if len(parts) != 2 or parts[1] not in {"approve", "revoke"}:
            return {"ok": False, "error": "Expected /api/console/mcp/trust/{server_id}/approve or /revoke."}
        body = _json_body(ctx)
        status_value = "approved" if parts[1] == "approve" else "revoked"
        payload = trust_store.mcp_trust_set(
            parts[0],
            status=status_value,
            risk_ceiling=str(body.get("risk_ceiling") or "medium"),
            tools=[str(tool) for tool in (body.get("tools") or []) if str(tool).strip()],
        )
        admission = admission_store.register_or_update(
            capability_kind="mcp",
            name=parts[0],
            source="mcp_trust_registry",
            risk_level=str(body.get("risk_ceiling") or "medium"),
            risk_ceiling=str(body.get("risk_ceiling") or "medium"),
            requested_permissions=[str(tool) for tool in (body.get("tools") or ["mcp_tool_execution"]) if str(tool).strip()],
            metadata={"server_id": parts[0], "mcp_status": status_value},
            inspection={"trust_action": parts[1], "runtime_registry_status": status_value},
        )
        admission_record = admission.get("record") if admission.get("ok") else {}
        if isinstance(admission_record, dict) and admission_record.get("id"):
            if status_value == "approved":
                admission_record = _move_admission_to_active(admission_record, reason="MCP trust approval from Console.")
            elif str(admission_record.get("status") or "") not in {"revoked", "quarantined"}:
                revoked = admission_store.transition(
                    str(admission_record.get("id")),
                    "revoked",
                    reviewer="console",
                    reason="MCP trust revoked from Console.",
                )
                if revoked.get("ok"):
                    admission_record = revoked["record"]
        payload["admission_record"] = admission_record
        record_timeline_event(
            console_state_dir,
            "mcp_trust_updated",
            {
                "server_id": parts[0],
                "status": status_value,
                "risk_ceiling": payload.get("server", {}).get("risk_ceiling"),
                "admission_record": admission_record.get("id") if isinstance(admission_record, dict) else "",
            },
        )
        return payload

    def remote_status(ctx: dict[str, Any]) -> dict[str, Any]:
        return remote_store.status()

    def remote_policy(ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = remote_store.update_policy(_json_body(ctx))
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        record_timeline_event(
            console_state_dir,
            "remote_policy_updated",
            {"direct_execution_enabled": payload.get("policy", {}).get("direct_execution_enabled")},
        )
        return payload

    def remote_pairing_create(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        try:
            payload = remote_store.create_pairing(
                channel=str(body.get("channel") or "webhook"),
                peer_id=str(body.get("peer_id") or ""),
                display_name=str(body.get("display_name") or ""),
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        record_timeline_event(
            console_state_dir,
            "remote_pairing_created",
            {
                "channel": payload.get("pairing", {}).get("channel"),
                "peer_id": payload.get("pairing", {}).get("peer_id"),
            },
        )
        return payload

    def remote_pairing_approve(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        payload = remote_store.approve_pairing(
            pairing_id=str(body.get("pairing_id") or ""),
            channel=str(body.get("channel") or ""),
            peer_id=str(body.get("peer_id") or ""),
            code=str(body.get("code") or ""),
        )
        if payload.get("ok"):
            record_timeline_event(
                console_state_dir,
                "remote_peer_paired",
                {
                    "channel": payload.get("peer", {}).get("channel"),
                    "peer_id": payload.get("peer", {}).get("peer_id"),
                },
            )
        return payload

    def remote_peer_action(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/remote/peers/")
        parts = [part for part in suffix.split("/") if part]
        if len(parts) != 2 or parts[1] not in {"direct", "revoke"}:
            return {"ok": False, "error": "Expected /api/console/remote/peers/{id}/direct or /revoke"}
        body = _json_body(ctx)
        if parts[1] == "direct":
            payload = remote_store.set_peer_direct_execution(parts[0], _as_bool(body.get("allow"), default=False))
        else:
            payload = remote_store.revoke_peer(parts[0])
        if payload.get("ok"):
            record_timeline_event(
                console_state_dir,
                "remote_peer_updated",
                {"peer_id": parts[0], "action": parts[1], "allow": body.get("allow")},
            )
        return payload

    def remote_channel_config(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/remote/channels/")
        channel = suffix.split("/", 1)[0].strip().lower()
        if not channel:
            return {"ok": False, "error": "Remote channel is required."}
        try:
            payload = remote_store.configure_channel(channel, _json_body(ctx))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if payload.get("ok"):
            record_timeline_event(
                console_state_dir,
                "remote_channel_configured",
                {
                    "channel": channel,
                    "configured": payload.get("channel", {}).get("configured"),
                    "send_enabled": payload.get("channel", {}).get("send_enabled"),
                },
            )
        return payload

    def remote_send_test(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        channel = str(body.get("channel") or "").strip().lower()
        reply_target = str(body.get("reply_target") or body.get("peer_id") or "").strip()
        text = str(body.get("text") or "Ghost Chimera remote test reply.").strip()
        if not channel or not reply_target:
            return {"ok": False, "error": "channel and reply_target are required."}
        payload = remote_store.send_reply(channel=channel, reply_target=reply_target, text=text)
        record_timeline_event(
            console_state_dir,
            "remote_test_reply_sent",
            {"channel": channel, "reply_target": reply_target, "ok": bool(payload.get("ok"))},
        )
        return payload

    def remote_inbound(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)

        def paths_provider() -> dict[str, Any]:
            from ..personalization.path_state import get_active_ghost_path
            from ..personalization.role_profiles import list_role_profiles

            return {
                "ok": True,
                "active_path": get_active_ghost_path(config_path=path_config_file),
                "profiles": [profile.to_dict() for profile in list_role_profiles()],
            }

        payload = remote_store.handle_inbound(
            channel=str(body.get("channel") or "webhook"),
            peer_id=str(body.get("peer_id") or ""),
            display_name=str(body.get("display_name") or ""),
            text=str(body.get("text") or ""),
            objective_runner=objective_runner,
            status_provider=_operator_summary_payload,
            paths_provider=paths_provider,
            jobs_provider=lambda: {"ok": True, "available_jobs": queue.available_jobs(), "history": queue.list_jobs()},
        )
        _record_remote_trust_run(
            payload,
            channel=str(body.get("channel") or "webhook"),
            peer_id=str(body.get("peer_id") or ""),
            text=str(body.get("text") or ""),
        )
        record_timeline_event(
            console_state_dir,
            "remote_command_received",
            {
                "channel": body.get("channel") or "webhook",
                "peer_id": body.get("peer_id") or "",
                "command": payload.get("command", ""),
                "mode": payload.get("mode", ""),
                "ok": bool(payload.get("ok")),
            },
        )
        return payload

    def remote_provider_webhook(ctx: dict[str, Any]) -> dict[str, Any]:
        channel = _suffix(ctx, "/api/console/remote/webhook/")
        raw_body = str(ctx.get("body") or "")
        signature = verify_remote_webhook_signature(remote_store, channel, dict(ctx.get("headers") or {}), raw_body)
        if not signature.get("ok"):
            record_timeline_event(
                console_state_dir,
                "remote_provider_webhook_rejected",
                {"channel": channel, "signature_status": signature.get("signature_status", ""), "ok": False},
            )
            return signature
        body = _json_body(ctx)
        try:
            inbound = normalize_remote_payload(channel, body)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        payload = remote_store.handle_inbound(
            channel=inbound.channel,
            peer_id=inbound.peer_id,
            display_name=inbound.display_name,
            text=inbound.text,
            objective_runner=objective_runner,
            status_provider=_operator_summary_payload,
            paths_provider=lambda: {"ok": True, "active_path": _operator_summary_payload().get("active_path", {})},
            jobs_provider=lambda: {"ok": True, "available_jobs": queue.available_jobs(), "history": queue.list_jobs()},
        )
        _record_remote_trust_run(payload, channel=inbound.channel, peer_id=inbound.peer_id, text=inbound.text)
        payload["signature_status"] = signature.get("signature_status", "")
        payload["normalized"] = inbound.to_dict()
        record_timeline_event(
            console_state_dir,
            "remote_provider_webhook_received",
            {
                "channel": inbound.channel,
                "peer_id": inbound.peer_id,
                "shape": inbound.raw_shape,
                "command": payload.get("command", ""),
                "mode": payload.get("mode", ""),
                "ok": bool(payload.get("ok")),
            },
        )
        return payload

    def remote_approval_action(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/remote/approvals/")
        parts = [part for part in suffix.split("/") if part]
        if len(parts) != 2 or parts[1] not in {"approve", "deny"}:
            return {"ok": False, "error": "Expected /api/console/remote/approvals/{id}/approve or /deny"}
        payload = remote_store.resolve_approval(parts[0], approved=parts[1] == "approve", objective_runner=objective_runner)
        if payload.get("ok"):
            record_timeline_event(
                console_state_dir,
                "remote_approval_resolved",
                {"approval_id": parts[0], "action": parts[1], "ok": bool(payload.get("ok"))},
            )
        return payload

    def evolution_sources_route(ctx: dict[str, Any]) -> dict[str, Any]:
        if ctx.get("method") == "GET":
            return {"ok": True, "sources": list_sources(console_state_dir)}
        try:
            source = create_learning_source(console_state_dir, _json_body(ctx))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        record_timeline_event(
            console_state_dir,
            "learning_source_added",
            {"source_id": source["id"], "source_type": source["source_type"], "consent_status": source["consent_status"]},
        )
        return {"ok": True, "source": source, "sources": list_sources(console_state_dir)}

    def evolution_source_action(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/evolution/sources/")
        parts = [part for part in suffix.split("/") if part]
        if len(parts) != 2 or parts[1] not in {"approve", "revoke"}:
            return {"ok": False, "error": "Expected /api/console/evolution/sources/{id}/approve or /revoke"}
        source_id, action = parts
        try:
            source = set_source_consent(console_state_dir, source_id, "approved" if action == "approve" else "revoked")
        except KeyError:
            return {"ok": False, "error": "Learning source not found."}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        record_timeline_event(
            console_state_dir,
            "learning_source_approved" if action == "approve" else "learning_source_revoked",
            {"source_id": source_id, "source_type": source.get("source_type")},
        )
        return {"ok": True, "source": source, "sources": list_sources(console_state_dir)}

    def evolution_candidates_route(ctx: dict[str, Any]) -> dict[str, Any]:
        if ctx.get("method") == "GET":
            return {"ok": True, "candidates": list_candidates(console_state_dir)}
        try:
            candidate = upsert_candidate(console_state_dir, _json_body(ctx))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        record_timeline_event(
            console_state_dir,
            "evolution_candidate_added",
            {"candidate_id": candidate["id"], "candidate_type": candidate["candidate_type"], "status": candidate["status"]},
        )
        return {"ok": True, "candidate": candidate, "candidates": list_candidates(console_state_dir)}

    def evolution_candidate_action(ctx: dict[str, Any]) -> dict[str, Any]:
        suffix = _suffix(ctx, "/api/console/evolution/candidates/")
        parts = [part for part in suffix.split("/") if part]
        allowed = {"review": "reviewed", "promote": "promoted", "reject": "rejected"}
        if len(parts) != 2 or parts[1] not in allowed:
            return {"ok": False, "error": "Expected /api/console/evolution/candidates/{id}/review, /promote, or /reject"}
        body = _json_body(ctx)
        if parts[1] == "promote":
            candidate_for_gate = _find_evolution_candidate(parts[0])
            if not isinstance(candidate_for_gate, dict):
                return {"ok": False, "error": "Evolution candidate not found."}
            admission = _admission_gate(
                capability_kind=str(candidate_for_gate.get("candidate_type") or "self_evolution_candidate"),
                name=str(candidate_for_gate.get("title") or parts[0]),
                source=str(candidate_for_gate.get("source_id") or "self-evolution"),
                risk_level=str(candidate_for_gate.get("risk_level") or "medium"),
                risk_ceiling=str(candidate_for_gate.get("risk_ceiling") or "medium"),
                requested_permissions=[
                    str(item)
                    for item in (candidate_for_gate.get("required_permissions") or ["self_evolution_promotion"])
                    if str(item).strip()
                ],
                metadata=candidate_for_gate.get("metadata") if isinstance(candidate_for_gate.get("metadata"), dict) else {},
                inspection={"candidate_id": parts[0], "status": candidate_for_gate.get("status")},
                reason="Self-Evolution promotion requires active capability admission.",
            )
            if not admission.get("ok"):
                return {
                    "ok": False,
                    "admission_required": True,
                    "error": admission.get("error"),
                    "admission_record": admission.get("record"),
                    "candidate": candidate_for_gate,
                    "candidates": list_candidates(console_state_dir),
                }
        try:
            candidate = set_candidate_status(
                console_state_dir,
                parts[0],
                allowed[parts[1]],
                notes=str(body.get("notes") or ""),
            )
        except KeyError:
            return {"ok": False, "error": "Evolution candidate not found."}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        record_timeline_event(
            console_state_dir,
            f"candidate_{allowed[parts[1]]}",
            {"candidate_id": candidate["id"], "candidate_type": candidate.get("candidate_type")},
        )
        return {"ok": True, "candidate": candidate, "candidates": list_candidates(console_state_dir)}

    def capability_pack_list(ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "policy": {
                "external_mcp_required": False,
                "preview_first": True,
                "secrets_are_write_only": True,
            },
            "tools": [tool.to_dict() for tool in list_capability_tools()],
        }

    def capability_pack_run(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        tool_id = str(body.get("tool_id") or "").strip()
        arguments = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
        payload = call_capability_tool(tool_id, arguments)
        record_timeline_event(
            console_state_dir,
            "capability_pack_tool_run",
            {"tool_id": tool_id, "ok": bool(payload.get("ok"))},
        )
        return payload

    def local_models_inventory(ctx: dict[str, Any]) -> dict[str, Any]:
        query = ctx.get("query") or {}
        roots_raw = query.get("root") or []
        roots = roots_raw if isinstance(roots_raw, list) else ([roots_raw] if roots_raw else None)
        payload = discover_local_model_inventory(roots)
        record_timeline_event(
            console_state_dir,
            "local_model_inventory_previewed",
            {"count": payload.get("count", 0), "preview_only": True},
        )
        return payload

    def local_models_resolve(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        source = str(body.get("source") or "").strip()
        if not source:
            return {"ok": False, "error": "source is required"}
        candidate = resolve_model_source(source, license_id=str(body.get("license_id") or ""))
        record_timeline_event(
            console_state_dir,
            "local_model_source_resolved",
            {"source_type": candidate.source_type, "status": candidate.compatibility_status},
        )
        return {
            "ok": True,
            "model": candidate.to_dict(),
            "policy": {"activation": "preview_only", "requires_user_approval": True},
        }

    def cognition_trace(ctx: dict[str, Any]) -> dict[str, Any]:
        query = ctx.get("query") or {}
        goal = str(query.get("goal") or "operator request")
        return summarize_operational_trace(
            goal=goal,
            sources=["config", "memory", "model catalog"],
            policy_decision="approval_required",
            tool_candidates=["capability_pack", "mcp", "local_model"],
        )

    def cognition_guard(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        belief = GhostBelief.from_confidence(
            str(body.get("value") or "candidate"),
            float(body.get("confidence") or 0.0),
            variance=float(body.get("variance") or 0.0),
            source=str(body.get("source") or "console"),
        )
        result = guard_belief(
            belief,
            max_risk=float(body.get("max_risk") or 0.2),
            max_variance=float(body.get("max_variance") or 0.05),
        )
        return {"ok": True, "belief": belief.to_dict(), "guard": result.to_dict()}

    def context_efficiency(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx) if ctx.get("method") == "POST" else {}
        result = compress_text_query_aware(
            str(body.get("text") or ""),
            focus=str(body.get("focus") or ""),
            budget_tokens=int(body.get("budget_tokens") or 800),
        )
        return result.to_dict()

    def sandbox_journey(ctx: dict[str, Any]) -> dict[str, Any]:
        report = run_sandbox_journey(state_dir=console_state_dir)
        record_timeline_event(
            console_state_dir,
            "sandbox_journey_run",
            {"steps": len(report.steps), "findings": len(report.findings)},
        )
        return report.to_dict()

    def jobs_list(ctx: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "available_jobs": queue.available_jobs(), "history": queue.list_jobs()}

    def jobs_create(ctx: dict[str, Any]) -> dict[str, Any]:
        body = _json_body(ctx)
        job_name = str(body.get("job") or body.get("name") or "").strip()
        profile = str(body.get("profile") or _status_payload(server)["autonomy"]["resolved_profile"]["name"])
        execute = _as_bool(body.get("execute"), default=False)
        run_now = _as_bool(body.get("run_now"), default=True)
        if not job_name:
            return {"ok": False, "error": "Missing autonomy job name"}
        try:
            record = queue.enqueue(job_name, profile=profile, execute=execute, run_now=run_now)
        except PermissionError as exc:
            return {"ok": False, "error": str(exc), "type": "policy"}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "type": "runtime"}
        return {"ok": record.get("status") != "error", "job": record}

    def jobs_detail(ctx: dict[str, Any]) -> dict[str, Any]:
        prefix = "/api/console/autonomy/jobs/"
        suffix = _suffix(ctx, prefix)
        if suffix.endswith("/cancel"):
            return jobs_cancel(ctx)
        job_id = suffix
        try:
            return {"ok": True, "job": queue.get(job_id)}
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}

    def jobs_cancel(ctx: dict[str, Any]) -> dict[str, Any]:
        prefix = "/api/console/autonomy/jobs/"
        job_id = _suffix(ctx, prefix).removesuffix("/cancel").strip("/")
        try:
            return {"ok": True, "job": queue.cancel(job_id)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def schedules_list(ctx: dict[str, Any]) -> dict[str, Any]:
        if scheduler is None:
            return {"ok": False, "error": scheduler_error or "Cron scheduler unavailable", "schedules": []}
        status_payload = scheduler.status()
        return {
            "ok": True,
            "running": status_payload.get("running", False),
            "job_count": status_payload.get("job_count", 0),
            "enabled_count": status_payload.get("enabled_count", 0),
            "schedules": status_payload.get("jobs", []),
        }

    def schedules_create(ctx: dict[str, Any]) -> dict[str, Any]:
        if scheduler is None:
            return {"ok": False, "error": scheduler_error or "Cron scheduler unavailable"}
        body = _json_body(ctx)
        name = str(body.get("name") or "").strip()
        cron_expression = str(body.get("cron_expression") or body.get("cron") or "").strip()
        job_name = str(body.get("job") or body.get("autonomy_job") or "").strip().lower().replace("_", "-")
        profile = str(body.get("profile") or _status_payload(server)["autonomy"]["resolved_profile"]["name"])
        execute = _as_bool(body.get("execute"), default=False)
        enabled = _as_bool(body.get("enabled"), default=True)
        if not name:
            return {"ok": False, "error": "Missing schedule name"}
        if not cron_expression:
            return {"ok": False, "error": "Missing cron_expression"}
        if job_name not in JOB_SPECS:
            return {"ok": False, "error": f"Unknown autonomy job '{job_name}'"}
        spec = JOB_SPECS[job_name]
        if not spec.background_capable:
            return {"ok": False, "error": f"Autonomy job '{job_name}' is not background-capable"}
        try:
            queue.validate_request(job_name, profile=profile, execute=execute)
        except PermissionError as exc:
            return {"ok": False, "error": str(exc), "type": "policy"}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "type": "runtime"}
        schedule = scheduler.add_job(
            name=name,
            cron_expression=cron_expression,
            objective=f"autonomy job: {job_name}",
            enabled=enabled,
            metadata={"autonomy_job": job_name, "profile": profile, "execute": execute},
        )
        return {"ok": True, "schedule": schedule.to_dict()}

    def schedules_action(ctx: dict[str, Any]) -> dict[str, Any]:
        if scheduler is None:
            return {"ok": False, "error": scheduler_error or "Cron scheduler unavailable"}
        prefix = "/api/console/autonomy/schedules/"
        parts = [part for part in _suffix(ctx, prefix).split("/") if part]
        if len(parts) != 2:
            return {"ok": False, "error": "Expected /api/console/autonomy/schedules/{id}/{action}"}
        schedule_id, action = parts
        if schedule_id not in scheduler.jobs:
            return {"ok": False, "error": f"Unknown schedule '{schedule_id}'"}
        if action == "enable":
            return {"ok": scheduler.enable_job(schedule_id), "schedule": scheduler.jobs[schedule_id].to_dict()}
        if action == "disable":
            return {"ok": scheduler.disable_job(schedule_id), "schedule": scheduler.jobs[schedule_id].to_dict()}
        if action == "delete":
            return {"ok": scheduler.remove_job(schedule_id)}
        if action == "run-now":
            schedule = scheduler.jobs[schedule_id]
            metadata = schedule.metadata
            try:
                record = queue.enqueue(
                    str(metadata.get("autonomy_job") or ""),
                    profile=str(metadata.get("profile") or "supervised"),
                    execute=_as_bool(metadata.get("execute"), default=False),
                    source="schedule",
                    schedule_id=schedule.id,
                )
            except PermissionError as exc:
                return {"ok": False, "error": str(exc), "type": "policy"}
            except Exception as exc:
                return {"ok": False, "error": str(exc), "type": "runtime"}
            return {
                "ok": record.get("status") not in {"error", "cancelled"},
                "result": {
                    "schedule_id": schedule.id,
                    "schedule_name": schedule.name,
                    "success": record.get("status") not in {"error", "cancelled"},
                    "error": record.get("error"),
                },
                "job": record,
                "error": record.get("error"),
            }
        return {"ok": False, "error": f"Unknown schedule action '{action}'"}

    server.routes.register("/", console_page, method="GET", auth="open", description="Ghost Console browser UI")
    server.routes.register("/console", console_page, method="GET", auth="open", description="Ghost Console browser UI")
    # Token-metadata endpoint is always open — it only reports whether auth is enabled, never the token itself.
    server.routes.register(
        "/api/console/token",
        lambda ctx: {"auth_enabled": bool(console_token)},
        method="GET",
        auth="open",
        description="Console auth capability advertisement",
    )
    _api_register("/api/console/status", status, method="GET", description="Ghost Console status")
    _api_register("/api/console/operator/summary", operator_summary, method="GET", description="Operator home summary")
    _api_register(
        "/api/console/superiority",
        superiority_scorecard,
        method="GET",
        description="Measured public superiority scorecard",
    )
    _api_register("/api/console/operator/timeline", operator_timeline, method="GET", description="Operator activity timeline")
    _api_register("/api/console/operator/latency", operator_latency, method="GET", description="Operator latency telemetry")
    _api_register("/api/console/operator/readiness", operator_readiness, method="POST", description="Run operator readiness check")
    _api_register("/api/console/operator/setup-step", operator_setup_step, method="POST", description="Record guided setup step")
    _api_register(
        "/api/console/conversation/sessions",
        conversation_sessions,
        method="GET",
        description="List Ghost conversation sessions",
    )
    _api_register(
        "/api/console/conversation/sessions",
        conversation_sessions,
        method="POST",
        description="Create a Ghost conversation session",
    )
    _api_register(
        "/api/console/conversation/sessions/",
        conversation_session_action,
        method="GET",
        prefix=True,
        description="Inspect a Ghost conversation session",
    )
    _api_register(
        "/api/console/conversation/sessions/",
        conversation_session_action,
        method="POST",
        prefix=True,
        description="Send, approve, deny, or stop a Ghost conversation",
    )
    _api_register(
        "/api/console/conversation/status",
        conversation_status,
        method="GET",
        description="Inspect the always-on conversation loop",
    )
    _api_register(
        "/api/console/conversation/settings",
        conversation_settings,
        method="POST",
        description="Update conversation voice and bypass settings",
    )
    _api_register("/api/console/remote/status", remote_status, method="GET", description="Inspect remote control status")
    _api_register("/api/console/remote/policy", remote_policy, method="POST", description="Update remote control policy")
    _api_register(
        "/api/console/remote/pairing/create",
        remote_pairing_create,
        method="POST",
        description="Create a remote sender pairing code",
    )
    _api_register(
        "/api/console/remote/pairing/approve",
        remote_pairing_approve,
        method="POST",
        description="Approve a pending remote sender pairing",
    )
    _api_register(
        "/api/console/remote/peers/",
        remote_peer_action,
        method="POST",
        prefix=True,
        description="Update or revoke a paired remote sender",
    )
    _api_register(
        "/api/console/remote/channels/",
        remote_channel_config,
        method="POST",
        prefix=True,
        description="Configure write-only remote adapter credentials and send policy",
    )
    _api_register(
        "/api/console/remote/send-test",
        remote_send_test,
        method="POST",
        description="Send a gated test reply through a configured remote channel",
    )
    _api_register(
        "/api/console/remote/inbound",
        remote_inbound,
        method="POST",
        description="Process a paired mobile or messaging command",
    )
    _api_register(
        "/api/console/remote/webhook/",
        remote_provider_webhook,
        method="POST",
        prefix=True,
        description="Normalize provider-shaped webhook payloads into remote commands",
    )
    _api_register(
        "/api/console/remote/approvals/",
        remote_approval_action,
        method="POST",
        prefix=True,
        description="Approve or deny a pending remote command",
    )
    _api_register("/api/console/trust/summary", trust_summary, method="GET", description="Inspect Trust Runtime summary")
    _api_register("/api/console/trust/runs", trust_runs, method="GET", description="List durable Trust Runtime runs")
    _api_register(
        "/api/console/trust/runs/",
        trust_run_detail,
        method="GET",
        prefix=True,
        description="Inspect a durable Trust Runtime run",
    )
    _api_register(
        "/api/console/trust/runs/",
        trust_run_detail,
        method="POST",
        prefix=True,
        description="Resume a durable Trust Runtime run",
    )
    _api_register(
        "/api/console/trust/approvals",
        trust_approvals,
        method="GET",
        description="List pending Trust Runtime approvals",
    )
    _api_register(
        "/api/console/trust/approvals/",
        trust_approval_action,
        method="POST",
        prefix=True,
        description="Approve or deny a Trust Runtime checkpoint",
    )
    _api_register(
        "/api/console/trust/traces/",
        trust_trace_export,
        method="GET",
        prefix=True,
        description="Export a redacted OTel-compatible local trace bundle",
    )
    _api_register(
        "/api/console/trust/replay/",
        trust_run_replay,
        method="POST",
        prefix=True,
        description="Preview a durable run replay without executing tools or model calls",
    )
    _api_register("/api/console/trust/evals", trust_evals, method="GET", description="Inspect Trust Runtime eval status")
    _api_register(
        "/api/console/trust/evals/baseline",
        trust_eval_baseline,
        method="POST",
        description="Create a local Trust Runtime eval baseline",
    )
    _api_register(
        "/api/console/trust/eval-cases",
        trust_eval_cases,
        method="GET",
        description="List promoted Trust Runtime eval cases",
    )
    _api_register(
        "/api/console/trust/eval-cases/promote",
        trust_eval_case_promote,
        method="POST",
        description="Promote a durable run into a reusable Trust Runtime eval case",
    )
    _api_register(
        "/api/console/capability-admission",
        capability_admission_route,
        method="GET",
        description="List capability admission records",
    )
    _api_register(
        "/api/console/capability-admission",
        capability_admission_route,
        method="POST",
        description="Register a capability admission record",
    )
    _api_register(
        "/api/console/capability-admission/",
        capability_admission_action,
        method="POST",
        prefix=True,
        description="Review, approve, activate, revoke, or quarantine a capability admission record",
    )
    _api_register("/api/console/mcp/trust", mcp_trust_registry, method="GET", description="List MCP trust registry")
    _api_register(
        "/api/console/mcp/trust/",
        mcp_trust_action,
        method="POST",
        prefix=True,
        description="Approve or revoke an MCP server trust envelope",
    )
    _api_register(
        "/api/console/evolution/sources",
        evolution_sources_route,
        method="GET",
        description="List Self-Evolution learning sources",
    )
    _api_register(
        "/api/console/evolution/sources",
        evolution_sources_route,
        method="POST",
        description="Create Self-Evolution learning source",
    )
    _api_register(
        "/api/console/evolution/sources/",
        evolution_source_action,
        method="POST",
        prefix=True,
        description="Approve or revoke Self-Evolution learning source",
    )
    _api_register(
        "/api/console/evolution/candidates",
        evolution_candidates_route,
        method="GET",
        description="List Self-Evolution candidates",
    )
    _api_register(
        "/api/console/evolution/candidates",
        evolution_candidates_route,
        method="POST",
        description="Create Self-Evolution candidate",
    )
    _api_register(
        "/api/console/evolution/candidates/",
        evolution_candidate_action,
        method="POST",
        prefix=True,
        description="Review, promote, or reject Self-Evolution candidate",
    )
    _api_register(
        "/api/console/capability-pack",
        capability_pack_list,
        method="GET",
        description="List built-in Ghost-native Chimera capability tools",
    )
    _api_register(
        "/api/console/capability-pack/run",
        capability_pack_run,
        method="POST",
        description="Run a built-in Ghost-native capability tool",
    )
    _api_register(
        "/api/console/local-models/inventory",
        local_models_inventory,
        method="GET",
        description="Preview local model inventory without activation",
    )
    _api_register(
        "/api/console/local-models/resolve",
        local_models_resolve,
        method="POST",
        description="Resolve a HF or local model source without downloading",
    )
    _api_register(
        "/api/console/cognition/trace",
        cognition_trace,
        method="GET",
        description="Show safe Ghost operational trace stages",
    )
    _api_register(
        "/api/console/cognition/guard",
        cognition_guard,
        method="POST",
        description="Run confidence and variance guard preview",
    )
    _api_register(
        "/api/console/context/compress",
        context_efficiency,
        method="POST",
        description="Preview query-aware deterministic compression",
    )
    _api_register(
        "/api/console/sandbox/journey",
        sandbox_journey,
        method="GET",
        description="Run local operator sandbox journey",
    )
    _api_register("/api/console/config", dashboard_config, method="GET", description="Inspect dashboard configuration")
    _api_register("/api/console/config", dashboard_config, method="POST", description="Update dashboard configuration")
    _api_register(
        "/api/console/provider-auth",
        provider_auth_vault,
        method="GET",
        description="Inspect provider auth vault status without exposing secrets",
    )
    _api_register(
        "/api/console/provider-auth",
        provider_auth_vault,
        method="POST",
        description="Save write-only provider auth metadata",
    )
    _api_register(
        "/api/console/provider-auth/connect",
        provider_auth_connect,
        method="POST",
        description="Prepare provider-specific auth connection flow",
    )
    _api_register(
        "/api/console/provider-auth/openrouter/callback",
        provider_auth_openrouter_callback,
        method="GET",
        description="Complete OpenRouter OAuth PKCE callback",
    )
    _api_register(
        "/api/console/provider-auth/oauth/poll",
        provider_auth_oauth_poll,
        method="POST",
        description="Poll a pending provider OAuth device flow",
    )
    _api_register(
        "/api/console/models/discovery",
        model_discovery,
        method="GET",
        description="Inspect cached compatible model discovery",
    )
    _api_register(
        "/api/console/models/discovery/refresh",
        model_discovery_refresh,
        method="POST",
        description="Refresh compatible model discovery sources",
    )
    _api_register(
        "/api/console/models/discovery/select",
        model_discovery_select,
        method="POST",
        description="Select a discovered model for the dashboard config",
    )
    _api_register(
        "/api/console/models/discovery/ping",
        model_discovery_ping,
        method="POST",
        description="Run an optional model compatibility ping",
    )
    _api_register("/api/console/autonomy", autonomy, method="GET", description="Ghost Console autonomy")
    _api_register("/api/console/autonomy", autonomy, method="POST", description="Ghost Console autonomy")
    _api_register(
        "/api/console/workspace",
        operator_workspace_snapshot,
        method="GET",
        description="Inspect operator workspace state",
    )
    _api_register(
        "/api/console/workspace/evidence",
        operator_workspace_evidence,
        method="POST",
        description="Record operator workspace evidence",
    )
    _api_register(
        "/api/console/workspace/reflections",
        operator_workspace_reflection,
        method="POST",
        description="Record operator workspace reflection",
    )
    _api_register(
        "/api/console/workspace/goals",
        operator_workspace_goal,
        method="POST",
        description="Set operator workspace goal",
    )
    _api_register(
        "/api/console/workspace/sync-memory",
        operator_workspace_sync_memory,
        method="POST",
        description="Promote operator workspace records into CWR memory",
    )
    _api_register("/api/console/memory/status", memory_status, method="GET", description="Show local CWR memory status")
    _api_register(
        "/api/console/memory/ingest", memory_ingest, method="POST", description="Ingest text into local CWR memory"
    )
    _api_register(
        "/api/console/memory/ingest-email",
        memory_ingest_email,
        method="POST",
        description="Ingest email (.eml/.mbox or raw text) into personal memory",
    )
    _api_register(
        "/api/console/memory/ingest-file",
        memory_ingest_file,
        method="POST",
        description="Ingest a local file or directory into personal memory",
    )
    _api_register("/api/console/memory/search", memory_search, method="POST", description="Search local CWR memory")
    _api_register(
        "/api/console/training/status",
        training_status,
        method="GET",
        description="MiniMind training setup status and dataset record count",
    )
    _api_register(
        "/api/console/training/teach",
        training_teach,
        method="POST",
        description="Append a prompt/response pair to the personal training dataset",
    )
    _api_register(
        "/api/console/minimind/status", minimind_status, method="GET", description="Show MiniMind local runtime status"
    )
    _api_register(
        "/api/console/minimind/dataset",
        minimind_dataset,
        method="POST",
        description="Write a MiniMind JSONL dataset from prompt/response records",
    )
    _api_register(
        "/api/console/minimind/personal/status",
        minimind_personal_status,
        method="GET",
        description="Show Personal MiniMind consent, memory, dataset, and RAG readiness",
    )
    _api_register(
        "/api/console/minimind/personal/consent",
        minimind_personal_consent,
        method="POST",
        description="Grant Personal MiniMind admin/source consent",
    )
    _api_register(
        "/api/console/minimind/personal/revoke",
        minimind_personal_revoke,
        method="POST",
        description="Revoke Personal MiniMind admin/source consent",
    )
    _api_register(
        "/api/console/minimind/personal/bootstrap",
        minimind_personal_bootstrap,
        method="POST",
        description="Bootstrap Personal MiniMind from consented local sources",
    )
    _api_register(
        "/api/console/minimind/personal/handoff",
        minimind_personal_handoff,
        method="POST",
        description="Build Personal MiniMind RAG handoff for the primary model",
    )
    _api_register(
        "/api/console/minimind/personal/post-training-action",
        minimind_post_training_action,
        method="POST",
        description="Run a consent-gated post-training MiniMind workflow and stage a Self-Evolution candidate",
    )
    _api_register(
        "/api/console/email/oauth/status",
        email_oauth_status_route,
        method="GET",
        description="Inspect Gmail and Outlook OAuth email crawl status without exposing tokens",
    )
    _api_register(
        "/api/console/email/oauth/start",
        email_oauth_start_route,
        method="POST",
        description="Start Gmail or Outlook read-only OAuth device flow",
    )
    _api_register(
        "/api/console/email/oauth/browser/start",
        email_oauth_browser_start_route,
        method="POST",
        description="Start Gmail read-only browser OAuth flow with PKCE",
    )
    _api_register(
        "/api/console/email/oauth/browser/callback",
        email_oauth_browser_callback_route,
        method="GET",
        description="Complete Gmail read-only browser OAuth callback",
    )
    _api_register(
        "/api/console/email/oauth/poll",
        email_oauth_poll_route,
        method="POST",
        description="Poll Gmail or Outlook OAuth device flow and store token write-only",
    )
    _api_register(
        "/api/console/email/oauth/crawl",
        email_oauth_crawl_route,
        method="POST",
        description="Crawl bounded Gmail or Outlook messages into Personal MiniMind after consent",
    )
    _api_register("/api/console/paths", role_profiles, method="GET", description="List multi-purpose Ghost paths")
    _api_register(
        "/api/console/paths/synthesize",
        synthesize_role_path,
        method="POST",
        description="Synthesize Ghost Chimera from a selected user path",
    )
    _api_register(
        "/api/console/paths/confirm-minimind",
        confirm_path_minimind,
        method="POST",
        description="Confirm whether the selected path enables open-source MiniMind dataset intake",
    )
    _api_register(
        "/api/console/paths/active", active_role_path, method="GET", description="Show the active persisted Ghost path"
    )
    _api_register(
        "/api/console/paths/active", active_role_path, method="POST", description="Persist the active Ghost path"
    )
    _api_register(
        "/api/console/thinking",
        thinking_trace,
        method="GET",
        description="Visualize explainable Ghost Chimera reasoning/runtime signals",
    )
    _api_register(
        "/api/console/github/status", github_status, method="GET", description="Inspect GitHub integration status"
    )
    _api_register(
        "/api/console/github/device/start",
        github_device_start,
        method="POST",
        description="Start optional GitHub OAuth device sign-in for the console",
    )
    _api_register(
        "/api/console/github/device/poll",
        github_device_poll,
        method="POST",
        description="Poll optional GitHub OAuth device sign-in without returning raw tokens",
    )
    _api_register(
        "/api/console/github/logout",
        github_logout,
        method="POST",
        description="Remove the locally stored console GitHub token",
    )
    _api_register(
        "/api/console/github/self-evolution/preview",
        github_self_evolution_preview,
        method="POST",
        description="Preview guarded GitHub source intake for self-evolution",
    )
    _api_register(
        "/api/console/github/plan",
        github_plan,
        method="POST",
        description="Convert a GitHub issue into a Ghost objective",
    )
    _api_register(
        "/api/console/github/policy-simulate",
        github_policy_simulate,
        method="POST",
        description="Preview GitHub action controls",
    )
    _api_register(
        "/api/console/capabilities",
        capabilities,
        method="GET",
        description="Inspect competitive agent-orchestration capability coverage",
    )
    _api_register(
        "/api/console/review-pr", review_pr, method="POST", description="Run deterministic PR/diff review automation"
    )
    _api_register(
        "/api/console/readiness", readiness, method="GET", description="Ghost Console release readiness runbook"
    )
    _api_register(
        "/api/console/rag/builder/status",
        rag_builder_status,
        method="GET",
        description="RAG Builder status for MiniMind readiness and policy checks",
    )
    _api_register(
        "/api/console/rag/builder",
        rag_builder_plan,
        method="POST",
        description="Build a RAG plan with open-source intake and optional MiniMind bootstrap",
    )
    _api_register(
        "/api/console/mcp/status",
        mcp_status,
        method="GET",
        description="Inspect chimeralang-mcp registration and runtime tool availability",
    )
    _api_register(
        "/api/console/mcp/chimeralang/enable",
        mcp_enable_chimeralang,
        method="POST",
        description="Enable chimeralang-mcp for Ghost Console",
    )
    _api_register(
        "/api/console/mcp/chimeralang/disable",
        mcp_disable_chimeralang,
        method="POST",
        description="Disable connected MCP servers for Ghost Console",
    )
    _api_register("/api/console/skills", skills_list, method="GET", description="List registered skills")
    _api_register(
        "/api/console/skills/discover",
        skills_discover,
        method="POST",
        description="Discover GitHub skill candidates and optionally convert them to local compatibility skills",
    )
    _api_register("/api/console/autonomy/jobs", jobs_list, method="GET", description="List autonomy jobs")
    _api_register("/api/console/autonomy/jobs", jobs_create, method="POST", description="Queue autonomy job")
    _api_register(
        "/api/console/autonomy/jobs/", jobs_detail, method="GET", prefix=True, description="Inspect autonomy job record"
    )
    _api_register(
        "/api/console/autonomy/jobs/", jobs_cancel, method="POST", prefix=True, description="Cancel queued autonomy job"
    )
    _api_register(
        "/api/console/autonomy/schedules", schedules_list, method="GET", description="List autonomy schedules"
    )
    _api_register(
        "/api/console/autonomy/schedules", schedules_create, method="POST", description="Create autonomy schedule"
    )
    _api_register(
        "/api/console/autonomy/schedules/",
        schedules_action,
        method="POST",
        prefix=True,
        description="Update, run, or delete autonomy schedule",
    )
    _api_register("/api/console/run", run, method="POST", description="Run a Ghost objective")
    _api_register(
        "/api/console/browser/fetch",
        browser_fetch,
        method="POST",
        description="Fetch an HTTPS URL through the Ghost browser tool",
    )
    _api_register(
        "/api/console/browser/status",
        browser_workspace_status,
        method="GET",
        description="Inspect optional agent-browser workspace availability",
    )
    _api_register(
        "/api/console/browser/open",
        browser_open,
        method="POST",
        description="Open an HTTPS URL in the optional agent-browser workspace",
    )
    _api_register(
        "/api/console/browser/snapshot",
        browser_snapshot,
        method="POST",
        description="Capture an accessibility snapshot from the optional agent-browser workspace",
    )
    _api_register(
        "/api/console/security/events",
        _security_events_handler,
        method="GET",
        description="Security event log from DPI inspection (Lobster Trap)",
    )
    _api_register(
        "/api/console/security/summary",
        _security_summary_handler,
        method="GET",
        description="Aggregated threat statistics and risk timeline",
    )
    _api_register(
        "/api/console/security/audit",
        _security_audit_handler,
        method="GET",
        description="HMAC-chained audit log entries and chain integrity check",
    )


def _console_url(server: GatewayServer) -> str:
    http_port = server.http_port
    if server._http_server is not None:
        http_port = int(server._http_server.server_address[1])
    return f"http://{server.host}:{http_port}/"


def run_console(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    http_port: int | None = None,
    state_dir: str | Path | None = None,
    open_browser: bool = True,
    block: bool = True,
    auth_token: str = "",
) -> GatewayServer:
    """
    Start and run a GatewayServer hosting the Ghost Console UI, API routes, and optional static assets.

    Parameters:
        host (str): Hostname or IP address the gateway listens on.
        port (int): TCP port for the gateway's primary (websocket) service.
        http_port (int | None): Optional explicit HTTP port for determining the console URL; if None the server chooses its default.
        state_dir (str | Path | None): Optional directory for persistent state (overrides environment config); used for workspace, queue, and scheduler storage.
        open_browser (bool): If True, attempt to open the console URL in the user's default web browser after the server starts.
        block (bool): If True, block the current thread until interrupted; on KeyboardInterrupt the server is stopped before returning.
        auth_token (str): When non-empty, all /api/* routes require this bearer token via the X-Gateway-Token header.

    Returns:
        GatewayServer: The started gateway server instance.
    """

    _apply_saved_config_env(overwrite=False)
    config = GhostChimeraConfig.from_env()
    if state_dir:
        resolved = Path(state_dir).expanduser()
        config = replace(
            config, state_dir=resolved, memory_db=resolved / "memory.sqlite3", audit_file=resolved / "audit.json"
        )
    server = GatewayServer(host=host, port=port, http_port=http_port, config=config)
    _register_static_routes(server)
    register_console_routes(server, state_dir=state_dir or config.state_dir, console_token=auth_token or "")
    server.start()
    url = _console_url(server)
    print(f"Ghost Console: {url}")
    if auth_token:
        print(f"Auth token required — set X-Gateway-Token header: {auth_token}")
    if open_browser:
        webbrowser.open(url)
    if block:
        try:
            while True:
                time.sleep(0.25)
        except KeyboardInterrupt:
            server.stop()
    return server


_STATIC_DIR: Path | None = None


def _static_dir() -> Path:
    """
    Return the cached Path to the package's "static" directory adjacent to this file.

    This computes Path(__file__).parent / "static" on first call, caches it in module-level state, and returns the cached Path on subsequent calls.

    Returns:
        Path: Filesystem path to the "static" directory next to this module.
    """
    global _STATIC_DIR
    if _STATIC_DIR is None:
        _STATIC_DIR = Path(__file__).parent / "static"
    return _STATIC_DIR


def _register_static_routes(server: GatewayServer) -> None:
    """
    Register HTTP routes that serve packaged static console assets.

    If a "static" directory exists next to this module, this function registers GET routes for any of the files index.html, app.js, and styles.css that are present. index.html is exposed at "/" and "/console"; each asset is exposed at "/static/<filename>" with an appropriate Content-Type header. If the static directory is missing, the function is a no-op.
    """
    base = _static_dir()
    if not base.is_dir():
        return
    for rel in ("index.html", "app.js", "styles.css"):
        full = base / rel
        if not full.is_file():
            continue
        body = full.read_bytes()
        ct = {
            "index.html": "text/html; charset=utf-8",
            "app.js": "application/javascript; charset=utf-8",
            "styles.css": "text/css; charset=utf-8",
        }.get(rel, "application/octet-stream")

        def make_handler(data: bytes, ct_: str) -> Callable[[dict[str, Any]], HttpResponse]:
            """
            Create an HTTP route handler that always responds with the given static bytes and content type.

            Parameters:
                data (bytes): Response body to return for every request.
                ct_ (str): MIME content type for the response (e.g., "text/html; charset=utf-8").

            Returns:
                Callable[[dict[str, Any]], HttpResponse]: A handler that accepts a request context and returns an HttpResponse with `body` set to `data` and `content_type` set to `ct_`.
            """
            return lambda ctx: HttpResponse(body=data, content_type=ct_)

        if rel == "index.html":
            server.routes.register(
                "/", make_handler(body, ct), method="GET", auth="open", description="Ghost Console static page"
            )
            server.routes.register(
                "/console", make_handler(body, ct), method="GET", auth="open", description="Ghost Console static page"
            )
        server.routes.register(
            "/static/" + rel, make_handler(body, ct), method="GET", auth="open", description="Static asset"
        )


__all__ = ["CONSOLE_HTML", "register_console_routes", "run_console"]
