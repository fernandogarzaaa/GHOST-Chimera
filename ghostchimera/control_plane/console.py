"""Browser-based Ghost Chimera control console."""

from __future__ import annotations

import contextlib
import json
import time
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..chimera_pilot import ChimeraPilotKernel
from ..chimera_pilot.autonomy import get_autonomy_profile, list_autonomy_profiles
from ..chimera_pilot.autonomy_jobs import JOB_SPECS
from ..chimera_pilot.autonomy_queue import AutonomyJobQueue
from ..chimera_pilot.capability_intelligence import inspect_capabilities
from ..chimera_pilot.desktop_policy import DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN
from ..chimera_pilot.gateway_server import GatewayServer, HttpResponse
from ..chimera_pilot.pr_review import run_pr_review
from ..cognition_layer.workspace_state import OperatorWorkspaceStore
from ..config import GhostChimeraConfig
from ..memory_layer.store import MemoryStore
from ..model_layer.minimind_lifecycle import MiniMindLifecycle
from ..model_layer.minimind_personal_agent import MiniMindPersonalAgent
from ..tool_layer.browser import http_get
from ..tool_layer.browser_workspace import AgentBrowserWorkspace
from .config import get_autonomy_config, load_config, save_config

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
    path_config_file = Path(config_path).expanduser() if config_path else None
    scheduler = cron_scheduler
    scheduler_error = ""
    if scheduler is None:
        try:
            from ..chimera_pilot.cron_scheduler import CronScheduler

            scheduler = CronScheduler(state_dir=state_dir or server.config.state_dir, job_executor=_scheduled_executor(queue))
        except Exception as exc:  # pragma: no cover - depends on optional croniter availability
            scheduler_error = str(exc)

    # Auth settings for API routes: use token auth when a console token is configured.
    _api_auth = "token" if console_token else "open"
    _api_token = console_token

    def _api_register(path: str, handler: Any, *, method: str = "GET", prefix: bool = False, description: str = "") -> None:
        """Register an API route with the appropriate auth mode."""
        server.routes.register(path, handler, method=method, auth=_api_auth, token=_api_token, prefix=prefix, description=description)

    def console_page(ctx: dict[str, Any]) -> HttpResponse:
        return HttpResponse(body=CONSOLE_HTML, content_type="text/html; charset=utf-8")

    def status(ctx: dict[str, Any]) -> dict[str, Any]:
        payload = _status_payload(server)
        payload["browser_workspace"] = workspace.status()
        return payload

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
        try:
            return objective_runner(objective)
        except PermissionError as exc:
            return {"ok": False, "error": str(exc), "type": "permission"}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "type": "runtime"}

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
                dataset_count = sum(
                    1 for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()
                )
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
            dataset_count = sum(
                1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()
            )
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
        return {"ok": True, "path": path}

    def github_status(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..integrations.github_client import GitHubAuth

        auth = GitHubAuth.discover()
        return {"ok": True, "auth_mode": auth.mode, "has_token": bool(auth.token)}

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
    _api_register("/api/console/autonomy", autonomy, method="GET", description="Ghost Console autonomy")
    _api_register("/api/console/autonomy", autonomy, method="POST", description="Ghost Console autonomy")
    _api_register("/api/console/workspace", operator_workspace_snapshot, method="GET", description="Inspect operator workspace state")
    _api_register("/api/console/workspace/evidence", operator_workspace_evidence, method="POST", description="Record operator workspace evidence")
    _api_register("/api/console/workspace/reflections", operator_workspace_reflection, method="POST", description="Record operator workspace reflection")
    _api_register("/api/console/workspace/goals", operator_workspace_goal, method="POST", description="Set operator workspace goal")
    _api_register("/api/console/workspace/sync-memory", operator_workspace_sync_memory, method="POST", description="Promote operator workspace records into CWR memory")
    _api_register("/api/console/memory/status", memory_status, method="GET", description="Show local CWR memory status")
    _api_register("/api/console/memory/ingest", memory_ingest, method="POST", description="Ingest text into local CWR memory")
    _api_register("/api/console/memory/ingest-email", memory_ingest_email, method="POST", description="Ingest email (.eml/.mbox or raw text) into personal memory")
    _api_register("/api/console/memory/ingest-file", memory_ingest_file, method="POST", description="Ingest a local file or directory into personal memory")
    _api_register("/api/console/memory/search", memory_search, method="POST", description="Search local CWR memory")
    _api_register("/api/console/training/status", training_status, method="GET", description="MiniMind training setup status and dataset record count")
    _api_register("/api/console/training/teach", training_teach, method="POST", description="Append a prompt/response pair to the personal training dataset")
    _api_register("/api/console/minimind/status", minimind_status, method="GET", description="Show MiniMind local runtime status")
    _api_register("/api/console/minimind/dataset", minimind_dataset, method="POST", description="Write a MiniMind JSONL dataset from prompt/response records")
    _api_register("/api/console/minimind/personal/status", minimind_personal_status, method="GET", description="Show Personal MiniMind consent, memory, dataset, and RAG readiness")
    _api_register("/api/console/minimind/personal/consent", minimind_personal_consent, method="POST", description="Grant Personal MiniMind admin/source consent")
    _api_register("/api/console/minimind/personal/revoke", minimind_personal_revoke, method="POST", description="Revoke Personal MiniMind admin/source consent")
    _api_register("/api/console/minimind/personal/bootstrap", minimind_personal_bootstrap, method="POST", description="Bootstrap Personal MiniMind from consented local sources")
    _api_register("/api/console/minimind/personal/handoff", minimind_personal_handoff, method="POST", description="Build Personal MiniMind RAG handoff for the primary model")
    _api_register("/api/console/paths", role_profiles, method="GET", description="List multi-purpose Ghost paths")
    _api_register("/api/console/paths/synthesize", synthesize_role_path, method="POST", description="Synthesize Ghost Chimera from a selected user path")
    _api_register("/api/console/paths/active", active_role_path, method="GET", description="Show the active persisted Ghost path")
    _api_register("/api/console/paths/active", active_role_path, method="POST", description="Persist the active Ghost path")
    _api_register("/api/console/github/status", github_status, method="GET", description="Inspect GitHub integration status")
    _api_register("/api/console/github/plan", github_plan, method="POST", description="Convert a GitHub issue into a Ghost objective")
    _api_register("/api/console/github/policy-simulate", github_policy_simulate, method="POST", description="Preview GitHub action controls")
    _api_register("/api/console/capabilities", capabilities, method="GET", description="Inspect competitive agent-orchestration capability coverage")
    _api_register("/api/console/review-pr", review_pr, method="POST", description="Run deterministic PR/diff review automation")
    _api_register("/api/console/readiness", readiness, method="GET", description="Ghost Console release readiness runbook")
    _api_register("/api/console/skills", skills_list, method="GET", description="List registered skills")
    _api_register("/api/console/autonomy/jobs", jobs_list, method="GET", description="List autonomy jobs")
    _api_register("/api/console/autonomy/jobs", jobs_create, method="POST", description="Queue autonomy job")
    _api_register("/api/console/autonomy/jobs/", jobs_detail, method="GET", prefix=True, description="Inspect autonomy job record")
    _api_register("/api/console/autonomy/jobs/", jobs_cancel, method="POST", prefix=True, description="Cancel queued autonomy job")
    _api_register("/api/console/autonomy/schedules", schedules_list, method="GET", description="List autonomy schedules")
    _api_register("/api/console/autonomy/schedules", schedules_create, method="POST", description="Create autonomy schedule")
    _api_register("/api/console/autonomy/schedules/", schedules_action, method="POST", prefix=True, description="Update, run, or delete autonomy schedule")
    _api_register("/api/console/run", run, method="POST", description="Run a Ghost objective")
    _api_register("/api/console/browser/fetch", browser_fetch, method="POST", description="Fetch an HTTPS URL through the Ghost browser tool")
    _api_register("/api/console/browser/status", browser_workspace_status, method="GET", description="Inspect optional agent-browser workspace availability")
    _api_register("/api/console/browser/open", browser_open, method="POST", description="Open an HTTPS URL in the optional agent-browser workspace")
    _api_register("/api/console/browser/snapshot", browser_snapshot, method="POST", description="Capture an accessibility snapshot from the optional agent-browser workspace")
    _api_register("/api/console/security/events", _security_events_handler, method="GET", description="Security event log from DPI inspection (Lobster Trap)")
    _api_register("/api/console/security/summary", _security_summary_handler, method="GET", description="Aggregated threat statistics and risk timeline")
    _api_register("/api/console/security/audit", _security_audit_handler, method="GET", description="HMAC-chained audit log entries and chain integrity check")


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

    config = GhostChimeraConfig.from_env()
    if state_dir:
        resolved = Path(state_dir).expanduser()
        config = replace(config, state_dir=resolved, memory_db=resolved / "memory.sqlite3", audit_file=resolved / "audit.json")
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
        ct = {"index.html": "text/html; charset=utf-8", "app.js": "application/javascript; charset=utf-8", "styles.css": "text/css; charset=utf-8"}.get(rel, "application/octet-stream")

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
            server.routes.register("/", make_handler(body, ct), method="GET", auth="open", description="Ghost Console static page")
            server.routes.register("/console", make_handler(body, ct), method="GET", auth="open", description="Ghost Console static page")
        server.routes.register("/static/" + rel, make_handler(body, ct), method="GET", auth="open", description="Static asset")


__all__ = ["CONSOLE_HTML", "register_console_routes", "run_console"]
