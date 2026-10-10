"""Tests for the unified agent-status endpoint (Ghost Console Agent Status view).

Spins up a live GatewayServer with the connector routes registered and
exercises POST /api/auth/agent-status, which aggregates durable runs,
durable sessions, cron schedules, pending approvals, and usage into one
snapshot for the console's Agent Status tab.
"""

from __future__ import annotations

import json
import sys
import types
import urllib.request
from dataclasses import replace
from pathlib import Path

# croniter is a hard dependency of cron_scheduler but is not installed in
# this sandbox (no PyPI egress; CI installs it). Shim it for tests.
_croniter_mod = types.ModuleType("croniter")


class _FakeCroniter:
    def __init__(self, expr: str, start: float) -> None:
        self.expr = expr
        self.start = start

    def get_next(self) -> float:
        if self.expr.strip() == "* * * * *":
            return self.start + 60 - (self.start % 60)
        return self.start + 3600


_croniter_mod.croniter = _FakeCroniter
sys.modules.setdefault("croniter", _croniter_mod)

from ghostchimera.chimera_pilot.gateway_server import GatewayServer  # noqa: E402
from ghostchimera.config import GhostChimeraConfig  # noqa: E402
from ghostchimera.connectors.console_routes import register_connector_routes  # noqa: E402
from ghostchimera.trust_runtime import TrustRuntimeStore  # noqa: E402

_PORT = [19373]


def _server(tmp_path: Path) -> GatewayServer:
    _PORT[0] += 2
    ws_port, http_port = _PORT[0], _PORT[0] + 1
    config = GhostChimeraConfig.from_env()
    config = replace(config, state_dir=tmp_path, memory_db=tmp_path / "m.sqlite3", audit_file=tmp_path / "a.json")
    server = GatewayServer(host="127.0.0.1", port=ws_port, http_port=http_port, config=config)
    register_connector_routes(server, tmp_path, auth="open", token="")
    server.start()
    # start() may bump ports when the preferred ones are occupied; always use
    # the bound ports rather than the requested ones.
    server._test_http_port = server.http_port  # type: ignore[attr-defined]
    return server


def _post_status(server: GatewayServer) -> tuple[int, dict]:
    base = f"http://127.0.0.1:{server._test_http_port}"  # type: ignore[attr-defined]
    req = urllib.request.Request(
        base + "/api/auth/agent-status",
        data=json.dumps({}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.load(resp)
    except Exception as exc:
        code = getattr(exc, "code", 0) or 0
        try:
            return code, json.loads(exc.read().decode())
        except Exception:
            return code, {}


def _seed_state(tmp_path: Path) -> None:
    store = TrustRuntimeStore(tmp_path)
    store.create_run("summarize inbox", source="console", agent_name="ghost-chimera")
    store.save_session(
        {
            "session_id": "sess-1",
            "messages": [{"role": "user", "content": "hi"}],
            "message_count": 1,
            "total_tokens": 42,
            "last_active": 1700000000.0,
        }
    )
    # Seed the persisted cron state directly (plain JSON): the endpoint reads
    # it through CronScheduler, so no scheduler import is needed here.
    (tmp_path / "cron_jobs.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "saved_at": 1700000000.0,
                "jobs": {
                    "cron-1": {
                        "id": "cron-1",
                        "name": "nightly-audit",
                        "cron_expression": "0 2 * * *",
                        "objective": "audit trust ledger",
                        "task_kind": "reasoning",
                        "enabled": True,
                        "next_run": 1700003600.0,
                        "last_run": 1699990000.0,
                        "run_count": 3,
                        "timezone": "UTC",
                        "metadata": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_agent_status_empty_state(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        code, data = _post_status(server)
        assert code == 200
        assert data["ok"] is True
        for key in ("agents", "sessions", "schedules", "approvals", "usage"):
            assert key in data, f"missing section: {key}"
        assert data["agents"]["ok"] is True
        assert data["agents"]["runs"] == []
        assert data["sessions"]["ok"] is True
        assert data["sessions"]["sessions"] == []
        assert "jobs" in data["schedules"]
        assert data["schedules"]["jobs"] == []
        assert data["approvals"]["ok"] is True
        assert data["approvals"]["approvals"] == []
        assert data["usage"]["ok"] is True
        assert "total_usd" in data["usage"]
    finally:
        server.stop()


def test_agent_status_reflects_seeded_state(tmp_path: Path) -> None:
    _seed_state(tmp_path)
    server = _server(tmp_path)
    try:
        code, data = _post_status(server)
        assert code == 200 and data["ok"] is True
        runs = data["agents"]["runs"]
        assert len(runs) == 1
        assert runs[0]["objective"] == "summarize inbox"
        assert runs[0]["agent_name"] == "ghost-chimera"
        sessions = data["sessions"]["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess-1"
        assert sessions[0]["message_count"] == 1
        jobs = data["schedules"]["jobs"]
        assert len(jobs) == 1
        assert jobs[0]["name"] == "nightly-audit"
        assert jobs[0]["cron_expression"] == "0 2 * * *"
    finally:
        server.stop()


def test_agent_status_isolates_section_failure(tmp_path: Path, monkeypatch) -> None:
    _seed_state(tmp_path)
    # Force the sessions section to raise; it must report its error in place
    # while the other sections still return real data.
    from ghostchimera import trust_runtime

    def _boom(self, **kwargs):
        raise RuntimeError("sessions exploded")

    monkeypatch.setattr(trust_runtime.TrustRuntimeStore, "list_sessions", _boom)
    server = _server(tmp_path)
    try:
        code, data = _post_status(server)
        assert code == 200 and data["ok"] is True
        assert data["sessions"]["ok"] is False
        assert "RuntimeError" in data["sessions"]["error"]
        assert len(data["agents"]["runs"]) == 1
        assert len(data["schedules"]["jobs"]) == 1
    finally:
        server.stop()


def test_agent_status_does_not_start_scheduler_thread(tmp_path: Path) -> None:
    _seed_state(tmp_path)
    before = {t.name for t in __import__("threading").enumerate()}
    server = _server(tmp_path)
    try:
        code, _ = _post_status(server)
        assert code == 200
    finally:
        server.stop()
    after = {t.name for t in __import__("threading").enumerate()}
    leaked = {name for name in after - before if "cron" in name.lower() or "scheduler" in name.lower()}
    assert not leaked, f"scheduler threads leaked: {leaked}"
