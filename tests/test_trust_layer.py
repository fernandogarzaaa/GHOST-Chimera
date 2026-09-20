"""Trust layer: hash-bound approvals, write gate, redacted audit. No real network."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.action_approvals import (
    ActionApprovalError,
    ActionApprovalStore,
    action_digest,
)
from ghostchimera.connectors.audit_trail import AuditTrail
from ghostchimera.connectors.auth_engine import CustomAuthEngine, NeedsApproval
from ghostchimera.connectors.console_routes import register_connector_routes

_PORT = [19573]


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


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


# -- digest -----------------------------------------------------------------------------------
def test_digest_stable_and_binding() -> None:
    a = action_digest("slack", "post", "https://slack.com/api/chat.postMessage", {"text": "hi"}, "post")
    assert a == action_digest("slack", "POST", "https://slack.com/api/chat.postMessage", {"text": "hi"}, "post")
    assert a != action_digest("slack", "POST", "https://slack.com/api/chat.postMessage", {"text": "HI"}, "post")
    assert a != action_digest("slack", "POST", "https://slack.com/api/chat.delete", {"text": "hi"}, "post")
    assert a != action_digest("slack", "POST", "https://slack.com/api/chat.postMessage", {"text": "hi"}, "delete")
    assert a != action_digest("slack", "GET", "https://slack.com/api/chat.postMessage", {"text": "hi"}, "post")


def test_digest_rejects_huge_body() -> None:
    with pytest.raises(ActionApprovalError, match="too large"):
        action_digest("x", "POST", "https://x.com/2/tweets", {"text": "y" * 9000})


# -- store --------------------------------------------------------------------------------------
def _req(store, **kw):
    args = {
        "entity_id": "u",
        "provider": "slack",
        "method": "POST",
        "url": "https://slack.com/api/chat.postMessage",
        "data": {"text": "hi"},
    }
    args.update(kw)
    return store.request(**args)


def test_approve_consume_single_use(tmp_path) -> None:
    store = ActionApprovalStore(tmp_path)
    try:
        created = _req(store, summary="say hi")
        assert created["state"] == "PENDING"
        decided = store.decide(created["id"], approved=True, actor="op")
        assert decided == {"id": created["id"], "state": "APPROVED"}
        kwargs = {
            "entity_id": "u",
            "provider": "slack",
            "method": "POST",
            "url": "https://slack.com/api/chat.postMessage",
            "data": {"text": "hi"},
        }
        assert store.consume(approval_id=created["id"], **kwargs) is True
        assert store.consume(approval_id=created["id"], **kwargs) is False  # burned
    finally:
        store.close()


def test_consume_rejects_tampered_action(tmp_path) -> None:
    store = ActionApprovalStore(tmp_path)
    try:
        created = _req(store)
        store.decide(created["id"], approved=True, actor="op")
        assert (
            store.consume(
                entity_id="u",
                provider="slack",
                method="POST",
                url="https://slack.com/api/chat.postMessage",
                data={"text": "EVIL"},
                approval_id=created["id"],
            )
            is False
        )
        assert (
            store.consume(
                entity_id="u",
                provider="slack",
                method="POST",
                url="https://slack.com/api/chat.delete",
                data={"text": "hi"},
                approval_id=created["id"],
            )
            is False
        )
        assert (
            store.consume(
                entity_id="other",
                provider="slack",
                method="POST",
                url="https://slack.com/api/chat.postMessage",
                data={"text": "hi"},
                approval_id=created["id"],
            )
            is False
        )
    finally:
        store.close()


def test_deny_and_expiry(tmp_path) -> None:
    store = ActionApprovalStore(tmp_path)
    try:
        denied = _req(store)
        assert store.decide(denied["id"], approved=False, actor="op")["state"] == "DENIED"
        assert (
            store.consume(
                entity_id="u",
                provider="slack",
                method="POST",
                url="https://slack.com/api/chat.postMessage",
                data={"text": "hi"},
                approval_id=denied["id"],
            )
            is False
        )
        expiring = _req(store, ttl_s=1.0)
        import time

        time.sleep(1.1)
        assert store.decide(expiring["id"], approved=True, actor="op")["state"] == "EXPIRED"
        with pytest.raises(ActionApprovalError, match="unknown"):
            store.decide("act-nope", approved=True, actor="op")
        with pytest.raises(ActionApprovalError, match="reads"):
            store.request("u", "slack", "GET", "https://x/", None)
    finally:
        store.close()


def test_pending_and_sweep(tmp_path) -> None:
    store = ActionApprovalStore(tmp_path)
    try:
        _req(store)
        assert len(store.pending("u")) == 1
        assert store.pending("other") == []
        assert store.sweep() == 0
    finally:
        store.close()


# -- engine gate ----------------------------------------------------------------------------------
def _proxy_transport(calls):
    def transport(method, url, payload):
        calls.append((method, url))
        if method == "PROXY":
            return 200, json.dumps({"ok": True}).encode()
        return 200, json.dumps({"access_token": "at-1", "expires_in": 3600}).encode()

    return transport


def _seed_token(engine, provider="slack"):
    engine._store_token(provider, "u", {"access_token": "at-1", "expires_in": 3600})


def test_write_gate_defaults_off(tmp_path) -> None:
    engine = CustomAuthEngine(tmp_path)
    try:
        assert engine.write_approval_required() is False
    finally:
        engine.close()


def test_write_gate_env_on(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_REQUIRE_WRITE_APPROVAL", "1")
    engine = CustomAuthEngine(tmp_path)
    try:
        assert engine.write_approval_required() is True
    finally:
        engine.close()


def test_gated_write_needs_approval_then_burns(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_REQUIRE_WRITE_APPROVAL", "1")
    calls: list = []
    engine = CustomAuthEngine(tmp_path, transport=_proxy_transport(calls))
    try:
        _seed_token(engine)
        url = "https://slack.com/api/chat.postMessage"
        with pytest.raises(NeedsApproval):
            engine.proxy_request("slack", "u", "POST", url, data={"text": "hi"})
        created = engine.request_action_approval("u", "slack", "POST", url, {"text": "hi"}, summary="say hi")
        decided = engine.decide_action_approval(created["id"], approved=True, actor="op")
        assert decided["state"] == "APPROVED"
        out = engine.proxy_request("slack", "u", "POST", url, data={"text": "hi"}, approval_id=created["id"])
        assert out == {"ok": True}
        with pytest.raises(NeedsApproval):  # single-use: burned
            engine.proxy_request("slack", "u", "POST", url, data={"text": "hi"}, approval_id=created["id"])
    finally:
        engine.close()


def test_gated_reads_pass_without_approval(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_REQUIRE_WRITE_APPROVAL", "1")
    calls: list = []
    engine = CustomAuthEngine(tmp_path, transport=_proxy_transport(calls))
    try:
        _seed_token(engine)
        out = engine.proxy_request("slack", "u", "GET", "https://slack.com/api/conversations.list")
        assert out == {"ok": True}
    finally:
        engine.close()


def test_ungated_writes_pass_by_default(tmp_path) -> None:
    calls: list = []
    engine = CustomAuthEngine(tmp_path, transport=_proxy_transport(calls))
    try:
        _seed_token(engine)
        out = engine.proxy_request("slack", "u", "POST", "https://slack.com/api/chat.postMessage", data={"text": "hi"})
        assert out == {"ok": True}
    finally:
        engine.close()


# -- audit -----------------------------------------------------------------------------------------
def test_audit_appends_and_redacts(tmp_path) -> None:
    audit = AuditTrail(tmp_path)
    audit.record(
        "proxy.call",
        entity_id="u",
        provider="slack",
        detail={
            "method": "POST",
            "url": "https://slack.com/api/x?y=1",
            "data": {"text": "hi", "token": "xoxb-secret", "password": "pw"},
        },
    )
    entries = audit.recent()
    assert len(entries) == 1
    detail = entries[0]["detail"]
    assert detail["data"]["token"] == "[redacted]"
    assert "slack.com" in detail["url"] and "y=1" not in detail["url"]
    assert entries[0]["event"] == "proxy.call"


def test_engine_audit_trail_written(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_REQUIRE_WRITE_APPROVAL", "1")
    calls: list = []
    engine = CustomAuthEngine(tmp_path, transport=_proxy_transport(calls))
    try:
        _seed_token(engine)
        url = "https://slack.com/api/chat.postMessage"
        created = engine.request_action_approval("u", "slack", "POST", url, {"text": "hi"})
        engine.decide_action_approval(created["id"], approved=True, actor="op")
        engine.proxy_request("slack", "u", "POST", url, data={"text": "hi"}, approval_id=created["id"])
        events = [e["event"] for e in engine.audit.recent(limit=20)]
        assert "token.stored" in events
        assert "approval.requested" in events
        assert "approval.approved" in events
        assert "approval.consumed" in events
        assert "proxy.call" in events
    finally:
        engine.close()


# -- routes ------------------------------------------------------------------------------------------
def test_approval_routes_and_gate_and_audit(tmp_path, monkeypatch) -> None:
    import ghostchimera.control_plane.config as cfg

    fake = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", fake)
    server = _server(tmp_path)
    try:
        base = _base(server)
        gate = _post(base + "/api/auth/write-gate", {})
        assert gate == {"ok": True, "enabled": False}
        assert _post(base + "/api/auth/write-gate", {"enabled": True}) == {"ok": True, "enabled": True}
        assert _post(base + "/api/auth/write-gate", {}) == {"ok": True, "enabled": True}

        url = "https://slack.com/api/chat.postMessage"
        created = _post(
            base + "/api/auth/approvals/request",
            {
                "provider": "slack",
                "method": "POST",
                "url": url,
                "data": {"text": "hi"},
                "summary": "say hi",
            },
        )
        assert created["ok"] is True
        pending = _post(base + "/api/auth/approvals/pending", {})
        assert len(pending["approvals"]) == 1
        decided = _post(base + "/api/auth/approvals/decide", {"id": created["id"], "approved": True})
        assert decided == {"ok": True, "id": created["id"], "state": "APPROVED"}
        assert _post(base + "/api/auth/approvals/pending", {})["approvals"] == []
        assert _post(base + "/api/auth/approvals/decide", {"id": "act-nope", "approved": True})["ok"] is False

        audit = _post(base + "/api/auth/audit/recent", {"limit": 10})
        events = [e["event"] for e in audit["entries"]]
        assert "approval.requested" in events and "approval.approved" in events
    finally:
        server.stop()
