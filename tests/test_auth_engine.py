"""Custom Auth Engine tests: offline, deterministic, no secrets."""

from __future__ import annotations

import json
import threading

import pytest

from ghostchimera.connectors.auth_engine import (
    PROVIDERS,
    AuthEngineError,
    CustomAuthEngine,
    EngineAction,
    NeedsReauth,
    UnknownProvider,
)


def _transport_factory(calls: list, *, refresh=None, proxy=None):
    def transport(kind: str, url: str, payload):
        calls.append((kind, url))
        if kind == "POST" and "slack.com/api/oauth" in url or "oauth" in url and kind == "POST":
            body = payload if isinstance(payload, dict) else {}
            if body.get("grant_type") == "refresh_token":
                if callable(refresh):
                    return refresh(body)
                return 200, json.dumps({"access_token": "new-at",
                                        "refresh_token": "new-rt",
                                        "expires_in": 3600}).encode()
            return 200, json.dumps({"access_token": "at-1", "refresh_token": "rt-1",
                                    "expires_in": 3600, "scope": "chat:write"}).encode()
        if kind == "PROXY":
            if callable(proxy):
                return proxy(payload)
            return 200, json.dumps({"ok": True, "ts": "1"}).encode()
        return 404, b"{}"

    return transport


def _engine(tmp_path, monkeypatch, calls, **kw):
    monkeypatch.setenv("SLACK_CLIENT_ID", "cid")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "csecret")
    monkeypatch.delenv("NANGO_SECRET_KEY", raising=False)
    return CustomAuthEngine(tmp_path, transport=_transport_factory(calls, **kw))


def test_catalog_covers_providers() -> None:
    for key in ("google-mail", "slack", "zendesk", "freshdesk", "gorgias",
                "hubspot", "salesforce", "notion", "airtable",
                "hubstaff", "time-doctor", "github", "linkedin"):
        assert key in PROVIDERS


def test_authorize_url_and_state(tmp_path, monkeypatch) -> None:
    calls: list = []
    engine = _engine(tmp_path, monkeypatch, calls)
    try:
        result = engine.authorize_url("slack", "va-1", "http://localhost/cb")
        assert result["authorize_url"].startswith("https://slack.com/oauth/v2/authorize?")
        assert "client_id=cid" in result["authorize_url"]
        assert "code_challenge=" in result["authorize_url"]
        assert result["entity_id"] == "va-1"
        with pytest.raises(UnknownProvider):
            engine.authorize_url("nope", "va-1", "http://localhost/cb")
    finally:
        engine.close()


def test_authorize_needs_client_id(tmp_path, monkeypatch) -> None:
    calls: list = []
    monkeypatch.delenv("SLACK_CLIENT_ID", raising=False)
    engine = CustomAuthEngine(tmp_path, transport=_transport_factory(calls))
    try:
        with pytest.raises(AuthEngineError):
            engine.authorize_url("slack", "va-1", "http://localhost/cb")
    finally:
        engine.close()


def test_callback_replay_and_tamper_guards(tmp_path, monkeypatch) -> None:
    calls: list = []
    engine = _engine(tmp_path, monkeypatch, calls)
    try:
        first = engine.authorize_url("slack", "va-1", "http://localhost/cb")
        done = engine.handle_callback("slack", "code-1", first["state"], "http://localhost/cb")
        assert done["ok"] is True and done["entity_id"] == "va-1"
        assert done["scopes"] == ["chat:write"]
        # Replay blocked.
        with pytest.raises(AuthEngineError):
            engine.handle_callback("slack", "code-1", first["state"], "http://localhost/cb")
        # Tampered state rejected.
        bad = first["state"][:-4] + "AAAA"
        with pytest.raises(AuthEngineError):
            engine.handle_callback("slack", "code-2", bad, "http://localhost/cb")
        # Wrong provider rejected.
        second = engine.authorize_url("slack", "va-1", "http://localhost/cb")
        with pytest.raises(AuthEngineError):
            engine.handle_callback("github", "code-3", second["state"], "http://localhost/cb")
    finally:
        engine.close()


