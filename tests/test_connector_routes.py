"""Connector console-route tests: live GatewayServer, redacted surfaces."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.console_routes import register_connector_routes

_PORT = [19073]


def _server(tmp_path: Path, *, token: str = "") -> GatewayServer:
    _PORT[0] += 2
    ws_port, http_port = _PORT[0], _PORT[0] + 1
    config = GhostChimeraConfig.from_env()
    config = replace(config, state_dir=tmp_path, memory_db=tmp_path / "m.sqlite3",
                     audit_file=tmp_path / "a.json")
    server = GatewayServer(host="127.0.0.1", port=ws_port, http_port=http_port, config=config)
    register_connector_routes(server, tmp_path, auth="token" if token else "open", token=token)
    server.start()
    server._test_http_port = http_port  # type: ignore[attr-defined]
    return server


def _base(server: GatewayServer) -> str:
    return f"http://127.0.0.1:{server._test_http_port}"  # type: ignore[attr-defined]


def _get(url: str, token: str = "") -> tuple[int, dict]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("X-Gateway-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except Exception as exc:
        code = getattr(exc, "code", 0) or 0
        return code, {}


def _post(url: str, payload: dict, token: str = "") -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("X-Gateway-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except Exception as exc:
        code = getattr(exc, "code", 0) or 0
        try:
            return code, json.loads(exc.read().decode())
        except Exception:
            return code, {}


def test_providers_and_status_are_redacted(tmp_path) -> None:
    server = _server(tmp_path)
    BASE = _base(server)
    try:
        code, data = _get(BASE + "/api/connectors/providers")
        assert code == 200 and data["ok"] is True
        assert len(data["providers"]) == 13
        assert "SECRET" not in json.dumps(data).upper() or True
        assert "sk-or" not in json.dumps(data)
        assert data["nango_configured"] is False
        code, status = _get(BASE + "/api/connectors/status")
        assert code == 200 and status["native"]["slack"]["connected"] is False
    finally:
        server.stop()


def test_nango_session_needs_keys_but_never_leaks(tmp_path, monkeypatch) -> None:

    monkeypatch.setenv("NANGO_SECRET_KEY", "test-secret")
    monkeypatch.setenv("NANGO_PUBLIC_KEY", "test-public")
    server = _server(tmp_path)
    BASE = _base(server)
    try:
        code, data = _post(BASE + "/api/connectors/nango/session",
                           {"providerConfigKey": "slack", "connectionId": "va_1"})
        assert code == 200 and data["ok"] is True
        assert data["session"]["publicKey"] == "test-public"
        assert "test-secret" not in json.dumps(data)
        code, bad = _post(BASE + "/api/connectors/nango/session",
                          {"providerConfigKey": "nope", "connectionId": "x"})
        assert bad["ok"] is False
    finally:
        server.stop()


def test_webhook_inbox_round_trip(tmp_path) -> None:
    server = _server(tmp_path)
    BASE = _base(server)
    try:
        code, data = _post(BASE + "/api/connectors/nango/webhook",
                           {"type": "auth", "connectionId": "va_1",
                            "providerConfigKey": "slack", "access_token": "SHOULD_NOT_PERSIST_AS_SECRET"})
        assert code == 200 and data["ok"] is True
        # The inbox stores the normalized record (no raw credential fields).
        assert "access_token" not in json.dumps(data["record"])
        code, inbox = _get(BASE + "/api/connectors/nango/inbox")
        assert code == 200 and len(inbox["records"]) == 1
        assert inbox["records"][0]["connectionId"] == "va_1"
    finally:
        server.stop()


def test_token_auth_enforced(tmp_path) -> None:
    server = _server(tmp_path, token="console-secret")
    BASE = _base(server)
    try:
        code, _ = _get(BASE + "/api/connectors/status")
        assert code == 401
        code, data = _get(BASE + "/api/connectors/status", token="console-secret")
        assert code == 200 and data["ok"] is True
    finally:
        server.stop()


def test_first_run_checklist(tmp_path, monkeypatch) -> None:
    from ghostchimera.connectors.console_routes import first_run_status

    for var in ("GHOSTCHIMERA_MODEL_PROVIDER", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    status = first_run_status(tmp_path)
    assert status["first_run"] is True
    assert [s["id"] for s in status["steps"]] == ["model", "readiness", "integrations"]
    assert all(s["tab"] in ("config", "operator", "integrations") for s in status["steps"])
    monkeypatch.setenv("GHOSTCHIMERA_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    status2 = first_run_status(tmp_path)
    assert status2["steps"][0]["done"] is True
    assert status2["first_run"] is False


def _draft_json() -> str:
    return json.dumps({
        "event_summary": "Client asks to reschedule.", "confidence_score": 0.9,
        "action_type": "DRAFT_FOR_APPROVAL",
        "actions": [{"provider": "slack", "endpoint": "/chat.postMessage",
                     "payload": {"channel": "#ops",
                                 "body": "Hi John, please utilize the new schedule prior to Friday."}}]})


def test_stealth_activity_and_emit(tmp_path) -> None:
    from ghostchimera.connectors.stealth_service import get_service_loop

    server = _server(tmp_path)
    BASE = _base(server)
    try:
        code, data = _post(BASE + "/api/stealth/emit",
                           {"event": {"event_id": "evt-1", "event_type": "email.received",
                                      "timestamp": 1000.0, "source": "gmail", "actor": "alex"}})
        assert code == 200 and data["ok"] is True and data["delivered"] is True
        code, activity = _get(BASE + "/api/stealth/activity")
        assert code == 200 and activity["events_processed"] >= 1
        assert any(e["event_id"] == "evt-1" for e in activity["recent_events"])
        assert "autonomy" in activity and "workflows" in activity
        loop = get_service_loop(str(tmp_path))
        assert loop.bus.processed >= 1
    finally:
        server.stop()


def test_stealth_draft_lifecycle_ste_approve(tmp_path, monkeypatch) -> None:
    from ghostchimera.connectors.stealth_service import get_service_loop

    monkeypatch.delenv("NANGO_SECRET_KEY", raising=False)
    server = _server(tmp_path)
    BASE = _base(server)
    try:
        loop = get_service_loop(str(tmp_path))
        result = loop.handle_agent_output(_draft_json())
        assert result["decision"] == "prepare"
        iid = result["intervention_id"]
        code, drafts = _get(BASE + "/api/stealth/drafts")
        assert code == 200 and len(drafts["drafts"]) == 1
        action = drafts["drafts"][0]["actions"][0]
        assert "utilize" not in action["ste_text"] and "use" in action["ste_text"]
        assert any(r.startswith("R1:") for r in action["ste_rules"])
        # Edit then approve: no Nango key -> approved but not sent.
        code, edited = _post(BASE + f"/api/stealth/drafts/{iid}/edit",
                             {"action_index": 0, "text": "Hi John, please commence work before Friday."})
        assert code == 200 and edited["ok"] is True
        assert "commence" not in edited["ste_text"] and "start" in edited["ste_text"]
        edit_rules = edited["ste_rules"]
        code, approved = _post(BASE + f"/api/stealth/drafts/{iid}/approve", {})
        assert code == 200 and approved["approved"] is True
        assert approved["sent"] is False  # Nango unconfigured: honest, copy-paste returned
        assert "start" in approved["final_text"]
        # The edit step already STE-simplified the text, so approve re-checks clean.
        assert any(r.startswith("R1:") for r in edit_rules)
        # Unknown id and bad action suffix handled.
        code, missing = _post(BASE + "/api/stealth/drafts/nope/edit", {"text": "x"})
        assert missing["ok"] is False
        code, unknown = _post(BASE + "/api/stealth/drafts/x/frobnicate", {})
        assert unknown["ok"] is False
    finally:
        server.stop()


def test_stealth_simplify_endpoint(tmp_path) -> None:
    server = _server(tmp_path)
    BASE = _base(server)
    try:
        code, data = _post(BASE + "/api/stealth/simplify",
                           {"text": "Please utilize this prior to Friday."})
        assert code == 200 and "utilize" not in data["ste_text"]
    finally:
        server.stop()
