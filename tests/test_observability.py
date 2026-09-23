"""Observability: ledger extensions, usage route, eval history. No network."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.console_routes import register_connector_routes
from ghostchimera.model_layer.cost_monitor import CostLedger

_PORT = [20173]


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


# -- ledger extensions ----------------------------------------------------------------
def test_record_tracks_tokens_latency_daily() -> None:
    ledger = CostLedger()
    ledger.record("openai", "gpt-4o-mini", input_tokens=100, output_tokens=50, latency_s=1.5)
    ledger.record("openai", "gpt-4o-mini", input_tokens=200, output_tokens=50, latency_s=3.5)
    assert ledger.tokens("openai") == {"in": 300, "out": 100}
    stats = ledger.latency_stats("openai")
    assert stats["calls"] == 2 and stats["max_s"] == 3.5
    assert 1.5 <= stats["p50_s"] <= 3.5
    daily = ledger.daily_summary()
    assert daily["totals"]["calls"] == 2
    assert daily["providers"]["openai"]["in"] == 300


def test_latency_bounded_samples() -> None:
    ledger = CostLedger()
    for _ in range(300):
        ledger.record("x", "m", input_tokens=1, output_tokens=1, latency_s=0.1)
    assert ledger.latency_stats("x")["calls"] == 200


def test_save_load_round_trip_with_new_sections(tmp_path) -> None:
    ledger = CostLedger()
    ledger.record("groq", "m", input_tokens=1000, output_tokens=500, latency_s=0.4)
    ledger.set_budget("groq", 5.0)
    path = ledger.save(tmp_path / "costs.json")
    loaded = CostLedger.load(path)
    assert loaded.tokens("groq") == {"in": 1000, "out": 500}
    assert loaded.daily_summary()["totals"]["calls"] == 1
    assert loaded.spend("groq") == ledger.spend("groq")


def test_load_legacy_file_without_new_sections(tmp_path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"spend_usd": {"a": 1.0}, "calls": {"a": 2}}), encoding="utf-8")
    loaded = CostLedger.load(path)
    assert loaded.spend("a") == 1.0 and loaded.calls("a") == 2
    assert loaded.tokens("a") == {"in": 0, "out": 0}
    assert loaded.daily_summary()["totals"] == {"spend": 0.0, "calls": 0, "in": 0, "out": 0}


# -- routes -----------------------------------------------------------------------------------
def test_usage_summary_shape(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        data = _post(_base(server) + "/api/auth/usage/summary", {})
        assert data["ok"] is True
        # The process ledger is shared (router traffic lands here too), so
        # assert shape and content, not emptiness.
        assert data["total_usd"] >= 0.0
        totals = data["daily"]["totals"]
        assert set(totals) == {"spend", "calls", "in", "out"}
        assert isinstance(data["providers"], dict)
        quotas = {q["tier"]: q for q in data["free_quotas"]}
        assert "gemini-flash-lite" in quotas
        lite = quotas["gemini-flash-lite"]
        assert lite["requests_per_day"] == 1500 and lite["trains_on_data"] is True
        assert any("trains_on_data" in q for q in data["free_quotas"])
    finally:
        server.stop()


def test_evals_unknown_suite_rejected(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        data = _post(_base(server) + "/api/auth/evals/run", {"suite": "nope"})
        assert data["ok"] is False and "unknown suite" in data["error"]
        history = _post(_base(server) + "/api/auth/evals/history", {})
        assert history == {"ok": True, "runs": []}
    finally:
        server.stop()


def test_evals_run_recorded_with_mock(tmp_path, monkeypatch) -> None:
    import ghostchimera.evals.runner as runner

    monkeypatch.setattr(runner, "run_suite", lambda name: {"ok": True, "passed": 2, "failed": 1})
    server = _server(tmp_path)
    try:
        base = _base(server)
        done = _post(base + "/api/auth/evals/run", {"suite": "smoke"})
        assert done["ok"] is True
        assert done["run"]["passed"] == 2 and done["run"]["failed"] == 1
        history = _post(base + "/api/auth/evals/history", {})
        assert len(history["runs"]) == 1
        assert history["runs"][0]["suite"] == "smoke"
    finally:
        server.stop()
