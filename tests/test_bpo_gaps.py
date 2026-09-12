"""BPO production gaps: store, webhooks, ghost-write route (offline tests)."""

from __future__ import annotations

import json

from ghostchimera.connectors import normalize_webhook
from ghostchimera.stealth import BpoStore


def test_va_registry_round_trip(tmp_path) -> None:
    store = BpoStore(tmp_path / "bpo.sqlite3", state_dir=tmp_path)
    try:
        assert store.get_va("va-missing") is None
        va = store.create_va("agent@example.com", organization_id="org-1")
        fetched = store.get_va(va["id"])
        assert fetched is not None and fetched["email"] == "agent@example.com"
    finally:
        store.close()


def test_oauth_connection_registry(tmp_path) -> None:
    store = BpoStore(tmp_path / "bpo.sqlite3", state_dir=tmp_path)
    try:
        va = store.create_va("agent@example.com")
        assert store.connections_for(va["id"]) == []
        record = store.register_connection(va["id"], "slack", "va_1")
        assert record["status"] == "ACTIVE"
        found = store.connections_for(va["id"], provider_config_key="slack")
        assert len(found) == 1 and found[0]["connection_id"] == "va_1"
        assert store.connections_for(va["id"], provider_config_key="gmail") == []
    finally:
        store.close()


def test_browser_profile_encrypted_round_trip(tmp_path) -> None:
    store = BpoStore(tmp_path / "bpo.sqlite3", state_dir=tmp_path)
    try:
        va = store.create_va("agent@example.com")
        assert store.load_browser_profile(va["id"], "crm.example.com") is None
        auth_state = {
            "cookies": [{"name": "session", "value": "SECRET123"}],
            "origins": [{"origin": "https://crm.example.com"}],
        }
        saved = store.save_browser_profile(va["id"], "crm.example.com", auth_state)
        assert saved["domain"] == "crm.example.com"
        # At rest the blob must not contain the plaintext secret.
        raw = (tmp_path / "bpo.sqlite3").read_bytes()
        assert b"SECRET123" not in raw
        loaded = store.load_browser_profile(va["id"], "crm.example.com")
        assert loaded == auth_state
        assert store.deactivate_browser_profile(va["id"], "crm.example.com") is True
        assert store.load_browser_profile(va["id"], "crm.example.com") is None
    finally:
        store.close()


def test_audit_trail_modes_and_pathways(tmp_path) -> None:
    store = BpoStore(tmp_path / "bpo.sqlite3", state_dir=tmp_path)
    try:
        va = store.create_va("agent@example.com")
        store.record_audit(
            va_id=va["id"],
            event_type="ticket.created",
            confidence_score=0.95,
            execution_mode="AUTONOMOUS_EXECUTE",
            execution_pathway="NANGO_API",
            payload_snapshot={"ticket_id": 7},
        )
        store.record_audit(
            va_id=va["id"],
            event_type="ticket.escalated",
            confidence_score=0.7,
            execution_mode="DRAFT_FOR_APPROVAL",
            execution_pathway="BROWSER_MICROVM",
            payload_snapshot={"ticket_id": 8},
        )
        rows = store.audit_for(va["id"])
        assert len(rows) == 2
        assert {r["execution_pathway"] for r in rows} == {"NANGO_API", "BROWSER_MICROVM"}
        assert rows[0]["timestamp"] >= rows[1]["timestamp"]
        assert store.audit_for("va-missing") == []
    finally:
        store.close()


def test_gmail_webhook_normalizes() -> None:
    event = normalize_webhook(
        "gmail",
        "d1",
        "va-1",
        {
            "id": "msg-1",
            "threadId": "t-1",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "client@example.com"},
                    {"name": "Subject", "value": "Reschedule?"},
                ]
            },
            "snippet": "Can we move to Friday",
        },
    )
    assert event is not None and event.event_type == "email.received"
    assert event.actor == "client@example.com"
    assert event.payload["va_id"] == "va-1"
    assert event.payload["subject"] == "Reschedule?"


