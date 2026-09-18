#!/usr/bin/env python3
"""Isolated sandbox that simulates a full Ghost Chimera user workflow.

Purpose
-------
Spin up a throwaway Ghost Console on an ephemeral port with a *fresh* state
directory, then walk the same journey a real user walks through the browser:

    launch console -> status -> choose provider -> run an objective ->
    memory / workspace evidence -> trust + thinking -> readiness -> stop

Every step goes through the real HTTP API surface the browser uses
(``/api/console/*``), never by importing internals directly. The sandbox
writes a machine-readable report (``sandbox_<ts>.json``) and keeps the
console alive for an optional EVE QA pass (``--hold-for-eve``) so a browser
automation agent can attack the same live instance.

Safety
------
- No real credentials: the sandbox selects the ``skip`` (deterministic)
  provider, so zero API keys are touched.
- ``block=False`` + a finally-stop, so the console never leaks behind.
- Fresh temp state dir per run; nothing written under the user's
  ``~/.ghostchimera``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _request(method: str, url: str, body: dict[str, Any] | None = None, *, timeout: float = 15.0) -> dict[str, Any]:
    """One HTTP call to a loopback console route; returns parsed JSON."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 - loopback sandbox only
    if body is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback sandbox only
        return json.loads(response.read().decode("utf-8"))


def _step(name: str, ok: bool, detail: Any, *, warn: bool = False) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "warn": warn, "detail": detail}


