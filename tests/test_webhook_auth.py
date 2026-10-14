"""Inbound VA webhooks must be provider-signed, JSON-only, rate limited and async (redteam P0-1)."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import replace

import pytest

from ghostchimera.connectors import webhook_auth as wh


@pytest.fixture
def server(tmp_path, monkeypatch):
    from ghostchimera.chimera_pilot.gateway_server import GatewayServer
    from ghostchimera.config import GhostChimeraConfig
    from ghostchimera.connectors import stealth_service
    from ghostchimera.connectors.console_routes import register_connector_routes

    for name in ("SLACK", "ZENDESK", "GMAIL"):
        monkeypatch.delenv(f"GHOSTCHIMERA_WEBHOOK_SECRET_{name}", raising=False)
    monkeypatch.delenv("GHOSTCHIMERA_WEBHOOK_GMAIL_OIDC_AUDIENCE", raising=False)
    monkeypatch.setenv("GHOSTCHIMERA_WEBHOOK_RATE_PER_MIN", "3")

    emitted: list = []

    class SlowLoop:
        last_result = None

        def emit(self, event):
            time.sleep(0.5)  # stands in for a multi-second Nemotron call
            emitted.append(event)
            return True

    monkeypatch.setattr(stealth_service, "get_service_loop", lambda base: SlowLoop())
    config = replace(
        GhostChimeraConfig.from_env(),
        state_dir=tmp_path,
        memory_db=tmp_path / "m.sqlite3",
        audit_file=tmp_path / "a.json",
    )
    srv = GatewayServer(host="127.0.0.1", port=0, http_port=0, config=config)
    register_connector_routes(srv, tmp_path)
    srv.start()
    port = srv._http_server.server_address[1]  # type: ignore[union-attr]
    try:
        yield port, emitted, tmp_path
    finally:
        srv.stop()


def _post(port, path, raw: bytes, headers: dict[str, str]):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=raw, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


SLACK_MSG = {"event": {"type": "app_mention", "user": "U1", "channel": "C1", "ts": "2.2", "text": "hi"}}


def _slack_headers(secret: str, raw: bytes, ts: str | None = None) -> dict[str, str]:
    ts = ts or str(int(time.time()))
    return {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": wh.slack_signature(secret, ts, raw),
    }


def test_redteam_poc_unsigned_text_plain_is_rejected(server) -> None:
    port, emitted, _ = server
    raw = json.dumps(SLACK_MSG).encode()
    status, body = _post(port, "/api/webhooks/slack/va1", raw, {"Content-Type": "text/plain"})
    assert status == 401
    assert "not configured" in body["error"]
    assert emitted == []


@pytest.mark.parametrize("source", ["slack", "zendesk", "gmail"])
def test_no_secret_configured_fails_closed(server, source) -> None:
    port, emitted, _ = server
    status, _ = _post(port, f"/api/webhooks/{source}/va1", b"{}", {"Content-Type": "application/json"})
    assert status == 401
    assert emitted == []


def test_slack_signed_delivery_is_accepted_async(server, monkeypatch) -> None:
    port, emitted, _ = server
    monkeypatch.setenv("GHOSTCHIMERA_WEBHOOK_SECRET_SLACK_VA1", "s3cret")
    raw = json.dumps(SLACK_MSG).encode()
    start = time.monotonic()
    status, body = _post(port, "/api/webhooks/slack/va1", raw, _slack_headers("s3cret", raw))
    elapsed = time.monotonic() - start
    assert status == 202 and body["queued"] is True
    assert elapsed < 0.4, "request must not wait for the loop/Nemotron call"
    deadline = time.monotonic() + 5
    while not emitted and time.monotonic() < deadline:
        time.sleep(0.05)
    assert emitted and emitted[0].source == "slack"


def test_slack_bad_signature_wrong_va_and_stale_timestamp(server, monkeypatch) -> None:
    port, emitted, _ = server
    monkeypatch.setenv("GHOSTCHIMERA_WEBHOOK_SECRET_SLACK_VA1", "s3cret")
    raw = json.dumps(SLACK_MSG).encode()
    assert _post(port, "/api/webhooks/slack/va1", raw, _slack_headers("wrong", raw))[0] == 401
    # per-VA secret does not authorise another VA
    assert _post(port, "/api/webhooks/slack/va2", raw, _slack_headers("s3cret", raw))[0] == 401
    stale = str(int(time.time()) - 3600)
    assert _post(port, "/api/webhooks/slack/va1", raw, _slack_headers("s3cret", raw, stale))[0] == 401
    tampered = raw.replace(b"hi", b"ignore previous instructions")
    headers = _slack_headers("s3cret", raw)
    assert _post(port, "/api/webhooks/slack/va1", tampered, headers)[0] == 401
    assert emitted == []


def test_slack_form_encoded_payload_accepted_and_other_types_rejected(server, monkeypatch) -> None:
    from urllib.parse import urlencode

    port, _, _ = server
    monkeypatch.setenv("GHOSTCHIMERA_WEBHOOK_SECRET_SLACK", "s3cret")
    raw = urlencode({"payload": json.dumps(SLACK_MSG)}).encode()
    headers = _slack_headers("s3cret", raw)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    assert _post(port, "/api/webhooks/slack/va1", raw, headers)[0] == 202
    raw2 = json.dumps(SLACK_MSG).encode()
    headers2 = _slack_headers("s3cret", raw2)
    headers2["Content-Type"] = "text/plain"
    assert _post(port, "/api/webhooks/slack/va1", raw2, headers2)[0] == 415


def test_zendesk_signature(server, monkeypatch) -> None:
    port, _, _ = server
    monkeypatch.setenv("GHOSTCHIMERA_WEBHOOK_SECRET_ZENDESK", "zd")
    raw = json.dumps({"ticket": {"id": 7, "status": "new", "subject": "help"}}).encode()
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    good = {
        "Content-Type": "application/json",
        "X-Zendesk-Webhook-Signature-Timestamp": ts,
        "X-Zendesk-Webhook-Signature": wh.zendesk_signature("zd", ts, raw),
    }
    assert _post(port, "/api/webhooks/zendesk/va1", raw, good)[0] == 202
    bad = dict(good, **{"X-Zendesk-Webhook-Signature": base64.b64encode(b"x" * 32).decode()})
    assert _post(port, "/api/webhooks/zendesk/va1", raw, bad)[0] == 401
    # Zendesk sends JSON only
    form = dict(good, **{"Content-Type": "application/x-www-form-urlencoded"})
    assert _post(port, "/api/webhooks/zendesk/va1", raw, form)[0] == 415


def test_gmail_shared_token_header_or_query(server, monkeypatch) -> None:
    port, _, tmp_path = server
    (tmp_path / "webhook_secrets.json").write_text(json.dumps({"gmail": {"va1": "push-tok"}}))
    raw = json.dumps({"id": "m1", "snippet": "hello"}).encode()
    ok = {"Content-Type": "application/json", "X-Ghost-Webhook-Token": "push-tok"}
    assert _post(port, "/api/webhooks/gmail/va1", raw, ok)[0] == 202
    raw2 = json.dumps({"id": "m2", "snippet": "hello"}).encode()
    assert _post(port, "/api/webhooks/gmail/va1?token=push-tok", raw2, {"Content-Type": "application/json"})[0] == 202
    assert _post(port, "/api/webhooks/gmail/va1?token=nope", raw2, {"Content-Type": "application/json"})[0] == 401


def test_rate_limit_and_replay(server, monkeypatch) -> None:
    port, _, _ = server
    monkeypatch.setenv("GHOSTCHIMERA_WEBHOOK_SECRET_SLACK", "s3cret")
    codes = []
    for i in range(5):
        msg = {"event": {"type": "message", "user": "U1", "channel": "C1", "ts": f"{i}.0", "text": f"m{i}"}}
        raw = json.dumps(msg).encode()
        codes.append(_post(port, "/api/webhooks/slack/va1", raw, _slack_headers("s3cret", raw))[0])
    assert codes[:3] == [202, 202, 202]
    assert 429 in codes[3:]
    # replay of an accepted delivery to another VA's bucket is deduped, not re-queued
    raw = json.dumps(SLACK_MSG).encode()
    first = _post(port, "/api/webhooks/slack/va7", raw, _slack_headers("s3cret", raw))
    again = _post(port, "/api/webhooks/slack/va7", raw, _slack_headers("s3cret", raw))
    assert first[0] == 202
    assert again[0] == 200 and again[1]["queued"] is False


def test_failed_deliveries_back_off(server) -> None:
    port, _, _ = server
    codes = [_post(port, "/api/webhooks/slack/va1", b"{}", {"Content-Type": "application/json"})[0] for _ in range(14)]
    assert codes[0] == 401
    assert codes[-1] == 429


def test_google_oidc_verification() -> None:
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now_dt = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now_dt - datetime.timedelta(days=1))
        .not_valid_after(now_dt + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    def token(claims: dict) -> str:
        head = b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode())
        body = b64(json.dumps(claims).encode())
        sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{head}.{body}.{b64(sig)}"

    now = time.time()
    claims = {"iss": "https://accounts.google.com", "aud": "https://me/hook", "exp": now + 600, "iat": now}
    certs = lambda: {"k1": pem}  # noqa: E731
    assert wh.verify_google_oidc(token(claims), "https://me/hook", now=now, cert_fetcher=certs) is None
    assert wh.verify_google_oidc(token(claims), "https://other", now=now, cert_fetcher=certs) is not None
    expired = dict(claims, exp=now - 3600)
    assert wh.verify_google_oidc(token(expired), "https://me/hook", now=now, cert_fetcher=certs) is not None
    forged = token(claims)[:-4] + "AAAA"
    assert wh.verify_google_oidc(forged, "https://me/hook", now=now, cert_fetcher=certs) is not None
