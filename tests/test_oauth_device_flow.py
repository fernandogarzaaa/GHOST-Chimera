"""Device flow (RFC 8628) + loopback listener tests. No network."""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from ghostchimera.connectors import oauth
from ghostchimera.connectors.auth_engine import CustomAuthEngine
from ghostchimera.connectors.loopback import LoopbackError, LoopbackListener


def _github():
    return oauth.get_preset("github")


# -- request_device_code ------------------------------------------------------
def test_request_device_code_normalizes_github_response():
    seen = {}

    def post(url, payload):
        seen.update(payload)
        assert url == "https://github.com/login/device/code"
        return {
            "device_code": "dev-1",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }

    out = oauth.request_device_code(_github(), client_id="cid", post_fn=post)
    assert out["device_code"] == "dev-1"
    assert out["user_code"] == "ABCD-1234"
    assert out["verification_uri"] == "https://github.com/login/device"
    assert out["verification_uri_complete"] == ""
    assert seen["client_id"] == "cid"
    assert "scope" in seen


def test_request_device_code_rejects_providers_without_device_flow():
    with pytest.raises(ValueError, match="no device flow"):
        oauth.request_device_code(oauth.get_preset("google"), client_id="cid", post_fn=lambda u, p: {})


def test_request_device_code_requires_client_id():
    with pytest.raises(ValueError, match="No client ID"):
        oauth.request_device_code(_github(), client_id="", post_fn=lambda u, p: {})


def test_request_device_code_surfaces_provider_error():
    with pytest.raises(ValueError, match="device request failed"):
        oauth.request_device_code(_github(), client_id="cid", post_fn=lambda u, p: {"error": "invalid_client"})


