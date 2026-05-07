"""Browser-based Ghost Chimera control console."""

from __future__ import annotations

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
from ..chimera_pilot.gateway_server import GatewayServer, HttpResponse
from ..cognition_layer.workspace_state import OperatorWorkspaceStore
from ..config import GhostChimeraConfig
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
]


CONSOLE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ghost Console</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #111315;
      --panel: #181b1f;
      --line: #2a3037;
      --text: #f1f5f9;
      --muted: #9aa6b2;
      --accent: #54d29b;
      --warn: #f1b84b;
      --danger: #f87171;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      border-bottom: 1px solid var(--line);
      background: #15181c;
    }
    h1 { margin: 0; font-size: 17px; font-weight: 650; }
    button, select, input, textarea {
      border: 1px solid var(--line);
      background: #101215;
      color: var(--text);
      border-radius: 6px;
      font: inherit;
    }
    button {
      cursor: pointer;
      min-height: 34px;
      padding: 0 12px;
      background: #20262c;
    }
    button.primary { background: #1b5f45; border-color: #247858; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    main {
      display: grid;
      grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
      min-height: calc(100vh - 56px);
    }
    aside {
      border-right: 1px solid var(--line);
      background: var(--panel);
      padding: 18px;
      overflow: auto;
    }
    section { padding: 20px 24px; border-bottom: 1px solid var(--line); }
    h2 { margin: 0 0 12px; font-size: 14px; font-weight: 650; color: var(--muted); text-transform: uppercase; }
    label { display: block; margin: 12px 0 6px; color: var(--muted); font-size: 12px; }
    select, input, textarea { width: 100%; padding: 9px 10px; }
    textarea { min-height: 112px; resize: vertical; }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #0d0f12;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 180px;
      max-height: 56vh;
      overflow: auto;
    }
    .row { display: flex; align-items: center; gap: 10px; }
    .row > * { flex: 1; }
    .metric { padding: 10px 0; border-bottom: 1px solid var(--line); }
    .metric:last-child { border-bottom: 0; }
    .metric strong { display: block; font-size: 18px; }
    .hint { color: var(--muted); font-size: 12px; margin-top: 8px; }
    .ok { color: var(--accent); }
    .warn { color: var(--warn); }
    .error { color: var(--danger); }
    .stack { display: grid; gap: 10px; }
    .pill {
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .compact-list {
      display: grid;
      gap: 8px;
      max-height: 220px;
      overflow: auto;
    }
    .compact-item {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px;
      background: #111418;
    }
    @media (max-width: 780px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <header>
    <h1>Ghost Console</h1>
    <div class="row" style="max-width: 260px;">
      <button id="refresh">Refresh</button>
      <span id="health" class="hint">connecting</span>
    </div>
  </header>
  <main>
    <aside>
      <section style="padding: 0 0 18px;">
        <h2>Runtime</h2>
        <div class="metric"><span>Gateway</span><strong id="gatewayState">unknown</strong></div>
        <div class="metric"><span>Sessions</span><strong id="sessionCount">0</strong></div>
        <div class="metric"><span>Autonomy</span><strong id="autonomyState">unknown</strong></div>
      </section>
      <section style="padding: 18px 0;">
        <h2>Workspace State</h2>
        <div class="metric"><span>Evidence</span><strong id="workspaceEvidence">0</strong></div>
        <div class="metric"><span>Reflections</span><strong id="workspaceReflections">0</strong></div>
        <div class="metric"><span>Uncertainty</span><strong id="workspaceUncertainty">1.00</strong></div>
        <button id="refreshWorkspace" style="margin-top: 10px; width: 100%;">Inspect Workspace</button>
      </section>
      <section style="padding: 18px 0;">
        <h2>Autonomy</h2>
        <label for="autonomyLevel">Profile</label>
        <select id="autonomyLevel"></select>
        <div class="hint" id="autonomyDescription"></div>
        <button id="saveAutonomy" class="primary" style="margin-top: 12px; width: 100%;">Save Profile</button>
      </section>
      <section style="padding: 18px 0 0;">
        <h2>Browser Workspace</h2>
        <label for="url">HTTPS URL</label>
        <input id="url" value="https://example.com">
        <label for="browserSession">Session</label>
        <input id="browserSession" value="default">
        <div class="row" style="margin-top: 12px;">
          <button id="openBrowser">Open</button>
          <button id="snapshotBrowser">Snapshot</button>
        </div>
        <button id="fetchUrl" style="margin-top: 10px; width: 100%;">HTTPS Fetch</button>
        <div class="hint" id="browserWorkspaceState">checking browser workspace</div>
      </section>
      <section style="padding: 18px 0 0;">
        <h2>Job Center</h2>
        <label for="jobName">Autonomy Job</label>
        <select id="jobName"></select>
        <label><input id="jobExecute" type="checkbox" style="width: auto; margin-right: 6px;"> execute high-impact checks</label>
        <div class="row" style="margin-top: 12px;">
          <button id="queueJob">Queue</button>
          <button id="runJob" class="primary">Run Now</button>
        </div>
        <div class="hint">High-impact jobs still require an operator-enabled profile.</div>
      </section>
      <section style="padding: 18px 0 0;">
        <h2>Schedules</h2>
        <label for="scheduleName">Name</label>
        <input id="scheduleName" value="daily self audit">
        <label for="scheduleCron">Cron</label>
        <input id="scheduleCron" value="0 9 * * *">
        <button id="createSchedule" style="margin-top: 10px; width: 100%;">Create Disabled Schedule</button>
        <div class="hint">Schedules reuse the job center and policy gates.</div>
      </section>
    </aside>
    <div>
      <section>
        <h2>Run Objective</h2>
        <textarea id="objective" placeholder="Ask Ghost Chimera to inspect status, run a safe plan, or summarize a workflow."></textarea>
        <div class="row" style="margin-top: 10px;">
          <button id="runObjective" class="primary">Run</button>
          <button id="clearOutput">Clear</button>
        </div>
      </section>
      <section>
        <h2>Output</h2>
        <pre id="output">Ready.</pre>
      </section>
      <section>
        <h2>Workspace Attention</h2>
        <div id="workspaceAttention" class="compact-list"></div>
      </section>
      <section>
        <h2>Recent Jobs</h2>
        <div id="jobHistory" class="compact-list"></div>
      </section>
      <section>
        <h2>Schedules</h2>
        <div id="scheduleList" class="compact-list"></div>
      </section>
      <section>
        <h2>Release Readiness</h2>
        <div id="readinessList" class="compact-list"></div>
      </section>
    </div>
  </main>
  <script>
    const output = document.getElementById("output");
    const state = { profiles: [], workspace: null };
    function write(value) {
      output.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    }
    async function request(path, options) {
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Request failed");
      return data;
    }
    async function refresh() {
      try {
        const data = await request("/api/console/status");
        state.profiles = data.profiles || [];
        document.getElementById("health").textContent = "online";
        document.getElementById("health").className = "hint ok";
        document.getElementById("gatewayState").textContent = data.gateway.running ? "running" : "available";
        document.getElementById("sessionCount").textContent = data.gateway.session_count;
        document.getElementById("autonomyState").textContent = data.autonomy.resolved_profile.name;
        const browser = data.browser_workspace || {};
        document.getElementById("browserWorkspaceState").textContent = browser.available
          ? "agent-browser available"
          : "agent-browser unavailable; HTTPS Fetch still works";
        document.getElementById("browserWorkspaceState").className = browser.available ? "hint ok" : "hint warn";
        const select = document.getElementById("autonomyLevel");
        select.innerHTML = "";
        for (const profile of state.profiles) {
          const option = document.createElement("option");
          option.value = profile.name;
          option.textContent = profile.name;
          select.appendChild(option);
        }
        select.value = data.autonomy.resolved_profile.name;
        updateAutonomyDescription();
        await refreshJobs();
        await refreshSchedules();
        await refreshWorkspace();
        await refreshReadiness();
      } catch (err) {
        document.getElementById("health").textContent = "offline";
        document.getElementById("health").className = "hint error";
        write(String(err));
      }
    }
    async function refreshJobs() {
      const data = await request("/api/console/autonomy/jobs");
      const select = document.getElementById("jobName");
      select.innerHTML = "";
      for (const job of data.available_jobs || []) {
        const option = document.createElement("option");
        option.value = job.name;
        option.textContent = job.name;
        select.appendChild(option);
      }
      const history = document.getElementById("jobHistory");
      history.innerHTML = "";
      for (const job of (data.history || []).slice().reverse().slice(0, 8)) {
        const item = document.createElement("div");
        item.className = "compact-item";
        item.innerHTML = `<strong>${escapeHtml(job.name)}</strong> <span class="pill">${escapeHtml(job.status)}</span><div class="hint">${escapeHtml(job.profile)} ${job.execute ? "execute" : "preview"}</div>`;
        history.appendChild(item);
      }
      if (!history.children.length) history.textContent = "No autonomy jobs yet.";
    }
    async function refreshWorkspace() {
      const data = await request("/api/console/workspace");
      state.workspace = data;
      document.getElementById("workspaceEvidence").textContent = data.working_memory.evidence.length;
      document.getElementById("workspaceReflections").textContent = data.working_memory.reflections.length;
      document.getElementById("workspaceUncertainty").textContent = Number(data.uncertainty.score).toFixed(2);
      const list = document.getElementById("workspaceAttention");
      list.innerHTML = "";
      for (const item of data.attention || []) {
        const row = document.createElement("div");
        row.className = "compact-item";
        row.innerHTML = `<strong>${escapeHtml(item.type)}</strong> <span class="pill">${escapeHtml(item.attention_score)}</span><div class="hint">${escapeHtml(item.content || item.action || item.source || "")}</div>`;
        list.appendChild(row);
      }
      if (!list.children.length) list.textContent = "No workspace evidence or reflections yet.";
      return data;
    }
    async function refreshSchedules() {
      const data = await request("/api/console/autonomy/schedules");
      const list = document.getElementById("scheduleList");
      list.innerHTML = "";
      for (const schedule of data.schedules || []) {
        const item = document.createElement("div");
        item.className = "compact-item";
        item.innerHTML = `<strong>${escapeHtml(schedule.name)}</strong> <span class="pill">${schedule.enabled ? "enabled" : "disabled"}</span><div class="hint">${escapeHtml(schedule.cron_expression)} next ${escapeHtml(schedule.next_run || "pending")}</div>`;
        const run = document.createElement("button");
        run.textContent = "Run Now";
        run.onclick = async () => {
          write(await request(`/api/console/autonomy/schedules/${schedule.id}/run-now`, { method: "POST" }));
          await refresh();
        };
        item.appendChild(run);
        list.appendChild(item);
      }
      if (!list.children.length) list.textContent = "No schedules yet.";
    }
    async function refreshReadiness() {
      const data = await request("/api/console/readiness");
      const list = document.getElementById("readinessList");
      list.innerHTML = "";
      for (const check of data.checks || []) {
        const item = document.createElement("div");
        item.className = "compact-item";
        item.innerHTML = `<strong>${escapeHtml(check.name)}</strong><div class="hint">${escapeHtml(check.command)}</div>`;
        list.appendChild(item);
      }
    }
    function updateAutonomyDescription() {
      const selected = document.getElementById("autonomyLevel").value;
      const profile = state.profiles.find((item) => item.name === selected);
      document.getElementById("autonomyDescription").textContent = profile ? profile.description : "";
    }
    document.getElementById("refresh").onclick = refresh;
    document.getElementById("refreshWorkspace").onclick = async () => write(await refreshWorkspace());
    document.getElementById("clearOutput").onclick = () => write("Ready.");
    document.getElementById("autonomyLevel").onchange = updateAutonomyDescription;
    document.getElementById("saveAutonomy").onclick = async () => {
      const level = document.getElementById("autonomyLevel").value;
      write(await request("/api/console/autonomy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ level })
      }));
      await refresh();
    };
    document.getElementById("runObjective").onclick = async () => {
      const objective = document.getElementById("objective").value.trim();
      if (!objective) return write("Enter an objective first.");
      write("Running...");
      write(await request("/api/console/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective })
      }));
      await refresh();
    };
    document.getElementById("fetchUrl").onclick = async () => {
      const url = document.getElementById("url").value.trim();
      write("Fetching...");
      write(await request("/api/console/browser/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url })
      }));
    };
    document.getElementById("openBrowser").onclick = async () => {
      const url = document.getElementById("url").value.trim();
      const session = document.getElementById("browserSession").value.trim() || "default";
      write("Opening browser workspace...");
      write(await request("/api/console/browser/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, session })
      }));
      await refresh();
    };
    document.getElementById("snapshotBrowser").onclick = async () => {
      const url = document.getElementById("url").value.trim();
      const session = document.getElementById("browserSession").value.trim() || "default";
      write("Capturing browser snapshot...");
      write(await request("/api/console/browser/snapshot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, session })
      }));
      await refresh();
    };
    document.getElementById("queueJob").onclick = async () => {
      write(await request("/api/console/autonomy/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job: document.getElementById("jobName").value,
          profile: document.getElementById("autonomyLevel").value,
          execute: document.getElementById("jobExecute").checked,
          run_now: false
        })
      }));
      await refresh();
    };
    document.getElementById("runJob").onclick = async () => {
      write(await request("/api/console/autonomy/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job: document.getElementById("jobName").value,
          profile: document.getElementById("autonomyLevel").value,
          execute: document.getElementById("jobExecute").checked,
          run_now: true
        })
      }));
      await refresh();
    };
    document.getElementById("createSchedule").onclick = async () => {
      write(await request("/api/console/autonomy/schedules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: document.getElementById("scheduleName").value,
          cron_expression: document.getElementById("scheduleCron").value,
          job: document.getElementById("jobName").value,
          profile: document.getElementById("autonomyLevel").value,
          execute: document.getElementById("jobExecute").checked,
          enabled: false
        })
      }));
      await refresh();
    };
    refresh();
  </script>
