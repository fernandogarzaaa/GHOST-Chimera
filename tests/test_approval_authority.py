"""Approval authority unification: stealth queue write-through, Trust linkage,
one Trust surface. No network."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.action_approvals import ActionApprovalStore
from ghostchimera.connectors.console_routes import register_connector_routes
from ghostchimera.stealth.approvals import ApprovalQueue
from ghostchimera.trust_runtime import TrustRuntimeStore

_PORT = [20073]


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


# -- write-through ----------------------------------------------------------------------------
def test_queue_without_authority_unchanged(tmp_path) -> None:
    queue = ApprovalQueue()
    assert queue._authority is None
    item = queue.request("do it", source_kind="manual")
    assert item is not None and "authority_id" not in item.details
    assert queue.approve(item.id, "op") is True


def test_request_mirrors_to_durable_store(tmp_path) -> None:
    store = ActionApprovalStore(tmp_path)
    try:
        queue = ApprovalQueue()
        queue.attach_authority(store)
        item = queue.request("Ship it", source_kind="proposal", source_id="p1", workflow="release")
        assert item is not None
        authority_id = item.details.get("authority_id", "")
        assert authority_id.startswith("act-")
        described = store.describe(authority_id)
        assert described is not None and described["state"] == "PENDING"
        assert described["provider"] == "stealth"
    finally:
        store.close()


def test_decisions_mirror_both_ways(tmp_path) -> None:
    store = ActionApprovalStore(tmp_path)
    try:
        queue = ApprovalQueue()
        queue.attach_authority(store)
        item = queue.request("Ship it", source_kind="manual")
        assert item is not None
        authority_id = item.details["authority_id"]
        # Loop-side decision lands in the durable record.
        assert queue.approve(item.id, "op") is True
        assert store.describe(authority_id)["state"] == "APPROVED"
        # Trust-UI-side decision syncs back into memory.
        item2 = queue.request("Other", source_kind="manual")
        assert item2 is not None
        store.decide(item2.details["authority_id"], approved=False, actor="trust-ui")
        assert queue.sync() == 1
        assert queue.get(item2.id).state.value == "denied"
    finally:
        store.close()


def test_sync_expiry(tmp_path) -> None:
    store = ActionApprovalStore(tmp_path)
    try:
        queue = ApprovalQueue()
        queue.attach_authority(store)
        item = queue.request("Ship it", source_kind="manual", ttl_s=1.0)
        assert item is not None
        import time

        time.sleep(1.1)
        assert queue.sync() >= 1
        assert queue.get(item.id).state.value == "expired"
    finally:
        store.close()


# -- TrustRuntime linkage -----------------------------------------------------------------------
def test_checkpoint_carries_authority_id(tmp_path) -> None:
    store = TrustRuntimeStore(tmp_path)
    run = store.create_run(objective="demo")
    approval = store.create_approval(run["run_id"], summary="go?", authority_id="act-abc123")
    assert approval["authority_id"] == "act-abc123"
    plain = store.create_approval(run["run_id"], summary="other")
    assert plain["authority_id"] == ""


def test_resolve_cascades_to_authority(tmp_path) -> None:
    action_store = ActionApprovalStore(tmp_path)
    try:
        created = action_store.request("console-user", "slack", "POST", "https://slack.com/api/x", {"a": 1})
        trust = TrustRuntimeStore(tmp_path)
        run = trust.create_run(objective="demo")
        approval = trust.create_approval(run["run_id"], summary="post?", authority_id=created["id"])
        resolved = trust.resolve_approval(approval["approval_id"], "approved", reviewer="op", authority=action_store)
        assert resolved["ok"] is True
        assert "authority_error" not in resolved
        assert action_store.describe(created["id"])["state"] == "APPROVED"
    finally:
        action_store.close()


def test_resolve_without_authority_unchanged(tmp_path) -> None:
    trust = TrustRuntimeStore(tmp_path)
    run = trust.create_run(objective="demo")
    approval = trust.create_approval(run["run_id"], summary="go?")
    resolved = trust.resolve_approval(approval["approval_id"], "denied", reviewer="op")
    assert resolved["ok"] is True


# -- unified Trust surface --------------------------------------------------------------------------
def test_pending_merges_stealth_asks(tmp_path) -> None:
    from ghostchimera.connectors.stealth_service import get_service_loop

    server = _server(tmp_path)
    try:
        loop = get_service_loop(tmp_path)
        item = loop.approvals.request("Stealth ask", source_kind="intervention", source_id="i1")
        assert item is not None
        data = _post(_base(server) + "/api/auth/approvals/pending", {})
        assert data["ok"] is True
        stealth_items = [a for a in data["approvals"] if a.get("source") == "stealth"]
        assert any(a["id"] == item.id for a in stealth_items)
        decided = _post(_base(server) + "/api/auth/approvals/decide", {"id": item.id, "approved": True})
        assert decided == {"ok": True, "id": item.id, "state": "approved", "source": "stealth"}
        remaining = _post(_base(server) + "/api/auth/approvals/pending", {})["approvals"]
        assert all(a.get("id") != item.id for a in remaining)
    finally:
        server.stop()
