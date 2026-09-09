"""Nango + agent-prompt tests: offline, no secrets, deterministic."""

from __future__ import annotations

import json

import pytest

from ghostchimera.connectors import NANGO_CATALOG, NangoClient, NangoError, get_preset
from ghostchimera.connectors.nango import NangoAction
from ghostchimera.stealth import (
    AgentActionType,
    AutonomyLevel,
    Decision,
    GhostPolicy,
    gate_agent_action,
    parse_agent_output,
    render_system_prompt,
)


def test_nango_catalog_covers_all_requested_providers() -> None:
    for key in ("google-mail", "slack", "zendesk", "freshdesk", "gorgias",
                "hubspot", "salesforce", "notion", "airtable",
                "hubstaff", "time-doctor", "github", "linkedin"):
        assert key in NANGO_CATALOG, f"missing {key}"
    cats = {p.category for p in NANGO_CATALOG.values()}
    assert {"comms", "support", "crm", "productivity", "workforce"} <= cats


def test_nango_oauth_presets_cover_new_providers() -> None:
    for provider in ("zendesk", "freshdesk", "gorgias", "hubspot",
                     "salesforce", "airtable", "hubstaff", "time-doctor"):
        preset = get_preset(provider)
        assert preset.authorize_url.startswith("https://")
        assert preset.token_url.startswith("https://")


def test_nango_client_requires_secret() -> None:
    with pytest.raises(NangoError):
        NangoClient(secret_key="", opener=None)


def _fake_opener(calls: list):
    def opener(method: str, url: str, body):
        calls.append((method, url))
        if url.endswith("/connection") or "/connection?" in url:
            return 200, json.dumps({"connections": [{"connection_id": "va_1"}]}).encode()
        if "/connection/va_1" in url and method == "GET":
            return 200, json.dumps({"connection_id": "va_1", "provider": "slack"}).encode()
        if "/proxy" in url:
            return 200, json.dumps({"ok": True, "ts": "123"}).encode()
        return 200, b"{}"

    return opener


def test_nango_proxy_and_connections_offline() -> None:
    calls: list = []
    client = NangoClient(secret_key="test-secret", opener=_fake_opener(calls))
    result = client.proxy(method="POST", endpoint="/chat.postMessage",
                          provider_config_key="slack", connection_id="va_1",
                          data={"channel": "#ops", "text": "hi"})
    assert result["ok"] is True
    method, url = calls[0]
    assert "provider_config_key=slack" in url and "connection_id=va_1" in url
    assert "test-secret" not in url  # secret travels in headers only
    conn = client.get_connection("slack", "va_1")
    assert conn["connection_id"] == "va_1"
    assert client.list_connections(provider_config_key="slack") == [{"connection_id": "va_1"}]
    assert client.delete_connection("slack", "va_1") is True
    with pytest.raises(NangoError):
        client.proxy(method="GET", endpoint="/x", provider_config_key="nope", connection_id="c")


def test_nango_frontend_session_never_leaks_secret() -> None:
    client = NangoClient(secret_key="super-secret", public_key="pub", opener=lambda *a: (200, b"{}"))
    session = client.frontend_session(provider_config_key="slack", connection_id="va_1")
    assert session["publicKey"] == "pub"
    assert "super-secret" not in json.dumps(session)


def test_nango_action_executes_via_proxy() -> None:
    calls: list = []
    client = NangoClient(secret_key="s", opener=_fake_opener(calls))
    action = NangoAction(provider="slack", endpoint="/chat.postMessage",
                         payload={"channel": "#ops", "text": "Update sent."})
    assert action.execute(client, connection_id="va_1")["ok"] is True


def test_nango_webhook_normalize_is_redacted() -> None:
    record = NangoClient.normalize_webhook({"type": "auth", "connectionId": "va_1",
                                            "providerConfigKey": "slack", "secret": "nope"})
    assert record["connectionId"] == "va_1"
    assert "secret" not in json.dumps(record)


def test_render_system_prompt_fills_all_slots() -> None:
    text = render_system_prompt(agent_name="Maria", integrations=["slack", "google-mail"],
                                event_payload={"from": "client@example.com", "intent": "reschedule"})
    assert "{{" not in text
    assert "Maria" in text and "slack, google-mail" in text
    assert '"intent": "reschedule"' in text


def test_parse_agent_output_valid_and_violations() -> None:
    good = parse_agent_output(json.dumps({
        "event_summary": "Client asks to reschedule.", "confidence_score": 0.95,
        "action_type": "AUTONOMOUS_EXECUTE",
        "actions": [{"provider": "google-mail", "endpoint": "/users/me/messages/send",
                     "payload": {"to": "c@example.com"}}]}))
    assert good.action_type == AgentActionType.AUTONOMOUS_EXECUTE
    assert good.confidence_score == 0.95
    with pytest.raises(ValueError):
        parse_agent_output("not json {")
    with pytest.raises(ValueError):
        parse_agent_output(json.dumps({"action_type": "FROBNICATE"}))
    with pytest.raises(ValueError):
        parse_agent_output(json.dumps({"action_type": "AUTONOMOUS_EXECUTE", "actions": []}))
    with pytest.raises(ValueError):
        parse_agent_output(json.dumps({"action_type": "NO_ACTION_NEEDED", "confidence_score": 9.9}))


def test_gate_agent_action_respects_autonomy() -> None:
    draft = parse_agent_output(json.dumps({"event_summary": "e", "confidence_score": 0.6,
                                           "action_type": "DRAFT_FOR_APPROVAL", "actions": []}))
    auto = parse_agent_output(json.dumps({"event_summary": "e", "confidence_score": 0.95,
                                          "action_type": "AUTONOMOUS_EXECUTE",
                                          "actions": [{"provider": "slack", "endpoint": "/x"}]}))
    idle = parse_agent_output(json.dumps({"event_summary": "e", "confidence_score": 0.2,
                                          "action_type": "NO_ACTION_NEEDED"}))
    assert gate_agent_action(idle) == Decision.NONE
    l1 = GhostPolicy(autonomy=AutonomyLevel.PREPARE)
    assert gate_agent_action(draft, l1) == Decision.PREPARE
    # L1/L2 must never autonomously execute external side effects.
    assert gate_agent_action(auto, l1) == Decision.ASK
    assert gate_agent_action(auto, GhostPolicy(autonomy=AutonomyLevel.INJECT)) == Decision.ASK
    l3 = GhostPolicy(autonomy=AutonomyLevel.ACT)
    assert gate_agent_action(auto, l3) == Decision.ACT