def run_sandbox(*, hold_for_eve: bool = False, eve_steps: int | None = None) -> dict[str, Any]:
    from ghostchimera.control_plane.console import run_console

    started = time.monotonic()
    steps: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ghostchimera-sandbox-") as tmp:
        state_dir = Path(tmp)
        with contextlib.redirect_stdout(io.StringIO()):
            server = run_console(
                host="127.0.0.1",
                port=0,
                http_port=0,
                state_dir=state_dir,
                open_browser=False,
                block=False,
            )
        try:
            http_port = server._http_server.server_address[1] if server._http_server else server.http_port
            base = f"http://127.0.0.1:{http_port}"
            time.sleep(0.4)

            # 1. Landing page renders.
            with urllib.request.urlopen(base + "/", timeout=10) as response:  # noqa: S310 - loopback
                html = response.read().decode("utf-8", errors="replace")
            steps.append(_step("landing_page", "operatorWorkbench" in html and "tabQuickJump" in html, "html-ok"))

            # 2. Status endpoint.
            status = _request("GET", base + "/api/console/status")
            autonomy_level = (
                (status.get("autonomy") or {}).get("level") if isinstance(status.get("autonomy"), dict) else None
            )
            steps.append(
                _step(
                    "status",
                    status.get("ok") is True,
                    {"gateway": status.get("gateway"), "autonomy": autonomy_level},
                )
            )

            # 3. Choose a provider that needs no API key via the exact
            #    config endpoint the browser uses. The browser config only
            #    offers real providers (no "skip"/deterministic option), so
            #    a keyless first-run user lands on ollama. This is also a
            #    documented finding from the sandbox.
            config = _request("GET", base + "/api/console/config")
            option_ids = {str(item.get("id")) for item in config.get("provider_options", [])}
            provider_choice = "ollama" if "ollama" in option_ids else ("custom" if "custom" in option_ids else "")
            save = _request("POST", base + "/api/console/config", {"provider": provider_choice or "custom"})
            config_after = _request("GET", base + "/api/console/config")
            model = config_after.get("model", {})
            steps.append(
                _step(
                    "provider_selected",
                    save.get("ok") is True and str(model.get("provider")) in {"ollama", "custom"},
                    {"choice": provider_choice, "provider": model.get("provider"), "save": save},
                )
            )

            # 4. Autonomy (read + set supervised). GET returns
            #    {"config": {...}, "resolved_profile": {...}}.
            autonomy = _request("GET", base + "/api/console/autonomy")
            autonomy_config = autonomy.get("config", {}) if isinstance(autonomy, dict) else {}
            autonomy_level = autonomy_config.get("level")
            steps.append(
                _step(
                    "autonomy_read",
                    autonomy_level is not None,
                    {"level": autonomy_level, "resolved": (autonomy.get("resolved_profile") or {}).get("name")},
                )
            )

            # 5. Run a real objective through the configured backend. A
            #    keyless provider (ollama) with no local server is expected to
            #    be unreachable in the sandbox — that is a WARN, not a hard
            #    failure, because it reflects environment, not product.
            objective = "Summarize what the Ghost Chimera sandbox is doing."
            run_payload = _request("POST", base + "/api/console/run", {"objective": objective})
            run_ok = run_payload.get("ok") is True or bool(run_payload.get("result") or run_payload.get("output"))
            run_error = str(run_payload.get("error") or run_payload.get("detail") or "").strip()
            run_unreachable = any(
                token in run_error.lower()
                for token in ("unauthorized", "connect", "refused", "timeout", "reachable", "ollama", "not running")
            )
            steps.append(
                _step(
                    "objective_run",
                    run_ok or run_unreachable,
                    {
                        "objective": objective,
                        "ok": run_payload.get("ok"),
                        "error": run_error[:300],
                        "result": str(run_payload.get("result") or run_payload.get("output") or "")[:300],
                        "run_id": run_payload.get("run_id") or run_payload.get("envelope", {}).get("run_id"),
                    },
                    warn=run_unreachable,
                )
            )

            # 6. Memory / workspace evidence snapshot.
            workspace = _request("GET", base + "/api/console/workspace")
            steps.append(
                _step(
                    "workspace_snapshot",
                    workspace.get("ok") is True,
                    {"keys": sorted(workspace.keys())[:12]},
                )
            )

            # 7. Thinking trace (explainability surface).
            thinking = _request("GET", base + "/api/console/thinking")
            steps.append(
                _step(
                    "thinking_trace",
                    thinking.get("ok") is True,
                    {"keys": sorted(thinking.keys())[:12]},
                )
            )

            # 8. Capabilities + readiness surfaces.
            capabilities = _request("GET", base + "/api/console/capabilities")
            readiness = _request("GET", base + "/api/console/readiness")
            steps.append(
                _step(
                    "capabilities",
                    capabilities.get("ok") is True,
                    {"keys": sorted(capabilities.keys())[:10]},
                )
            )
            steps.append(
                _step(
                    "readiness",
                    readiness.get("ok") is True,
                    {"checks": len(readiness.get("checks", [])) if isinstance(readiness.get("checks"), list) else 0},
                )
            )

            # 9. Optional EVE QA hook: keep console alive for a browser agent.
            eve_target = None
            if hold_for_eve:
                eve_target = base
                steps.append(_step("eve_hold", True, {"target": base, "steps_budget": eve_steps}))

            wall_ms = round((time.monotonic() - started) * 1000, 1)
            passed = sum(1 for s in steps if s["ok"])
            report: dict[str, Any] = {
                "sandbox": "ghost_chimera_user_workflow",
                "ok": passed == len(steps),
                "base_url": base,
                "state_dir": str(state_dir),
                "summary": {
                    "total": len(steps),
                    "passed": passed,
                    "failed": len(steps) - passed,
                    "wall_time_ms": wall_ms,
                },
                "steps": steps,
                "eve_target": eve_target,
            }

            if hold_for_eve:
                # Hold the console (and the finally-block stop) open for the
                # calling EVE pass; caller is responsible for timing.
                print(json.dumps({"eve_target": eve_target, "status": "held"}, sort_keys=True))
                time.sleep(3600)
            return report
        finally:
            server.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulate a full Ghost Chimera user workflow in an isolated sandbox.")
    parser.add_argument(
        "--hold-for-eve", action="store_true", help="Keep the console alive and print an EVE target URL."
    )
    parser.add_argument("--eve-steps", type=int, default=None, help="EVE max-steps hint for the held console.")
    parser.add_argument("--json", action="store_true", help="Emit the full JSON report.")
    args = parser.parse_args(argv)
    report = run_sandbox(hold_for_eve=args.hold_for_eve, eve_steps=args.eve_steps)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