</body>
</html>
"""


def _json_body(ctx: dict[str, Any]) -> dict[str, Any]:
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
    kernel = ChimeraPilotKernel.default(include_deterministic_backend=True)
    executions = kernel.run(objective)
    payload = [execution.to_dict() for execution in executions]
    return {"ok": all(item.get("ok") for item in payload), "executions": payload}


def _status_payload(server: GatewayServer) -> dict[str, Any]:
    config = load_config()
    autonomy = get_autonomy_config(config)
    profile = get_autonomy_profile(str(autonomy.get("level") or "supervised"))
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
) -> None:
    """Register browser console routes on an existing GatewayServer."""

    objective_runner = run_objective or _default_run_objective
    url_fetcher = fetch_url or http_get
    workspace = browser_workspace or AgentBrowserWorkspace()
    queue = autonomy_queue or AutonomyJobQueue(state_dir=state_dir or server.config.state_dir)
    workspace_store = operator_workspace or OperatorWorkspaceStore(state_dir=state_dir or server.config.state_dir)
    scheduler = cron_scheduler
    scheduler_error = ""
    if scheduler is None:
        try:
            from ..chimera_pilot.cron_scheduler import CronScheduler

            scheduler = CronScheduler(state_dir=state_dir or server.config.state_dir, job_executor=_scheduled_executor(queue))
        except Exception as exc:  # pragma: no cover - depends on optional croniter availability
            scheduler_error = str(exc)

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
        for key in ("max_tool_rounds", "max_parallel_tasks", "local_model_profile", "require_approval_for_high_impact"):
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

    def readiness(ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "checks": [dict(check) for check in RELEASE_CHECKS],
            "note": "Run these checks locally before tagging or pushing a beta release.",
        }

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
    server.routes.register("/api/console/status", status, method="GET", auth="open", description="Ghost Console status")
    server.routes.register("/api/console/autonomy", autonomy, method="GET", auth="open", description="Ghost Console autonomy")
    server.routes.register("/api/console/autonomy", autonomy, method="POST", auth="open", description="Ghost Console autonomy")
    server.routes.register(
        "/api/console/workspace",
        operator_workspace_snapshot,
        method="GET",
        auth="open",
        description="Inspect operator workspace state",
    )
    server.routes.register(
        "/api/console/workspace/evidence",
        operator_workspace_evidence,
        method="POST",
        auth="open",
        description="Record operator workspace evidence",
    )
    server.routes.register(
        "/api/console/workspace/reflections",
        operator_workspace_reflection,
        method="POST",
        auth="open",
        description="Record operator workspace reflection",
    )
    server.routes.register(
        "/api/console/workspace/goals",
        operator_workspace_goal,
        method="POST",
        auth="open",
        description="Set operator workspace goal",
    )
    server.routes.register(
        "/api/console/workspace/sync-memory",
        operator_workspace_sync_memory,
        method="POST",
        auth="open",
        description="Promote operator workspace records into CWR memory",
    )
    server.routes.register("/api/console/readiness", readiness, method="GET", auth="open", description="Ghost Console release readiness runbook")
    server.routes.register("/api/console/autonomy/jobs", jobs_list, method="GET", auth="open", description="List autonomy jobs")
    server.routes.register("/api/console/autonomy/jobs", jobs_create, method="POST", auth="open", description="Queue autonomy job")
    server.routes.register(
        "/api/console/autonomy/jobs/",
        jobs_detail,
        method="GET",
        auth="open",
        prefix=True,
        description="Inspect autonomy job record",
    )
    server.routes.register(
        "/api/console/autonomy/jobs/",
        jobs_cancel,
        method="POST",
        auth="open",
        prefix=True,
        description="Cancel queued autonomy job",
    )
    server.routes.register(
        "/api/console/autonomy/schedules",
        schedules_list,
        method="GET",
        auth="open",
        description="List autonomy schedules",
    )
    server.routes.register(
        "/api/console/autonomy/schedules",
        schedules_create,
        method="POST",
        auth="open",
        description="Create autonomy schedule",
    )
    server.routes.register(
        "/api/console/autonomy/schedules/",
        schedules_action,
        method="POST",
        auth="open",
        prefix=True,
        description="Update, run, or delete autonomy schedule",
    )
    server.routes.register("/api/console/run", run, method="POST", auth="open", description="Run a Ghost objective")
    server.routes.register(
        "/api/console/browser/fetch",
        browser_fetch,
        method="POST",
        auth="open",
        description="Fetch an HTTPS URL through the Ghost browser tool",
    )
    server.routes.register(
        "/api/console/browser/status",
        browser_workspace_status,
        method="GET",
        auth="open",
        description="Inspect optional agent-browser workspace availability",
    )
    server.routes.register(
        "/api/console/browser/open",
        browser_open,
        method="POST",
        auth="open",
        description="Open an HTTPS URL in the optional agent-browser workspace",
    )
    server.routes.register(
        "/api/console/browser/snapshot",
        browser_snapshot,
        method="POST",
        auth="open",
        description="Capture an accessibility snapshot from the optional agent-browser workspace",
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
) -> GatewayServer:
    """Start the gateway-backed Ghost Console."""

    config = GhostChimeraConfig.from_env()
    if state_dir:
        resolved = Path(state_dir).expanduser()
        config = replace(config, state_dir=resolved, memory_db=resolved / "memory.sqlite3", audit_file=resolved / "audit.json")
    server = GatewayServer(host=host, port=port, http_port=http_port, config=config)
    register_console_routes(server, state_dir=state_dir or config.state_dir)
    server.start()
    url = _console_url(server)
    print(f"Ghost Console: {url}")
    if open_browser:
        webbrowser.open(url)
    if block:
        try:
            while True:
                time.sleep(0.25)
        except KeyboardInterrupt:
            server.stop()
    return server


__all__ = ["CONSOLE_HTML", "register_console_routes", "run_console"]