def test_callback_rejects_rebound_entity_and_reuses_stored_redirect(tmp_path, monkeypatch) -> None:
    from ghostchimera.connectors.auth_engine import _b64url_decode, _b64url_encode

    calls: list = []
    engine = _engine(tmp_path, monkeypatch, calls)
    try:
        auth = engine.authorize_url("slack", "va-1", "https://app.example/cb")
        forged_payload = _b64url_decode(auth["state"])
        forged_payload["entity_id"] = "mallory"
        with pytest.raises(AuthEngineError):
            engine.handle_callback("slack", "code-x", _b64url_encode(forged_payload), "https://app.example/cb")

        posted: list = []

        def capture(kind: str, url: str, payload):
            posted.append(payload if isinstance(payload, dict) else {})
            return 200, json.dumps({"access_token": "at-9", "expires_in": 3600}).encode()

        engine2 = CustomAuthEngine(tmp_path, transport=capture)
        try:
            auth2 = engine2.authorize_url("slack", "va-1", "https://app.example/cb")
            done = engine2.handle_callback("slack", "code-y", auth2["state"], "http://rogue/cb")
            assert done["ok"] is True and done["entity_id"] == "va-1"
            assert posted and posted[0]["redirect_uri"] == "https://app.example/cb"
        finally:
            engine2.close()
    finally:
        engine.close()


def test_valid_token_without_refresh(tmp_path, monkeypatch) -> None:
    calls: list = []
    engine = _engine(tmp_path, monkeypatch, calls)
    try:
        auth = engine.authorize_url("slack", "va-1", "http://localhost/cb")
        engine.handle_callback("slack", "code", auth["state"], "http://localhost/cb")
        token = engine.get_valid_token("va-1", "slack")
        assert token == "at-1"
        assert sum(1 for kind, _ in calls if kind == "POST") == 1  # exchange only
        with pytest.raises(UnknownProvider):
            engine.get_valid_token("va-1", "ghost")
        with pytest.raises(NeedsReauth):
            engine.get_valid_token("nobody", "slack")
    finally:
        engine.close()


def test_proactive_refresh_on_expiry(tmp_path, monkeypatch) -> None:
    calls: list = []
    engine = _engine(tmp_path, monkeypatch, calls)
    try:
        auth = engine.authorize_url("slack", "va-1", "http://localhost/cb")
        # Force immediate expiry by patching the stored record's clock is hard;
        # instead expire via a zero-lifetime exchange below.
        engine.handle_callback("slack", "code", auth["state"], "http://localhost/cb")
        # Manually backdate expiry to force refresh on next read.
        engine.store._conn.execute(
            "UPDATE integration_auth_tokens SET expires_at = 1.0 WHERE entity_id='va-1'")
        engine.store._conn.commit()
        assert engine.get_valid_token("va-1", "slack") == "new-at"
        assert engine.get_valid_token("va-1", "slack") == "new-at"  # cached now
        refreshes = [c for c in calls if c[0] == "POST"]
        assert len(refreshes) == 2  # exchange + exactly one refresh
    finally:
        engine.close()


def test_single_flight_refresh_under_concurrency(tmp_path, monkeypatch) -> None:
    calls: list = []
    refresh_count = [0]

    def refresh(body):
        refresh_count[0] += 1
        import time as _t
        _t.sleep(0.05)
        return 200, json.dumps({"access_token": "race-at",
                                "refresh_token": "race-rt", "expires_in": 3600}).encode()

    engine = _engine(tmp_path, monkeypatch, calls, refresh=refresh)
    try:
        auth = engine.authorize_url("slack", "va-1", "http://localhost/cb")
        engine.handle_callback("slack", "code", auth["state"], "http://localhost/cb")
        engine.store._conn.execute(
            "UPDATE integration_auth_tokens SET expires_at = 1.0 WHERE entity_id='va-1'")
        engine.store._conn.commit()
        results = []

        def worker():
            results.append(engine.get_valid_token("va-1", "slack"))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert results == ["race-at"] * 8
        assert refresh_count[0] == 1
    finally:
        engine.close()


