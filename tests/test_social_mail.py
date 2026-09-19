"""Social presets + app-password mail + Bluesky. Fake transports only."""

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
from ghostchimera.integrations import bluesky_basic, mail_basic

_PORT = [19373]


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


# -- presets ---------------------------------------------------------------------------
def test_social_presets_present() -> None:
    for pid in ("mastodon", "reddit", "discord", "tiktok", "facebook", "instagram", "x"):
        preset = oauth.get_preset(pid)
        assert preset.authorize_url.startswith("https://")
        assert preset.token_url.startswith("https://")
        assert not preset.supports_device_flow


def test_social_pkce_flags() -> None:
    assert oauth.get_preset("mastodon").use_pkce is True
    assert oauth.get_preset("reddit").use_pkce is True
    assert oauth.get_preset("discord").use_pkce is True
    assert oauth.get_preset("tiktok").use_pkce is True
    assert oauth.get_preset("facebook").use_pkce is False
    assert oauth.get_preset("instagram").use_pkce is False
    assert oauth.get_preset("x").use_pkce is True


def test_mastodon_instance_override(monkeypatch) -> None:
    monkeypatch.setenv("MASTODON_INSTANCE", "fosstodon.org")
    preset = oauth.get_preset("mastodon")
    assert preset.authorize_url == "https://fosstodon.org/oauth/authorize"
    assert preset.token_url == "https://fosstodon.org/oauth/token"


def test_mastodon_default_instance() -> None:
    assert "mastodon.social" in oauth.get_preset("mastodon").authorize_url


def test_reddit_authorize_extras() -> None:
    url = oauth.build_authorize_url(
        oauth.get_preset("reddit"), client_id="c", redirect_uri="http://x/", state="s", challenge="ch"
    )
    assert "duration=permanent" in url
    assert "code_challenge=" in url


def test_reddit_basic_auth_flag() -> None:
    assert oauth.get_preset("reddit").use_basic_auth is True
    assert oauth.get_preset("github").use_basic_auth is False


def test_x_scopes_offline() -> None:
    assert "offline.access" in oauth.get_preset("x").scopes


