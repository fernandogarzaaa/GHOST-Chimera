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
        assert "sk-or" not in json.dumps(data)
        assert data["auth_engine"] == "custom"
        code, status = _get(BASE + "/api/connectors/status")
        assert code == 200 and status["native"]["slack"]["connected"] is False
    finally:
        server.stop()


def test_auth_authorize_callback_status_revoke(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SLACK_CLIENT_ID", "cid")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "csecret")
    server = _server(tmp_path)
    BASE = _base(server)
    try:
        code, auth = _post(BASE + "/api/auth/authorize",
                           {"provider": "slack", "entity_id": "va-1",
                            "redirect_uri": "http://localhost/cb"})
        assert code == 200 and auth["ok"] is True
        assert "client_id=cid" in auth["authorize_url"]
        assert auth["entity_id"] == "va-1"
        code, bad = _post(BASE + "/api/auth/authorize",
                          {"provider": "nope", "entity_id": "va-1",
                           "redirect_uri": "http://localhost/cb"})
        assert bad["ok"] is False
        code, missing = _post(BASE + "/api/auth/authorize", {"provider": "slack"})
        assert missing["ok"] is False
        code, status = _post(BASE + "/api/auth/status", {"entity_id": "va-1"})
        assert code == 200 and status["connections"] == []
        code, revoked = _post(BASE + "/api/auth/revoke",
                              {"entity_id": "va-1", "provider": "slack"})
        assert revoked == {"ok": True, "revoked": False}
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


def test_auth_callback_page_error_paths(tmp_path) -> None:
    """Render safe browser responses for cancelled, incomplete, and invalid callbacks."""
    server = _server(tmp_path)
    try:
        route = server.routes.find("GET", "/api/auth/callback")
        assert route is not None

        def get(query):
            """Invoke the browser callback route with the supplied query values."""
            return route.handler({"method": "GET", "path": "/api/auth/callback",
                                  "headers": {"host": "127.0.0.1:8766"},
                                  "query": query, "body": ""})

        cancelled = get({"error": "access_denied", "error_description": "user said no"})
        assert "user said no" in cancelled.body
        assert cancelled.content_type.startswith("text/html")
        missing = get({})
        assert "Incomplete login" in missing.body
        tampered = get({"code": "x", "state": "!!!not-base64!!!"})
        assert "Bad login state" in tampered.body
        # No key material or tracebacks in any page.
        for page in (cancelled, missing, tampered):
            assert "Traceback" not in page.body
    finally:
        server.stop()


def test_auth_client_id_saved_then_authorizes(tmp_path, monkeypatch) -> None:
    """Use a console-saved Google client ID and include the Gmail read scope."""
    import ghostchimera.control_plane.config as cfg

    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.json")
    server = _server(tmp_path)
    BASE = _base(server)
    try:
        code, missing = _post(BASE + "/api/auth/client-id", {"provider": "", "client_id": ""})
        assert missing["ok"] is False
        code, bad = _post(BASE + "/api/auth/client-id",
                          {"provider": "google-mail", "client_id": "a/b"})
        assert bad["ok"] is False
        code, saved = _post(BASE + "/api/auth/client-id",
                            {"provider": "google-mail", "client_id": "cid.apps.googleusercontent.com"})
        assert code == 200 and saved == {"ok": True, "provider": "google-mail", "saved": True}
        # Saved ID is used without any environment variable...
        code, auth = _post(BASE + "/api/auth/authorize",
                           {"provider": "google-mail", "entity_id": "va-1",
                            "redirect_uri": "http://127.0.0.1:8766/api/auth/callback"})
        assert code == 200 and auth["ok"] is True
        assert "client_id=cid.apps.googleusercontent.com" in auth["authorize_url"]
        # ...and the Gmail API scope rides along by default.
        assert "gmail.readonly" in auth["authorize_url"]
    finally:
        server.stop()