def test_slack_webhook_filters_echoes_and_pings() -> None:
    assert normalize_webhook("slack", "d0", "va-1", {"type": "url_verification"}) is None
    assert (
        normalize_webhook(
            "slack",
            "d1",
            "va-1",
            {"event": {"type": "message", "bot_id": "B1", "text": "hi", "channel": "C1", "ts": "1"}},
        )
        is None
    )
    event = normalize_webhook(
        "slack",
        "d2",
        "va-1",
        {"event": {"type": "message", "user": "U7", "text": "refund please", "channel": "C1", "ts": "2"}},
    )
    assert event is not None and event.actor == "U7"
    mention = normalize_webhook(
        "slack",
        "d3",
        "va-1",
        {"event": {"type": "app_mention", "user": "U7", "text": "help", "channel": "C1", "ts": "3"}},
    )
    assert mention is not None and mention.event_type == "agent.prompt_submitted"


def test_zendesk_webhook_routes_by_status() -> None:
    opened = normalize_webhook(
        "zendesk",
        "d1",
        "va-1",
        {
            "ticket": {
                "id": 42,
                "status": "new",
                "subject": "Broken",
                "priority": "urgent",
                "requester": {"email": "client@example.com"},
            }
        },
    )
    assert opened is not None and opened.event_type == "agent.prompt_submitted"
    assert opened.payload["ticket_id"] == 42
    solved = normalize_webhook("zendesk", "d2", "va-1", {"ticket": {"id": 43, "status": "solved"}})
    assert solved is not None and solved.event_type == "agent.response_completed"
    assert normalize_webhook("zendesk", "d3", "va-1", {"nope": True}) is None
    assert normalize_webhook("pagerduty", "d4", "va-1", {}) is None


def test_ghost_write_route_honest_without_model(tmp_path) -> None:
    import urllib.request
    from dataclasses import replace

    from ghostchimera.chimera_pilot.gateway_server import GatewayServer
    from ghostchimera.config import GhostChimeraConfig
    from ghostchimera.connectors.console_routes import register_connector_routes

    config = replace(
        GhostChimeraConfig.from_env(),
        state_dir=tmp_path,
        memory_db=tmp_path / "m.sqlite3",
        audit_file=tmp_path / "a.json",
    )
    server = GatewayServer(host="127.0.0.1", port=19173, http_port=19174, config=config)
    register_connector_routes(server, tmp_path)
    server.start()
    try:

        def post(path, payload):
            req = urllib.request.Request(
                f"http://127.0.0.1:19174{path}",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)

        short = post("/api/stealth/ghost-write", {"prompt_context": "hi"})
        assert short["ok"] is False
        # No provider keys in this env: honest no-model answer, never faked.
        long_text = post(
            "/api/stealth/ghost-write", {"prompt_context": "Customer asks for a refund for a double charge."}
        )
        assert long_text["ok"] is False
        assert "no completion available" in long_text["error"]
        hook = post(
            "/api/webhooks/slack/va-9",
            {"event": {"type": "message", "user": "U1", "text": "hello", "channel": "C1", "ts": "99"}},
        )
        assert hook["ok"] is True and hook["queued"] is True
        assert hook["decision"] in ("none", "store", "prepare", "inject", "act", "ask")
        ping = post("/api/webhooks/slack/va-9", {"type": "url_verification"})
        assert ping["ok"] is True and ping["queued"] is False
        assert post("/api/webhooks/pagerduty/va-9", {})["ok"] is False
    finally:
        server.stop()


def test_ghost_write_route_uses_model_when_present(tmp_path, monkeypatch) -> None:
    import urllib.request
    from dataclasses import replace

    import ghostchimera.model_layer.llm as llm_mod
    from ghostchimera.chimera_pilot.gateway_server import GatewayServer
    from ghostchimera.config import GhostChimeraConfig
    from ghostchimera.connectors.console_routes import register_connector_routes

    class FakeLLM:
        provider_name = "fake"

        def __init__(self, *args, **kwargs) -> None:
            self.available = True

        def chat(self, system_message: str, user_message: str) -> str:
            return "Try restarting the router first."

    monkeypatch.setattr(llm_mod, "LLM", FakeLLM)
    config = replace(
        GhostChimeraConfig.from_env(),
        state_dir=tmp_path,
        memory_db=tmp_path / "m.sqlite3",
        audit_file=tmp_path / "a.json",
    )
    server = GatewayServer(host="127.0.0.1", port=19175, http_port=19176, config=config)
    register_connector_routes(server, tmp_path)
    server.start()
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:19176/api/stealth/ghost-write",
            data=json.dumps({"prompt_context": "The customer cannot connect."}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        assert data["ok"] is True
        assert "router" in data["ghost_suggestion"]
    finally:
        server.stop()