def test_invalid_grant_demotes_to_needs_reauth(tmp_path, monkeypatch) -> None:
    calls: list = []

    def refresh(body):
        return 400, json.dumps({"error": "invalid_grant"}).encode()

    engine = _engine(tmp_path, monkeypatch, calls, refresh=refresh)
    try:
        auth = engine.authorize_url("slack", "va-1", "http://localhost/cb")
        engine.handle_callback("slack", "code", auth["state"], "http://localhost/cb")
        engine.store._conn.execute(
            "UPDATE integration_auth_tokens SET expires_at = 1.0 WHERE entity_id='va-1'")
        engine.store._conn.commit()
        with pytest.raises(NeedsReauth):
            engine.get_valid_token("va-1", "slack")
        status = engine.status("va-1")
        assert status["connections"][0]["status"] == "NEEDS_REAUTH"
        # Sticky: no more transport calls.
        before = len(calls)
        with pytest.raises(NeedsReauth):
            engine.get_valid_token("va-1", "slack")
        assert len(calls) == before
    finally:
        engine.close()


def test_proxy_request_and_action(tmp_path, monkeypatch) -> None:
    seen: list = []

    def proxy(payload):
        seen.append(payload)
        return 200, json.dumps({"ok": True}).encode()

    calls: list = []
    engine = _engine(tmp_path, monkeypatch, calls, proxy=proxy)
    try:
        auth = engine.authorize_url("slack", "va-1", "http://localhost/cb")
        engine.handle_callback("slack", "code", auth["state"], "http://localhost/cb")
        result = engine.proxy_request("slack", "va-1", "POST",
                                      "https://slack.com/api/chat.postMessage",
                                      data={"channel": "#ops"})
        assert result == {"ok": True}
        action = EngineAction(provider="slack",
                              url="https://slack.com/api/chat.postMessage",
                              payload={"channel": "#ops"})
        assert action.execute(engine, "va-1") == {"ok": True}
        assert seen and seen[0]["method"] == "POST"
    finally:
        engine.close()


def test_redaction_everywhere(tmp_path, monkeypatch) -> None:
    calls: list = []
    engine = _engine(tmp_path, monkeypatch, calls)
    try:
        auth = engine.authorize_url("slack", "va-1", "http://localhost/cb")
        engine.handle_callback("slack", "code", auth["state"], "http://localhost/cb")
        blob = json.dumps(engine.status("va-1")) + repr(engine)
        assert "at-1" not in blob and "rt-1" not in blob
        raw = (tmp_path / "auth.sqlite3").read_bytes()
        assert b"at-1" not in raw and b"rt-1" not in raw  # encrypted at rest
        assert engine.revoke("va-1", "slack") is True
        assert engine.revoke("va-1", "slack") is False
        with pytest.raises(NeedsReauth):
            engine.get_valid_token("va-1", "slack")
    finally:
        engine.close()


def test_client_id_fallback_chain_and_source(tmp_path, monkeypatch) -> None:
    """Prefer environment client IDs and fall back to shipped shared IDs."""
    from ghostchimera.connectors import auth_engine as engine_mod
    from ghostchimera.connectors.auth_engine import CustomAuthEngine
    from ghostchimera.control_plane import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
    calls: list = []
    engine = CustomAuthEngine(tmp_path, transport=_transport_factory(calls))
    try:
        for var in ("SLACK_CLIENT_ID",):
            monkeypatch.delenv(var, raising=False)
        assert engine.client_id_source("slack") in ("saved", "none", "shared")
        monkeypatch.setenv("SLACK_CLIENT_ID", "cid-env")
        assert engine._client_id("slack") == "cid-env"
        assert engine.client_id_source("slack") == "environment"
        monkeypatch.setitem(engine_mod.SHIPPED_CLIENT_IDS, "slack", "cid-shipped")
        try:
            monkeypatch.delenv("SLACK_CLIENT_ID", raising=False)
            assert engine._client_id("slack") == "cid-shipped"
            assert engine.client_id_source("slack") == "shared"
        finally:
            engine_mod.SHIPPED_CLIENT_IDS.pop("slack", None)
    finally:
        engine.close()


def test_postgres_migration_exists() -> None:
    from pathlib import Path

    migration = Path(__file__).resolve().parents[1] / "migrations" / "0001_integration_auth_tokens.sql"
    text = migration.read_text(encoding="utf-8")
    for marker in ("integration_auth_tokens", "entity_id", "provider", "access_token",
                   "refresh_token", "expires_at", "scopes", "UNIQUE(entity_id, provider)"):
        assert marker in text
