"""Automations: triggers, actions, run history, approvals. Fake transports only."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.automations import AutomationError, AutomationsEngine
from ghostchimera.connectors.console_routes import register_connector_routes

_PORT = [19773]


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


# -- validation -------------------------------------------------------------------------------
def test_create_validation(tmp_path) -> None:
    engine = AutomationsEngine(tmp_path)
    try:
        with pytest.raises(AutomationError, match="name and instruction"):
            engine.create(name="", instruction="x", trigger={"type": "cron", "cron": "0 8 * * *"})
        with pytest.raises(AutomationError, match="bad cron"):
            engine.create(name="n", instruction="i", trigger={"type": "cron", "cron": "not a cron"})
        with pytest.raises(AutomationError, match="trigger type"):
            engine.create(name="n", instruction="i", trigger={"type": "smoke"})
        with pytest.raises(AutomationError, match="vault key"):
            engine.create(name="n", instruction="i", trigger={"type": "email"})
        with pytest.raises(AutomationError, match="action type"):
            engine.create(
                name="n", instruction="i", trigger={"type": "cron", "cron": "0 8 * * *"}, action={"type": "nuke"}
            )
        with pytest.raises(AutomationError, match="http"):
            engine.create(
                name="n",
                instruction="i",
                trigger={"type": "cron", "cron": "0 8 * * *"},
                action={"type": "webhook", "url": "ftp://x"},
            )
        with pytest.raises(AutomationError, match="notify"):
            engine.create(name="n", instruction="i", trigger={"type": "cron", "cron": "0 8 * * *"}, notify="smoke")
    finally:
        engine.stop()


def test_create_cron_and_lifecycle(tmp_path) -> None:
    engine = AutomationsEngine(tmp_path)
    try:
        created = engine.create(name="Brief", instruction="summarize", trigger={"type": "cron", "cron": "0 8 * * *"})
        assert created["enabled"] is True and created["next_run_at"] > 0
        assert len(engine.list()) == 1
        engine.set_enabled(created["id"], enabled=False)
        assert engine.list()[0]["enabled"] is False
        with pytest.raises(AutomationError, match="paused"):
            engine.fire(created["id"])
        assert engine.delete(created["id"]) is True
        assert engine.list() == []
        with pytest.raises(AutomationError, match="unknown"):
            engine.fire(created["id"])
    finally:
        engine.stop()


# -- runs -----------------------------------------------------------------------------------------
def test_log_run_and_history(tmp_path) -> None:
    engine = AutomationsEngine(tmp_path)
    try:
        created = engine.create(name="Log", instruction="watch", trigger={"type": "cron", "cron": "0 8 * * *"})
        run = engine.fire(created["id"])
        assert run["status"] == "complete"
        history = engine.runs(created["id"])
        assert len(history) == 1 and history[0]["run_id"] == run["run_id"]
        child = engine.fire(created["id"], parent_run_id=run["run_id"], note="again")
        assert child["parent_run_id"] == run["run_id"]
        assert len(engine.runs()) == 2
    finally:
        engine.stop()


def test_webhook_run_fake_transport(tmp_path, monkeypatch) -> None:
    seen = {}

    class _Resp:
        status = 200

        def read(self):
            return b'{"ok":true}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, **kwargs):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    engine = AutomationsEngine(tmp_path)
    try:
        created = engine.create(
            name="Hook",
            instruction="push",
            trigger={"type": "cron", "cron": "0 8 * * *"},
            action={"type": "webhook", "url": "https://example.com/hook"},
        )
        run = engine.fire(created["id"])
        assert run["status"] == "complete"
        assert seen["url"] == "https://example.com/hook"
        assert seen["body"]["automation"] == "Hook"
    finally:
        engine.stop()


def test_connector_write_parks_and_executes(tmp_path, monkeypatch) -> None:
    from ghostchimera.connectors.auth_engine import CustomAuthEngine

    executed = []
    monkeypatch.setattr(
        CustomAuthEngine, "proxy_request", lambda self, *a, **k: executed.append((a, k)) or {"ok": True}
    )
    engine = AutomationsEngine(tmp_path)
    try:
        created = engine.create(
            name="Post",
            instruction="announce",
            trigger={"type": "cron", "cron": "0 8 * * *"},
            action={
                "type": "connector_write",
                "provider": "slack",
                "method": "POST",
                "url": "https://slack.com/api/chat.postMessage",
                "data": {"text": "hi"},
            },
        )
        run = engine.fire(created["id"])
        assert run["status"] == "awaiting-approval"
        approval_id = run["result"]["approval_id"]
        auth_engine = CustomAuthEngine(tmp_path)
        try:
            auth_engine.decide_action_approval(approval_id, approved=True, actor="op")
        finally:
            auth_engine.close()
        done = engine.execute_approved(run["run_id"], approval_id)
        assert done["status"] == "complete" and done["parent_run_id"] == run["run_id"]
        assert len(executed) == 1
        with pytest.raises(AutomationError, match="already executed"):
            engine.execute_approved(run["run_id"], approval_id)
    finally:
        engine.stop()


# -- email trigger ----------------------------------------------------------------------------------
def test_email_trigger_match_and_dedup(tmp_path, monkeypatch) -> None:
    import ghostchimera.integrations.mail_basic as mail_basic
    from ghostchimera.connectors.auth_engine import CustomAuthEngine

    messages = [
        {"uid": "7", "from": "Boss <boss@x.com>", "subject": "URGENT: deploy", "snippet": "go"},
        {"uid": "8", "from": "News <n@x.com>", "subject": "Newsletter", "snippet": "hi"},
    ]
    monkeypatch.setattr(mail_basic, "fetch_inbox", lambda *a, **k: {"ok": True, "messages": messages})
    auth_engine = CustomAuthEngine(tmp_path)
    try:
        auth_engine.save_custom_key(
            "console-user", "app_password", "Gmail", "abcd efgh ijkl mnop", provider_hint="user@gmail.com"
        )
    finally:
        auth_engine.close()
    engine = AutomationsEngine(tmp_path)
    try:
        engine.create(
            name="Boss mail",
            instruction="flag it",
            trigger={"type": "email", "label": "Gmail", "sender": "boss@x.com", "subject": "urgent"},
        )
        first = engine.tick()
        assert len(first) == 1
        assert first[0]["trigger"]["uid"] == "7"
        second = engine.tick()
        assert second == []  # UID 7 seen; UID 8 filtered out
    finally:
        engine.stop()


def test_email_trigger_missing_key_is_quiet(tmp_path) -> None:
    engine = AutomationsEngine(tmp_path)
    try:
        engine.create(name="Mail", instruction="x", trigger={"type": "email", "label": "Nope"})
        assert engine.tick() == []
    finally:
        engine.stop()


def test_cron_tick_fires_due(tmp_path) -> None:
    engine = AutomationsEngine(tmp_path)
    try:
        created = engine.create(name="Due", instruction="go", trigger={"type": "cron", "cron": "0 8 * * *"})
        with engine._lock:
            engine._find_mutable(created["id"])["next_run_at"] = 0.0
            engine._save()
        runs = engine.tick()
        assert len(runs) == 1 and runs[0]["status"] == "complete"
        assert engine.tick() == []  # next run rescheduled in the future
    finally:
        engine.stop()


# -- routes -------------------------------------------------------------------------------------------
def test_automation_routes(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        base = _base(server)
        listed = _post(base + "/api/auth/automations", {})
        assert listed["ok"] is True and listed["automations"] == []
        created = _post(
            base + "/api/auth/automations/create",
            {
                "name": "R",
                "instruction": "watch it",
                "trigger": {"type": "cron", "cron": "0 9 * * *"},
            },
        )
        assert created["ok"] is True
        assert (
            _post(
                base + "/api/auth/automations/create", {"name": "R", "instruction": "x", "trigger": {"type": "nope"}}
            )["ok"]
            is False
        )
        fired = _post(base + "/api/auth/automations/fire", {"id": created["id"]})
        assert fired["ok"] is True and fired["run"]["status"] == "complete"
        runs = _post(base + "/api/auth/automations/runs", {"id": created["id"]})
        assert len(runs["runs"]) == 1
        continued = _post(
            base + "/api/auth/automations/fire",
            {"id": created["id"], "parent_run_id": fired["run"]["run_id"], "note": "again"},
        )
        assert continued["run"]["parent_run_id"] == fired["run"]["run_id"]
        paused = _post(base + "/api/auth/automations/set", {"id": created["id"], "enabled": False})
        assert paused["enabled"] is False
        assert _post(base + "/api/auth/automations/fire", {"id": created["id"]})["ok"] is False
        assert _post(base + "/api/auth/automations/set", {"id": created["id"], "delete": True})["deleted"] is True
        assert _post(base + "/api/auth/automations", {})["automations"] == []
    finally:
        server.stop()