def test_login_options_lists_social_with_costs(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        data = _get(_base(server) + "/api/auth/login-options")
        by_key = {o["key"]: o for o in data["options"]}
        for pid in ("mastodon", "reddit", "discord", "tiktok", "facebook", "instagram", "x"):
            assert pid in by_key, pid
        assert by_key["x"]["setup_cost"] == "paid"
        assert by_key["mastodon"]["setup_cost"] == "none"
        assert by_key["reddit"]["setup_cost"] == "one-time-free"
    finally:
        server.stop()


# -- reddit basic auth + x login-only ----------------------------------------------------
def _transport(calls):
    def transport(method, url, payload):
        calls.append((url, dict(payload)))
        return 200, json.dumps({"access_token": "at-1", "expires_in": 3600, "scope": "identity"}).encode()

    return transport


def test_reddit_exchange_uses_basic_auth(tmp_path, monkeypatch) -> None:

    monkeypatch.setenv("REDDIT_CLIENT_ID", "rid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "rsecret")
    calls: list = []
    engine = CustomAuthEngine(tmp_path, transport=_transport(calls))
    try:
        created = engine.authorize_url("reddit", "u", "http://127.0.0.1:9/callback")
        from ghostchimera.connectors.auth_engine import _b64url_decode

        payload = _b64url_decode(created["state"])
        engine.handle_callback("reddit", "code-1", created["state"], "http://127.0.0.1:9/callback")
        assert payload["provider"] == "reddit"
        url, sent = calls[-1]
        assert "reddit.com/api/v1/access_token" in url
        assert sent["_basic"] == "rid:rsecret"
        assert "client_secret" not in sent  # basic carries it instead
    finally:
        engine.close()


def test_x_proxy_blocked(tmp_path, monkeypatch) -> None:
    import pytest

    monkeypatch.setenv("X_CLIENT_ID", "xid")
    engine = CustomAuthEngine(tmp_path)
    try:
        with pytest.raises(Exception, match="login-only"):
            engine.proxy_request("x", "u", "GET", "https://api.x.com/2/users/me")
    finally:
        engine.close()


# -- mail_basic ----------------------------------------------------------------------------
class FakeIMAP:
    RAW = (
        b"From: Boss <boss@example.com>\r\nSubject: Welcome aboard\r\n"
        b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\nContent-Type: text/plain\r\n\r\n"
        b"Your verification code is 482916. Reset link: https://example.com/reset?token=abc"
    )

    def __init__(self, *args, **kwargs) -> None:
        pass

    def login(self, user, password):
        assert user == "user@gmail.com" and password == "abcd efgh ijkl mnop"
        return ("OK", [])

    def select(self, box, readonly=True):
        assert readonly is True
        return ("OK", [b"2"])

    def search(self, charset, criteria):
        return ("OK", [b"1 2"])

    def fetch(self, uid, spec):
        assert "PEEK" in spec
        return ("OK", [(b"1 (BODY[] {1}", self.RAW)])

    def logout(self):
        return ("BYE", [])


def test_fetch_inbox_fake_imap() -> None:
    out = mail_basic.fetch_inbox("user@gmail.com", "abcd efgh ijkl mnop", max_messages=5, connection_factory=FakeIMAP)
    assert out["ok"] is True and len(out["messages"]) == 2
    first = out["messages"][0]
    assert first["from"] == "Boss <boss@example.com>"
    assert first["subject"] == "Welcome aboard"
    assert "482916" not in first["snippet"]
    assert "[code-filtered]" in first["snippet"]
    assert "token=abc" not in first["snippet"]


def test_fetch_inbox_validation() -> None:
    import pytest

    with pytest.raises(ValueError, match="email address"):
        mail_basic.fetch_inbox("not-an-email", "abcd efgh ijkl mnop", connection_factory=FakeIMAP)
    with pytest.raises(ValueError, match="app password"):
        mail_basic.fetch_inbox("user@gmail.com", "", connection_factory=FakeIMAP)


def test_scrub_sensitive() -> None:
    assert "[code-filtered]" in mail_basic.scrub_sensitive("your OTP is 739201 today")
    assert "[link-filtered]" in mail_basic.scrub_sensitive("go https://x.com/password-reset?a=b now")
    assert mail_basic.scrub_sensitive("plain meeting notes") == "plain meeting notes"


def test_resolve_app_password(tmp_path) -> None:
    engine = CustomAuthEngine(tmp_path)
    try:
        saved = engine.save_custom_key(
            "u", "app_password", "Gmail", "abcd efgh ijkl mnop", provider_hint="user@gmail.com"
        )
        resolved = mail_basic.resolve_app_password(engine, "u", key_id=saved["id"])
        assert resolved == {"email": "user@gmail.com", "secret": "abcdefghijklmnop", "label": "Gmail"}
    finally:
        engine.close()


def test_mail_fetch_route_requires_consent(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        data = _post(_base(server) + "/api/auth/mail/fetch", {"max_messages": 5})
        assert data["ok"] is False
        assert data.get("type") == "consent_required"
    finally:
        server.stop()


# -- bluesky ----------------------------------------------------------------------------------
def test_bluesky_session_validation() -> None:
    import pytest

    with pytest.raises(bluesky_basic.BlueskyError, match="required"):
        bluesky_basic.create_session("", "", request_fn=lambda *a, **k: {})


def test_bluesky_post_flow_fake() -> None:
    seen = {}

    def fake(method, url, **kwargs):
        seen[url] = kwargs.get("body")
        if "createSession" in url:
            return {"did": "did:ex:1", "handle": "u.bsky.social", "accessJwt": "aj", "refreshJwt": "rj"}
        return {"uri": "at://did:ex:1/app.bsky.feed.post/1"}

    session = bluesky_basic.create_session("u.bsky.social", "aaaa-bbbb-cccc-dddd", request_fn=fake)
    assert session["did"] == "did:ex:1"
    out = bluesky_basic.send_post(session, "hello", request_fn=fake)
    assert out["uri"].startswith("at://")
    import pytest

    with pytest.raises(bluesky_basic.BlueskyError, match="300"):
        bluesky_basic.send_post(session, "x" * 301, request_fn=fake)


def test_bluesky_routes(tmp_path, monkeypatch) -> None:
    import ghostchimera.integrations.bluesky_basic as bb

    engine = CustomAuthEngine(tmp_path)
    try:
        saved = engine.save_custom_key(
            "console-user", "byok", "u.bsky.social", "aaaa-bbbb-cccc-dddd", provider_hint="u.bsky.social"
        )
        key_id = saved["id"]
    finally:
        engine.close()

    monkeypatch.setattr(
        bb,
        "create_session",
        lambda handle, pw: {
            "did": "d",
            "handle": handle,
            "access_jwt": "a",
            "refresh_jwt": "r",
            "pds": "https://bsky.social",
        },
    )
    monkeypatch.setattr(bb, "send_post", lambda session, text: {"uri": "at://x"})
    monkeypatch.setattr(bb, "get_timeline", lambda session, limit=10: {"feed": []})
    server = _server(tmp_path)
    try:
        base = _base(server)
        posted = _post(base + "/api/auth/bluesky/post", {"key_id": key_id, "text": "hi"})
        assert posted == {"ok": True, "uri": "at://x", "handle": "u.bsky.social"}
        assert _post(base + "/api/auth/bluesky/post", {"key_id": key_id, "text": ""})["ok"] is False
        assert _post(base + "/api/auth/bluesky/post", {"key_id": "key-nope", "text": "hi"})["ok"] is False
        timeline = _post(base + "/api/auth/bluesky/timeline", {"key_id": key_id})
        assert timeline["ok"] is True and timeline["items"] == []
    finally:
        server.stop()
