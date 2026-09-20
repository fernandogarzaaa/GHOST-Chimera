"""AI-provider logins: OpenRouter PKCE, Gemini OAuth, vault-to-model bridge."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors import oauth
from ghostchimera.connectors.auth_engine import CustomAuthEngine
from ghostchimera.connectors.console_routes import register_connector_routes
from ghostchimera.model_layer.auth_profiles import AuthProfile
from ghostchimera.model_layer.gemini_provider import GeminiProvider

_PORT = [19473]


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


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except Exception as exc:
        return getattr(exc, "code", 0) or 0, ""


def _get_json(url: str) -> dict:
    code, body = _get(url)
    assert code == 200, body[:200]
    return json.loads(body)


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# -- OpenRouter ----------------------------------------------------------------------
def test_openrouter_login_url_shape() -> None:
    url, verifier = oauth.build_openrouter_login_url(callback_url="http://x:1/api/auth/openrouter/landing?setup=n")
    assert url.startswith("https://openrouter.ai/auth?")
    assert "code_challenge=" in url and "code_challenge_method=S256" in url
    assert "callback_url=" in url and verifier


def test_openrouter_exchange_success(monkeypatch) -> None:
    monkeypatch.setattr(
        oauth.urllib.request, "urlopen", lambda req, **kw: _FakeResp({"key": "sk-or-v1-abc", "label": "L"})
    )
    out = oauth.exchange_openrouter_code("code-1")
    assert out == {"key": "sk-or-v1-abc", "label": "L"}


def test_openrouter_exchange_no_key(monkeypatch) -> None:
    import pytest

    monkeypatch.setattr(oauth.urllib.request, "urlopen", lambda req, **kw: _FakeResp({"error": "bad"}))
    with pytest.raises(ValueError, match="no key"):
        oauth.exchange_openrouter_code("code-1")


def test_engine_openrouter_round_trip(tmp_path, monkeypatch) -> None:
    import ghostchimera.connectors.oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "exchange_openrouter_code", lambda code: {"key": "sk-or-v1-abc", "label": "L"})
    engine = CustomAuthEngine(tmp_path)
    try:
        started = engine.start_openrouter_login("u", "http://127.0.0.1:8766")
        assert started["ok"] is True and "openrouter.ai/auth" in started["authorize_url"]
        done = engine.finish_openrouter_login("code-1", started["setup"])
        assert done == {"ok": True, "id": done["id"], "label": "OpenRouter", "entity_id": "u"}
        keys = engine.store.list_custom_keys("u")
        assert len(keys) == 1 and keys[0]["provider_hint"] == "openrouter"
        # Single-use: replay fails.
        import pytest

        with pytest.raises(Exception, match="missing/expired"):
            engine.finish_openrouter_login("code-1", started["setup"])
    finally:
        engine.close()


def test_openrouter_routes(tmp_path, monkeypatch) -> None:
    import ghostchimera.connectors.oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "exchange_openrouter_code", lambda code: {"key": "sk-or-v1-abc", "label": "L"})
    server = _server(tmp_path)
    try:
        base = _base(server)
        started = _post(base + "/api/auth/openrouter/start", {"callback_base": "http://127.0.0.1:9"})
        assert started["ok"] is True
        code, body = _get(base + f"/api/auth/openrouter/landing?code=c1&setup={started['setup']}")
        assert code == 200 and "OpenRouter connected" in body
        keys = _post(base + "/api/auth/keys/list", {})["keys"]
        assert any(k["label"] == "OpenRouter" for k in keys)
    finally:
        server.stop()


# -- Gemini OAuth ----------------------------------------------------------------------
def test_gemini_bearer_header(monkeypatch) -> None:
    captured = {}

    class _Resp:
        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, **kwargs):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = GeminiProvider(AuthProfile(provider="gemini", oauth_token="ya29.test", model="gemini-3.5-flash"))
    assert provider.available is True
    assert provider.chat("sys", "hello") == "hi"
    assert captured["auth"] == "Bearer ya29.test"
    assert "?key=" not in captured["url"]


def test_gemini_key_path_unchanged(monkeypatch) -> None:
    captured = {}

    class _Resp:
        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, **kwargs):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = GeminiProvider(AuthProfile(provider="gemini", api_key="AIza-key", model="gemini-3.5-flash"))
    assert provider.chat("sys", "hello") == "hi"
    assert "?key=AIza-key" in captured["url"]
    assert captured["auth"] is None


def test_google_gemini_login_option_and_scopes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid.apps.googleusercontent.com")
    server = _server(tmp_path)
    try:
        base = _base(server)
        options = {o["key"]: o for o in _get_json(base + "/api/auth/login-options")["options"]}
        assert "google-gemini" in options
        auth = _post(
            base + "/api/auth/authorize",
            {
                "provider": "google-gemini",
                "entity_id": "u",
                "redirect_uri": "http://127.0.0.1:9/cb",
            },
        )
        assert auth["ok"] is True
        assert "generative-language" in auth["authorize_url"]
    finally:
        server.stop()


# -- vault-to-model bridge ---------------------------------------------------------------
def test_use_as_model_route(tmp_path, monkeypatch) -> None:
    import ghostchimera.control_plane.config as cfg

    fake = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", fake)
    server = _server(tmp_path)
    try:
        base = _base(server)
        saved = _post(
            base + "/api/auth/keys/save",
            {
                "kind": "byok",
                "label": "Router",
                "secret": "sk-or-v1-abc",
                "provider_hint": "openrouter",
            },
        )
        assert saved["ok"] is True
        used = _post(
            base + "/api/auth/keys/use-as-model",
            {
                "key_id": saved["id"],
                "provider": "openrouter",
                "model": "openai/gpt-4o-mini",
            },
        )
        assert used == {"ok": True, "provider": "openrouter", "label": "Router"}
        stored = json.loads(fake.read_text(encoding="utf-8"))
        assert stored["model"]["provider"] == "openrouter"
        assert stored["model"]["api_key"] == "sk-or-v1-abc"
        assert stored["model"]["vault_key_id"] == saved["id"]
        ref = _post(base + "/api/auth/keys/model-ref", {})
        assert ref == {"ok": True, "vault_key_id": saved["id"], "vault_label": "Router", "provider": "openrouter"}
        # App passwords are refused as model keys.
        appw = _post(
            base + "/api/auth/keys/save",
            {
                "kind": "app_password",
                "label": "Gmail",
                "secret": "abcd efgh ijkl mnop",
            },
        )
        refused = _post(base + "/api/auth/keys/use-as-model", {"key_id": appw["id"], "provider": "openrouter"})
        assert refused["ok"] is False
    finally:
        server.stop()
