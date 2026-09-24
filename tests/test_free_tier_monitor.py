"""Free-tier daily monitor: probing, snapshot, daemon. No real network."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.console_routes import register_connector_routes
from ghostchimera.model_layer.free_tier_monitor import FreeTierMonitor, probe_provider

_PORT = [20273]


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


def _fake_fetch(payload=None, error=None):
    def fetch(url, *, api_key="", timeout=15.0):
        if error is not None:
            raise error
        return payload if payload is not None else {"data": [{"id": "model-a"}, {"id": "model-b"}]}

    return fetch


# -- probing ----------------------------------------------------------------------------------
def test_probe_success_extracts_ids(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "q")
    out = probe_provider("groq", fetch_fn=_fake_fetch())
    assert out["ok"] is True and out["models_seen"] == ["model-a", "model-b"]
    assert out["latency_s"] >= 0


def test_probe_skipped_without_key(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    out = probe_provider("groq", fetch_fn=_fake_fetch())
    assert out["ok"] is False and out.get("skipped") is True


def test_probe_failure_reported_not_raised() -> None:
    out = probe_provider("pollinations", fetch_fn=_fake_fetch(error=TimeoutError("slow")))
    assert out["ok"] is False and "TimeoutError" in out["error"]


def test_probe_unknown_provider() -> None:
    out = probe_provider("nope", fetch_fn=_fake_fetch())
    assert out["ok"] is False


# -- snapshot + daemon ------------------------------------------------------------------------------
def test_check_now_persists_snapshot(tmp_path, monkeypatch) -> None:
    import ghostchimera.model_layer.free_tier_monitor as monitor_mod

    monkeypatch.setattr(
        monitor_mod, "probe_provider", lambda provider, fetch_fn=None: {"provider": provider, "ok": True}
    )
    monitor = FreeTierMonitor(tmp_path)
    try:
        out = monitor.check_now()
        assert out["ok"] is True and out["tiers"]["groq"]["ok"] is True
        status = monitor.status()
        assert status["stale"] is False and status["tiers"]["groq"]["ok"] is True
    finally:
        monitor.stop()


def test_enabled_toggle(tmp_path) -> None:
    monitor = FreeTierMonitor(tmp_path)
    try:
        assert monitor.is_enabled() is True
        assert monitor.set_enabled(False) == {"ok": True, "enabled": False}
        assert monitor.is_enabled() is False
        assert monitor.ensure_running() is False
        assert monitor.set_enabled(True)["enabled"] is True
    finally:
        monitor.stop()


def test_daemon_starts_and_stops(tmp_path) -> None:
    monitor = FreeTierMonitor(tmp_path, interval_s=60)
    try:
        assert monitor.ensure_running() is True
        assert monitor.ensure_running() is True
    finally:
        monitor.stop()


# -- routes --------------------------------------------------------------------------------------------
def test_free_tiers_routes(tmp_path, monkeypatch) -> None:
    import ghostchimera.model_layer.free_tier_monitor as monitor_mod

    monkeypatch.setattr(
        monitor_mod, "probe_provider", lambda provider, fetch_fn=None: {"provider": provider, "ok": True}
    )
    server = _server(tmp_path)
    try:
        base = _base(server)
        status = _post(base + "/api/auth/free-tiers", {})
        assert status["ok"] is True and status["enabled"] is True
        checked = _post(base + "/api/auth/free-tiers", {"action": "check"})
        assert checked["ok"] is True and checked["tiers"]["groq"]["ok"] is True
        usage = _post(base + "/api/auth/usage/summary", {})
        assert usage["ok"] is True and "free_tiers_live" in usage
        assert usage["free_tiers_live"]["tiers"]["groq"]["ok"] is True
        assert _post(base + "/api/auth/free-tiers", {"action": "disable"})["enabled"] is False
    finally:
        server.stop()
