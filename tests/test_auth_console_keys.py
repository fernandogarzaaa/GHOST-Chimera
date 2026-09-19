"""Console key management: save/clear client IDs + secrets, login options. Live server."""

from __future__ import annotations

import json
import os
import stat
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.console_routes import register_connector_routes

_PORT = [19173]


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


def _get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
        return json.load(resp)


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    import ghostchimera.control_plane.config as cfg

    fake = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", fake)
    return fake


def test_save_id_and_secret_never_echoed(tmp_path, isolated_config, monkeypatch) -> None:
    monkeypatch.delenv("NOTION_CLIENT_ID", raising=False)
    monkeypatch.delenv("NOTION_CLIENT_SECRET", raising=False)
    server = _server(tmp_path)
    try:
        data = _post(
            _base(server) + "/api/auth/client-id",
            {
                "provider": "notion",
                "client_id": "nid",
                "client_secret": "nsecret",
            },
        )
        assert data["ok"] is True
        assert data["client_id_configured"] is True
        assert data["client_id_source"] == "saved"
        assert data["client_secret_configured"] is True
        assert "nsecret" not in json.dumps(data)
        saved = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert saved["provider_oauth"]["notion"]["client_id"] == "nid"
        assert saved["provider_oauth"]["notion"]["client_secret"] == "nsecret"
    finally:
        server.stop()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_saved_secret_file_is_owner_only(tmp_path, isolated_config, monkeypatch) -> None:
    monkeypatch.delenv("SLACK_CLIENT_SECRET", raising=False)
    server = _server(tmp_path)
    try:
        _post(_base(server) + "/api/auth/client-id", {"provider": "slack", "client_secret": "xoxb-secret"})
        mode = stat.S_IMODE(os.stat(isolated_config).st_mode)
        assert mode == 0o600
    finally:
        server.stop()


def test_clear_removes_saved_entry(tmp_path, isolated_config) -> None:
    server = _server(tmp_path)
    try:
        assert _post(_base(server) + "/api/auth/client-id", {"provider": "github", "client_id": "c"})["ok"] is True
        cleared = _post(_base(server) + "/api/auth/client-id", {"provider": "github", "clear": True})
        assert cleared == {"ok": True, "provider": "github", "cleared": True}
        saved = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert "github" not in saved.get("provider_oauth", {})
    finally:
        server.stop()


def test_save_validation(tmp_path, isolated_config) -> None:
    server = _server(tmp_path)
    try:
        base = _base(server) + "/api/auth/client-id"
        assert _post(base, {"provider": "", "client_id": "x"})["ok"] is False
        assert _post(base, {"provider": "github"})["ok"] is False
        assert _post(base, {"provider": "github", "client_id": "a/b"})["ok"] is False
    finally:
        server.stop()


def test_login_options_shape(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        data = _get(_base(server) + "/api/auth/login-options")
        assert data["ok"] is True
        assert data["callback_url"].endswith("/api/auth/callback")
        by_key = {o["key"]: o for o in data["options"]}
        assert by_key["github"]["device_flow"] is True
        assert by_key["google-mail"]["device_flow"] is False
        assert by_key["slack"]["browser_flow"] is True
        for opt in data["options"]:
            assert "client_secret_configured" in opt
            assert "client_secret_source" in opt
    finally:
        server.stop()


def test_engine_secret_env_beats_saved(tmp_path, isolated_config, monkeypatch) -> None:
    from ghostchimera.connectors.auth_engine import CustomAuthEngine

    isolated_config.write_text(
        json.dumps({"provider_oauth": {"notion": {"client_secret": "saved-secret"}}}), encoding="utf-8"
    )
    engine = CustomAuthEngine(tmp_path)
    try:
        assert engine._client_secret("notion") == "saved-secret"
        assert engine.client_secret_source("notion") == "saved"
        monkeypatch.setenv("NOTION_CLIENT_SECRET", "env-secret")
        assert engine._client_secret("notion") == "env-secret"
        assert engine.client_secret_source("notion") == "environment"
    finally:
        engine.close()


def test_engine_secret_none_when_unset(tmp_path, isolated_config, monkeypatch) -> None:
    from ghostchimera.connectors.auth_engine import CustomAuthEngine

    monkeypatch.delenv("AIRTABLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GHOSTCHIMERA_AIRTABLE_CLIENT_SECRET", raising=False)
    engine = CustomAuthEngine(tmp_path)
    try:
        assert engine._client_secret("airtable") == ""
        assert engine.client_secret_source("airtable") == "none"
    finally:
        engine.close()
