"""Browser-based Ghost Chimera control console."""

from __future__ import annotations

import json
import time
import webbrowser
from collections.abc import Callable
from typing import Any

from ..chimera_pilot import ChimeraPilotKernel
from ..chimera_pilot.autonomy import get_autonomy_profile, list_autonomy_profiles
from ..chimera_pilot.gateway_server import GatewayServer, HttpResponse
from ..config import GhostChimeraConfig
from ..tool_layer.browser import http_get
from ..tool_layer.browser_workspace import AgentBrowserWorkspace
from .config import get_autonomy_config, load_config, save_config

RunObjective = Callable[[str], dict[str, Any]]
FetchUrl = Callable[[str], str]


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
    </div>
  </main>
  <script>
    const output = document.getElementById("output");
    const state = { profiles: [] };
    function write(value) {
      output.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
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
      } catch (err) {
        document.getElementById("health").textContent = "offline";
        document.getElementById("health").className = "hint error";
        write(String(err));
      }
    }
    function updateAutonomyDescription() {
      const selected = document.getElementById("autonomyLevel").value;
      const profile = state.profiles.find((item) => item.name === selected);
      document.getElementById("autonomyDescription").textContent = profile ? profile.description : "";
    }
    document.getElementById("refresh").onclick = refresh;
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


def register_console_routes(
    server: GatewayServer,
    *,
    run_objective: RunObjective | None = None,
    fetch_url: FetchUrl | None = None,
    browser_workspace: AgentBrowserWorkspace | None = None,
) -> None:
    """Register browser console routes on an existing GatewayServer."""

    objective_runner = run_objective or _default_run_objective
    url_fetcher = fetch_url or http_get
    workspace = browser_workspace or AgentBrowserWorkspace()

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

    server.routes.register("/", console_page, method="GET", auth="open", description="Ghost Console browser UI")
    server.routes.register("/console", console_page, method="GET", auth="open", description="Ghost Console browser UI")
    server.routes.register("/api/console/status", status, method="GET", auth="open", description="Ghost Console status")
    server.routes.register("/api/console/autonomy", autonomy, method="GET", auth="open", description="Ghost Console autonomy")
    server.routes.register("/api/console/autonomy", autonomy, method="POST", auth="open", description="Ghost Console autonomy")
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
    open_browser: bool = True,
    block: bool = True,
) -> GatewayServer:
    """Start the gateway-backed Ghost Console."""

    server = GatewayServer(host=host, port=port, http_port=http_port)
    register_console_routes(server)
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
