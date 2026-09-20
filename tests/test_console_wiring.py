"""Wiring contract: every auth route responds (never 404), every console
section has a live backend. Catches unwired UI and dead routes."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.console_routes import register_connector_routes

_PORT = [19873]


def _server(tmp_path: Path) -> GatewayServer:
    _PORT[0] += 2
    ws_port, http_port = _PORT[0], _PORT[0] + 1
    config = GhostChimeraConfig.from_env()
    config = replace(config, state_dir=tmp_path, memory_db=tmp_path / "m.sqlite3", audit_file=tmp_path / "a.json")
    server = GatewayServer(host="127.0.0.1", port=ws_port, http_port=http_port, config=config)
    register_connector_routes(server, tmp_path)
    server.start()
    server._test_http_port = http_port  # type: ignore[attr-defined]
    return server


def _base(server: GatewayServer) -> str:
    return f"http://127.0.0.1:{server._test_http_port}"  # type: ignore[attr-defined]


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except Exception as exc:
        code = getattr(exc, "code", 0) or 0
        try:
            return code, json.loads(exc.read().decode())
        except Exception:
            return code, {}


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except Exception as exc:
        return getattr(exc, "code", 0) or 0, ""


# (route, body): every entry must answer with a JSON "ok" or an HTML page —
# 404 means the UI calls a dead route.
POST_ROUTES = [
    ("/api/auth/gh/status", {}),
    ("/api/auth/gh/import", {}),
    ("/api/auth/device/start", {}),
    ("/api/auth/device/poll", {}),
    ("/api/auth/keys/save", {}),
    ("/api/auth/keys/list", {}),
    ("/api/auth/keys/delete", {}),
    ("/api/auth/keys/use-as-model", {}),
    ("/api/auth/keys/model-ref", {}),
    ("/api/auth/import-csv/preview", {}),
    ("/api/auth/import-csv/commit", {}),
    ("/api/auth/browser/preview", {}),
    ("/api/auth/browser/import", {}),
    ("/api/auth/mail/fetch", {}),
    ("/api/auth/bluesky/post", {}),
    ("/api/auth/bluesky/timeline", {}),
    ("/api/auth/openrouter/start", {}),
    ("/api/auth/approvals/request", {}),
    ("/api/auth/approvals/decide", {}),
    ("/api/auth/approvals/pending", {}),
    ("/api/auth/audit/recent", {}),
    ("/api/auth/write-gate", {}),
    ("/api/auth/takeover/start", {}),
    ("/api/auth/takeover/release", {}),
    ("/api/auth/takeover/status", {}),
    ("/api/auth/automations", {}),
    ("/api/auth/automations/create", {}),
    ("/api/auth/automations/set", {}),
    ("/api/auth/automations/fire", {}),
    ("/api/auth/automations/runs", {}),
    ("/api/auth/automations/execute", {}),
    ("/api/auth/client-id", {}),
    ("/api/auth/authorize", {}),
    ("/api/auth/callback", {}),
    ("/api/auth/status", {}),
    ("/api/auth/revoke", {}),
]


def test_every_post_route_answers(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        base = _base(server)
        for path, body in POST_ROUTES:
            code, data = _post(base + path, body)
            assert code == 200, f"{path} -> HTTP {code}"
            assert isinstance(data, dict) and "ok" in data, f"{path} has no ok field: {data}"
    finally:
        server.stop()


def test_login_options_and_landing_pages(tmp_path) -> None:
    import json as _json

    server = _server(tmp_path)
    try:
        base = _base(server)
        code, body = _get(base + "/api/auth/login-options")
        assert code == 200
        options = _json.loads(body)["options"]
        assert len(options) >= 20
        code, body = _get(base + "/api/auth/openrouter/landing")
        assert code == 200 and len(body) > 0
        code, body = _get(base + "/api/auth/callback")
        assert code == 200 and len(body) > 0
    finally:
        server.stop()


def test_console_sections_have_backend_ids() -> None:
    """Every interactive console section's key element IDs exist in the HTML."""
    with open("ghostchimera/control_plane/static/index.html", encoding="utf-8") as handle:
        html = handle.read()
    for section_id in (
        "providerLogins",
        "ghCliBanner",
        "storedKeys",
        "credentialImportPreview",
        "approvalsPending",
        "auditOutput",
        "takeoverOutput",
        "automationsList",
        "automationRuns",
        "blueskyOutput",
        "mailOutput",
    ):
        assert f'id="{section_id}"' in html, f"missing section: {section_id}"


def test_first_run_steps_point_at_real_tabs_and_controls(tmp_path) -> None:
    """Start-setup navigation contract: each step's tab exists as tab-content,
    and the JS spotlight target for each step id exists. Prevents dead jumps."""
    import re

    from ghostchimera.connectors.console_routes import first_run_status

    with open("ghostchimera/control_plane/static/index.html", encoding="utf-8") as handle:
        html = handle.read()
    with open("ghostchimera/control_plane/static/app.js", encoding="utf-8") as handle:
        js = handle.read()
    with open("ghostchimera/control_plane/static/styles.css", encoding="utf-8") as handle:
        css = handle.read()
    contents = set(re.findall(r'id="(tab-[a-z-]+)"', html))
    for step in first_run_status(tmp_path)["steps"]:
        assert f"tab-{step['tab']}" in contents, f"step {step['id']} points at missing tab-{step['tab']}"
    assert ".spotlight" in css, "spotlight style missing"
    for target in ("configProvider", "operatorReadiness", "providerLogins"):
        assert f'id="{target}"' in html, f"spotlight target missing: {target}"
        assert target in js, f"spotlight mapping missing: {target}"
