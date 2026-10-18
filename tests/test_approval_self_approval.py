"""Approvals: requester != decider, server-side actor (redteam P1-3)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import replace

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.console_routes import register_connector_routes

OPERATOR = "operator-token-0123456789abcdef"
AGENT = "agent-token-0123456789abcdef"
ACTION = {"provider": "github", "method": "DELETE", "url": "https://api.github.com/repos/v/r"}


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTCHIMERA_AGENT_TOKEN", AGENT)
    monkeypatch.delenv("GHOSTCHIMERA_ALLOW_SELF_APPROVAL", raising=False)
    config = replace(
        GhostChimeraConfig.from_env(), state_dir=tmp_path, memory_db=tmp_path / "m.sqlite3", audit_file=tmp_path / "a"
    )
    srv = GatewayServer(host="127.0.0.1", port=0, http_port=0, config=config)
    register_connector_routes(srv, tmp_path, auth="token", token=OPERATOR)
    srv.start()
    try:
        yield f"http://127.0.0.1:{srv._http_server.server_address[1]}", tmp_path  # type: ignore[union-attr]
    finally:
        srv.stop()


def _post(url: str, payload: dict, tok: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Gateway-Token": tok},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_redteam_poc_self_approval_with_spoofed_actor_is_refused(server) -> None:
    base, _ = server
    _, created = _post(base + "/api/auth/approvals/request", {**ACTION, "requested_by": "agent"}, OPERATOR)
    assert created["ok"] is True
    _, decided = _post(
        base + "/api/auth/approvals/decide", {"id": created["id"], "approved": True, "actor": "agent"}, OPERATOR
    )
    assert decided["ok"] is False and "self-approval" in decided["error"]


def test_agent_token_can_request_but_never_decide(server) -> None:
    base, _ = server
    status, created = _post(base + "/api/auth/approvals/request", ACTION, AGENT)
    assert status == 200 and created["ok"] is True
    status, by_agent = _post(base + "/api/auth/approvals/decide", {"id": created["id"], "approved": True}, AGENT)
    # Rejected by the route's operator-only auth (401); the handler refuses too.
    assert status == 401 or (by_agent.get("ok") is False and "never decide" in by_agent.get("error", ""))
    # The human operator (a different principal) decides; actor recorded server-side.
    _, by_operator = _post(
        base + "/api/auth/approvals/decide",
        {"id": created["id"], "approved": True, "actor": "CEO <script>alert(1)</script>"},
        OPERATOR,
    )
    assert by_operator == {"ok": True, "id": created["id"], "state": "APPROVED"}
    _, audit = _post(base + "/api/auth/audit/recent", {"limit": 10}, OPERATOR)
    approved = [e for e in audit["entries"] if e["event"] == "approval.approved"][0]
    detail = approved.get("detail") or {}
    assert detail.get("actor") == "operator"
    assert "<script>" not in json.dumps(approved)


def test_bad_token_cannot_request(server) -> None:
    base, _ = server
    status, _ = _post(base + "/api/auth/approvals/request", ACTION, "wrong")
    assert status == 401


def test_human_console_request_can_still_be_approved(server) -> None:
    base, _ = server
    _, created = _post(base + "/api/auth/approvals/request", ACTION, OPERATOR)
    _, decided = _post(base + "/api/auth/approvals/decide", {"id": created["id"], "approved": True}, OPERATOR)
    assert decided["state"] == "APPROVED"


def test_self_approval_opt_in_and_digest_binding(server, monkeypatch) -> None:
    base, _ = server
    monkeypatch.setenv("GHOSTCHIMERA_ALLOW_SELF_APPROVAL", "1")
    _, created = _post(base + "/api/auth/approvals/request", {**ACTION, "requested_by": "agent"}, OPERATOR)
    _, wrong = _post(
        base + "/api/auth/approvals/decide", {"id": created["id"], "approved": True, "digest": "0" * 64}, OPERATOR
    )
    assert wrong["ok"] is False and "digest" in wrong["error"]
    _, ok = _post(
        base + "/api/auth/approvals/decide",
        {"id": created["id"], "approved": True, "digest": created["digest"]},
        OPERATOR,
    )
    assert ok["state"] == "APPROVED"
