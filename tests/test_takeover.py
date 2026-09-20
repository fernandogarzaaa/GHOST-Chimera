"""Takeover mode: user drives, agent blocked, loop paused, audit written."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.auth_engine import CustomAuthEngine
from ghostchimera.connectors.console_routes import register_connector_routes
from ghostchimera.stealth.computer_live import CdpBrowserExecutor, PyAutoGuiDesktopExecutor
from ghostchimera.stealth.takeover import TakeoverActive, TakeoverError, TakeoverManager, takeover_active

_PORT = [19673]


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


# -- manager ----------------------------------------------------------------------------
def test_start_release_cycle() -> None:
    manager = TakeoverManager()
    try:
        state = manager.start(purpose="linkedin login", url="https://linkedin.com")
        assert state["purpose"] == "linkedin login"
        assert manager.status()["active"] is True
        with pytest.raises(TakeoverError, match="already active"):
            manager.start(purpose="other")
        with pytest.raises(TakeoverActive):
            manager.check()
    finally:
        released = manager.release(actor="op")
    assert released["released"] is True
    assert manager.status()["active"] is False


def test_release_idle() -> None:
    manager = TakeoverManager()
    assert manager.release() == {"released": False, "reason": "no active takeover"}


def test_check_passes_when_idle() -> None:
    TakeoverManager().check()  # must not raise


def test_expiry_auto_releases() -> None:
    import time

    manager = TakeoverManager()
    try:
        manager.start(purpose="x")
        manager._active["expires_at"] = time.time() - 1
        status = manager.status()
        assert status["active"] is False and status["expired"] is True
    finally:
        manager.release()


def test_loop_hooks_pause_and_restore() -> None:
    calls: list = []
    manager = TakeoverManager()
    manager.set_loop_hooks(pause=lambda: calls.append("pause") or False, resume=lambda: calls.append("resume"))
    try:
        manager.start(purpose="x")
        assert calls == ["pause"]
    finally:
        manager.release()
    assert calls == ["pause", "resume"] or calls == ["pause"]  # resume only if was enabled


def test_loop_hooks_resume_when_was_enabled() -> None:
    calls: list = []
    manager = TakeoverManager()
    manager.set_loop_hooks(pause=lambda: calls.append("pause") or True, resume=lambda: calls.append("resume"))
    try:
        manager.start(purpose="x")
    finally:
        manager.release()
    assert calls == ["pause", "resume"]


# -- executor guards ----------------------------------------------------------------------
class _FakeCdp:
    def describe(self):
        return {"url": "https://x/", "text": "hi"}


class _FakeAdapter:
    def screenshot(self, path):
        Path(path).write_text("img")

    def move_to(self, x, y):
        pass

    def click(self):
        pass


def test_cdp_executor_blocked_during_takeover() -> None:
    from ghostchimera.stealth.takeover import takeover_manager

    manager = takeover_manager()
    executor = CdpBrowserExecutor(_FakeCdp())
    assert executor({"operation": "browser.read"})["page"]["url"] == "https://x/"
    try:
        manager.start(purpose="manual login")
        assert takeover_active() is True
        with pytest.raises(TakeoverActive):
            executor({"operation": "browser.read"})
        with pytest.raises(TakeoverActive):
            executor({"operation": "browser.click", "target": "button"})
    finally:
        manager.release()
    assert takeover_active() is False
    assert executor({"operation": "browser.read"})["page"]["url"] == "https://x/"


def test_desktop_executor_blocked_during_takeover(tmp_path) -> None:
    from ghostchimera.stealth.takeover import takeover_manager

    manager = takeover_manager()
    executor = PyAutoGuiDesktopExecutor(adapter=_FakeAdapter())
    try:
        manager.start(purpose="desktop login")
        with pytest.raises(TakeoverActive):
            executor({"operation": "desktop.read", "parameters": {"path": str(tmp_path / "s.png")}})
    finally:
        manager.release()


# -- routes ---------------------------------------------------------------------------------
def test_takeover_routes_and_audit(tmp_path) -> None:
    from ghostchimera.stealth.takeover import takeover_manager

    server = _server(tmp_path)
    try:
        base = _base(server)
        assert _post(base + "/api/auth/takeover/status", {})["active"] is False
        started = _post(base + "/api/auth/takeover/start", {"purpose": "linkedin", "url": "https://linkedin.com"})
        assert started["ok"] is True and started["purpose"] == "linkedin"
        assert _post(base + "/api/auth/takeover/start", {})["ok"] is False
        status = _post(base + "/api/auth/takeover/status", {})
        assert status["active"] is True
        released = _post(base + "/api/auth/takeover/release", {})
        assert released["released"] is True
        assert _post(base + "/api/auth/takeover/status", {})["active"] is False
        engine = CustomAuthEngine(tmp_path)
        try:
            events = [e["event"] for e in engine.audit.recent(limit=20)]
        finally:
            engine.close()
        assert "takeover.start" in events and "takeover.release" in events
    finally:
        takeover_manager().release()
        server.stop()