# -- poll_device_token ----------------------------------------------------------
def test_poll_pending_then_complete():
    calls = {"n": 0}

    def post(url, payload):
        calls["n"] += 1
        assert payload["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
        if calls["n"] < 2:
            return {"error": "authorization_pending"}
        return {"access_token": "at-1", "expires_in": 3600, "scope": "read:user"}

    pending = oauth.poll_device_token(_github(), client_id="cid", device_code="dev-1", post_fn=post)
    assert pending == {"status": "pending"}
    done = oauth.poll_device_token(_github(), client_id="cid", device_code="dev-1", post_fn=post)
    assert done["status"] == "complete"
    assert done["access_token"] == "at-1"
    assert done["provider"] == "github"
    assert done["expires_at"] > 0


def test_poll_slow_down_flagged():
    out = oauth.poll_device_token(
        _github(), client_id="cid", device_code="d", post_fn=lambda u, p: {"error": "slow_down"}
    )
    assert out == {"status": "pending", "slow_down": True}


@pytest.mark.parametrize("code", ["access_denied", "expired_token"])
def test_poll_terminal_states_raise(code):
    with pytest.raises(ValueError, match="ended by user or expired"):
        oauth.poll_device_token(_github(), client_id="cid", device_code="d", post_fn=lambda u, p: {"error": code})


def test_poll_unknown_error_raises():
    with pytest.raises(ValueError, match="device poll failed"):
        oauth.poll_device_token(_github(), client_id="cid", device_code="d", post_fn=lambda u, p: {"error": "weird"})


# -- wait_for_device_token --------------------------------------------------------
def test_wait_loops_with_injected_sleep():
    responses = [{"error": "authorization_pending"}, {"access_token": "at-9", "expires_in": 60}]
    slept: list = []
    out = oauth.wait_for_device_token(
        _github(),
        client_id="cid",
        device_code="d",
        interval=1,
        timeout=60,
        sleep_fn=slept.append,
        post_fn=lambda url, payload: responses.pop(0),
    )
    assert out["access_token"] == "at-9"
    assert len(slept) == 1


def test_wait_times_out():
    with pytest.raises(ValueError, match="timed out"):
        oauth.wait_for_device_token(
            _github(),
            client_id="cid",
            device_code="d",
            interval=1,
            timeout=0.05,
            sleep_fn=lambda s: None,
            post_fn=lambda url, payload: {"error": "authorization_pending"},
        )


# -- salesforce host + slack scope param -------------------------------------------
def test_salesforce_login_host_configurable(monkeypatch):
    monkeypatch.setenv("SALESFORCE_LOGIN_HOST", "example.my.salesforce.com")
    preset = oauth.get_preset("salesforce")
    assert preset.authorize_url.startswith("https://example.my.salesforce.com/")
    assert preset.token_url.startswith("https://example.my.salesforce.com/")


def test_salesforce_default_host():
    preset = oauth.get_preset("salesforce")
    assert "login.salesforce.com" in preset.authorize_url


def test_slack_uses_user_scope_param():
    url = oauth.build_authorize_url(
        oauth.get_preset("slack"), client_id="c", redirect_uri="http://x/", state="s", challenge="ch"
    )
    assert "user_scope=" in url
    assert "scope=" not in url.replace("user_scope=", "")


# -- loopback listener ------------------------------------------------------------------
def test_loopback_captures_code():
    listener = LoopbackListener().start()
    try:
        assert listener.redirect_uri.startswith("http://127.0.0.1:")
        assert listener.redirect_uri.endswith("/callback")

        def _hit():
            urllib.request.urlopen(listener.redirect_uri + "?code=abc&state=st", timeout=10).read()

        thread = threading.Thread(target=_hit, daemon=True)
        thread.start()
        query = listener.wait(timeout=10)
        thread.join(timeout=10)
        assert query["code"] == "abc"
        assert query["state"] == "st"
    finally:
        listener.close()


def test_loopback_provider_error_surfaced():
    listener = LoopbackListener().start()
    try:

        def _hit():
            urllib.request.urlopen(listener.redirect_uri + "?error=access_denied", timeout=10).read()

        thread = threading.Thread(target=_hit, daemon=True)
        thread.start()
        with pytest.raises(LoopbackError, match="refused"):
            listener.wait(timeout=10)
        thread.join(timeout=10)
    finally:
        listener.close()


def test_loopback_refuses_non_local_bind():
    with pytest.raises(LoopbackError, match="non-local"):
        LoopbackListener(host="0.0.0.0")


def test_loopback_timeout():
    listener = LoopbackListener().start()
    try:
        with pytest.raises(LoopbackError, match="timed out"):
            listener.wait(timeout=0.2)
    finally:
        listener.close()


# -- engine device start/poll --------------------------------------------------------------
def _device_transport(calls, *, polls_before_success=1):
    polls = {"n": 0}

    def transport(method, url, payload):
        calls.append((url, dict(payload)))
        if "device/code" in url:
            return 200, json.dumps(
                {
                    "device_code": "dev-1",
                    "user_code": "WXYZ-9999",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 900,
                    "interval": 5,
                }
            ).encode()
        polls["n"] += 1
        if polls["n"] < polls_before_success:
            return 200, json.dumps({"error": "authorization_pending"}).encode()
        return 200, json.dumps({"access_token": "at-e", "expires_in": 3600, "scope": "read:user"}).encode()

    return transport


def test_engine_device_start_and_poll(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTCHIMERA_GITHUB_CLIENT_ID", "cid")
    calls: list = []
    engine = CustomAuthEngine(tmp_path, transport=_device_transport(calls, polls_before_success=1))
    try:
        started = engine.start_device_login("github", "user-1")
        assert started["ok"] is True
        assert started["user_code"] == "WXYZ-9999"
        assert started["verification_uri"] == "https://github.com/login/device"
        handle = started["handle"]
        # Device secret stays server-side: handle file holds device_code,
        # the start response must not.
        assert "dev-1" not in json.dumps(started)
        done = engine.poll_device_login(handle)
        assert done["status"] == "complete"
        assert done["connection"]["provider"] == "github"
        # Second poll: file consumed.
        with pytest.raises(Exception, match="missing/expired"):
            engine.poll_device_login(handle)
    finally:
        engine.close()


def test_engine_device_poll_pending_then_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTCHIMERA_GITHUB_CLIENT_ID", "cid")
    calls: list = []
    engine = CustomAuthEngine(tmp_path, transport=_device_transport(calls, polls_before_success=2))
    try:
        started = engine.start_device_login("github", "user-1")
        pending = engine.poll_device_login(started["handle"])
        assert pending["status"] == "pending"
        done = engine.poll_device_login(started["handle"])
        assert done["status"] == "complete"
    finally:
        engine.close()


def test_engine_device_denied_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTCHIMERA_GITHUB_CLIENT_ID", "cid")

    def transport(method, url, payload):
        if "device/code" in url:
            return 200, json.dumps(
                {
                    "device_code": "dev-1",
                    "user_code": "U",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 900,
                    "interval": 5,
                }
            ).encode()
        return 200, json.dumps({"error": "access_denied"}).encode()

    engine = CustomAuthEngine(tmp_path, transport=transport)
    try:
        started = engine.start_device_login("github", "user-1")
        with pytest.raises(Exception, match="denied or expired"):
            engine.poll_device_login(started["handle"])
    finally:
        engine.close()


def test_engine_device_unknown_provider(tmp_path):
    engine = CustomAuthEngine(tmp_path)
    try:
        with pytest.raises(Exception, match="Unknown provider"):
            engine.start_device_login("nope", "user-1")
    finally:
        engine.close()


def test_engine_device_unsupported_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    engine = CustomAuthEngine(tmp_path)
    try:
        with pytest.raises(Exception, match="no device flow"):
            engine.start_device_login("google-mail", "user-1")
    finally:
        engine.close()
