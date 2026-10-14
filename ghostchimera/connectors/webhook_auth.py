"""Authentication, rate limiting and async hand-off for inbound VA webhooks.

``POST /api/webhooks/{slack,gmail,zendesk}/{va_id}`` is reachable without the
console token (providers cannot present it), so every delivery must prove it
came from the provider before anything is parsed into an event:

- **Slack**: Slack signing secret, ``X-Slack-Signature: v0=<hex>`` over
  ``v0:{X-Slack-Request-Timestamp}:{raw body}`` (HMAC-SHA256), timestamp
  within :data:`MAX_SKEW_SECONDS`.
- **Zendesk**: webhook signing secret, ``X-Zendesk-Webhook-Signature`` =
  base64(HMAC-SHA256(secret, timestamp + raw body)) with
  ``X-Zendesk-Webhook-Signature-Timestamp`` within the skew window.
- **Gmail (Pub/Sub push)**: either a Google-signed OIDC ID token in
  ``Authorization: Bearer`` (when an audience is configured), or a shared
  verification token (``X-Ghost-Webhook-Token`` header, or the ``?token=``
  query parameter Pub/Sub push subscriptions use since they cannot set
  headers).

No secret configured -> the delivery is rejected (fail closed). Secrets come
from the environment::

    GHOSTCHIMERA_WEBHOOK_SECRET_<SOURCE>_<VA_ID>   # per VA (preferred)
    GHOSTCHIMERA_WEBHOOK_SECRET_<SOURCE>           # all VAs of one provider
    GHOSTCHIMERA_WEBHOOK_GMAIL_OIDC_AUDIENCE       # enables OIDC for Gmail
    GHOSTCHIMERA_WEBHOOK_GMAIL_OIDC_EMAIL          # optional: pin the push SA

(``<VA_ID>`` upper-cased, non-alphanumerics -> ``_``) or from
``<state_dir>/webhook_secrets.json`` shaped ``{"slack": {"*": "...",
"va-1": "..."}}``.

Verified deliveries are rate limited per ``(source, va_id)`` and handed to a
bounded background queue; the HTTP request is answered ``202`` without waiting
for the (paid, multi-second) Nemotron reasoning the loop runs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import queue
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)

MAX_SKEW_SECONDS = 300
MAX_BODY_BYTES = 1 * 1024 * 1024
VA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SECRETS_FILE = "webhook_secrets.json"
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


@dataclass(frozen=True)
class WebhookRejection:
    status: int
    error: str


@dataclass(frozen=True)
class VerifiedDelivery:
    payload: dict[str, Any]
    delivery_id: str


def _env_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", value).upper()


def lookup_secret(source: str, va_id: str, state_dir: str | Path | None = None) -> str:
    """Per-VA secret, then provider-wide secret; env first, then the state file."""
    for name in (
        f"GHOSTCHIMERA_WEBHOOK_SECRET_{_env_key(source)}_{_env_key(va_id)}",
        f"GHOSTCHIMERA_WEBHOOK_SECRET_{_env_key(source)}",
    ):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if state_dir is not None:
        path = Path(state_dir) / SECRETS_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        entry = data.get(source) if isinstance(data, dict) else None
        if isinstance(entry, str):
            return entry.strip()
        if isinstance(entry, dict):
            for key in (va_id, "*"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _timestamp_fresh(raw: str, now: float) -> bool:
    try:
        ts = float(str(raw).strip())
    except (TypeError, ValueError):
        return False
    return abs(now - ts) <= MAX_SKEW_SECONDS


def slack_signature(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def zendesk_signature(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify_slack(secret: str, headers: dict[str, str], body: bytes, now: float) -> WebhookRejection | None:
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")
    if not timestamp or not signature:
        return WebhookRejection(401, "missing Slack signature headers")
    if not _timestamp_fresh(timestamp, now):
        return WebhookRejection(401, "stale or invalid Slack timestamp")
    if not hmac.compare_digest(slack_signature(secret, timestamp, body), signature.strip()):
        return WebhookRejection(401, "invalid Slack signature")
    return None


def verify_zendesk(secret: str, headers: dict[str, str], body: bytes, now: float) -> WebhookRejection | None:
    timestamp = headers.get("x-zendesk-webhook-signature-timestamp", "")
    signature = headers.get("x-zendesk-webhook-signature", "")
    if not timestamp or not signature:
        return WebhookRejection(401, "missing Zendesk signature headers")
    # Zendesk sends an ISO-8601 timestamp; accept epoch seconds too.
    parsed = _parse_timestamp(timestamp)
    if parsed is None or abs(now - parsed) > MAX_SKEW_SECONDS:
        return WebhookRejection(401, "stale or invalid Zendesk timestamp")
    if not hmac.compare_digest(zendesk_signature(secret, timestamp, body), signature.strip()):
        return WebhookRejection(401, "invalid Zendesk signature")
    return None


def _parse_timestamp(raw: str) -> float | None:
    from datetime import datetime

    raw = str(raw).strip()
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Gmail Pub/Sub push: shared token or Google OIDC ID token
# ---------------------------------------------------------------------------

_CERT_CACHE: dict[str, Any] = {"certs": {}, "expires": 0.0}
_CERT_LOCK = threading.Lock()


def _fetch_google_certs() -> dict[str, str]:
    import urllib.request

    from ..http_identity import ensure_user_agent

    with _CERT_LOCK:
        if _CERT_CACHE["certs"] and time.time() < _CERT_CACHE["expires"]:
            return dict(_CERT_CACHE["certs"])
        with urllib.request.urlopen(ensure_user_agent(urllib.request.Request(GOOGLE_CERTS_URL)), timeout=10) as resp:  # noqa: S310 - fixed https URL
            certs = json.loads(resp.read().decode("utf-8"))
        _CERT_CACHE["certs"] = certs
        _CERT_CACHE["expires"] = time.time() + 3600
        return dict(certs)


def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def verify_google_oidc(
    token: str,
    audience: str,
    *,
    email: str = "",
    now: float | None = None,
    cert_fetcher: Callable[[], dict[str, str]] = _fetch_google_certs,
) -> WebhookRejection | None:
    """Verify an RS256 Google-signed ID token (Pub/Sub push authentication)."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:  # pragma: no cover - cryptography is a core dependency
        return WebhookRejection(401, "OIDC verification requires the 'cryptography' package")
    now = time.time() if now is None else now
    try:
        header_b64, claims_b64, sig_b64 = token.split(".")
        header = json.loads(_b64url(header_b64))
        claims = json.loads(_b64url(claims_b64))
        signature = _b64url(sig_b64)
    except (ValueError, json.JSONDecodeError):
        return WebhookRejection(401, "malformed OIDC token")
    if header.get("alg") != "RS256":
        return WebhookRejection(401, "unsupported OIDC algorithm")
    try:
        certs = cert_fetcher()
    except Exception:
        logger.warning("Could not fetch Google OIDC certificates", exc_info=True)
        return WebhookRejection(503, "OIDC certificates unavailable")
    pem = certs.get(str(header.get("kid", "")))
    if not pem:
        return WebhookRejection(401, "unknown OIDC signing key")
    try:
        public_key = x509.load_pem_x509_certificate(pem.encode()).public_key()
        public_key.verify(  # type: ignore[union-attr,call-arg]
            signature,
            f"{header_b64}.{claims_b64}".encode(),
            padding.PKCS1v15(),  # type: ignore[call-arg]
            hashes.SHA256(),  # type: ignore[call-arg]
        )
    except Exception:
        return WebhookRejection(401, "invalid OIDC signature")
    if claims.get("iss") not in GOOGLE_ISSUERS:
        return WebhookRejection(401, "OIDC issuer mismatch")
    aud = claims.get("aud")
    if aud != audience and not (isinstance(aud, list) and audience in aud):
        return WebhookRejection(401, "OIDC audience mismatch")
    try:
        if float(claims.get("exp", 0)) < now - 60 or float(claims.get("iat", now)) > now + 300:
            return WebhookRejection(401, "OIDC token expired")
    except (TypeError, ValueError):
        return WebhookRejection(401, "OIDC token expired")
    if email and (claims.get("email") != email or claims.get("email_verified") is False):
        return WebhookRejection(401, "OIDC email mismatch")
    return None


def verify_gmail(
    secret: str,
    headers: dict[str, str],
    query: dict[str, str],
    *,
    now: float,
    cert_fetcher: Callable[[], dict[str, str]] | None = None,
) -> WebhookRejection | None:
    audience = os.environ.get("GHOSTCHIMERA_WEBHOOK_GMAIL_OIDC_AUDIENCE", "").strip()
    bearer = headers.get("authorization", "")
    if audience and bearer.lower().startswith("bearer ") and bearer.count(".") == 2:
        kwargs: dict[str, Any] = {
            "email": os.environ.get("GHOSTCHIMERA_WEBHOOK_GMAIL_OIDC_EMAIL", "").strip(),
            "now": now,
        }
        if cert_fetcher is not None:
            kwargs["cert_fetcher"] = cert_fetcher
        return verify_google_oidc(bearer[7:].strip(), audience, **kwargs)
    if not secret:
        return WebhookRejection(401, "webhook secret not configured for gmail")
    presented = headers.get("x-ghost-webhook-token", "").strip() or str(query.get("token", "")).strip()
    if not presented:
        return WebhookRejection(401, "missing Gmail push verification token")
    if not hmac.compare_digest(presented.encode(), secret.encode()):
        return WebhookRejection(401, "invalid Gmail push verification token")
    return None


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------


def parse_body(source: str, headers: dict[str, str], body: bytes) -> dict[str, Any] | WebhookRejection:
    """JSON for every provider; Slack's form encoding (``payload=<json>``) too."""
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return WebhookRejection(400, "invalid JSON body")
        return data if isinstance(data, dict) else WebhookRejection(400, "JSON body must be an object")
    if source == "slack" and content_type == "application/x-www-form-urlencoded":
        try:
            form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            return WebhookRejection(400, "invalid form body")
        if "payload" in form:
            try:
                data = json.loads(form["payload"][0])
            except json.JSONDecodeError:
                return WebhookRejection(400, "invalid Slack payload field")
            return data if isinstance(data, dict) else WebhookRejection(400, "Slack payload must be an object")
        return {key: values[0] if values else "" for key, values in form.items()}
    return WebhookRejection(415, "webhooks accept application/json (Slack also form-encoded)")


# ---------------------------------------------------------------------------
# Rate limiting, replay protection, async hand-off
# ---------------------------------------------------------------------------


class TokenBucket:
    """Per-key token buckets: ``capacity`` requests, refilled over ``per`` seconds."""

    def __init__(self, capacity: int, per: float = 60.0, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = max(1, int(capacity))
        self.rate = self.capacity / max(per, 1e-6)
        self._clock = clock
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - last) * self.rate)
            if tokens < 1.0:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1.0, now)
            if len(self._state) > 4096:
                self._state.pop(next(iter(self._state)))
            return True

    def refund(self, key: str) -> None:
        with self._lock:
            if key in self._state:
                tokens, last = self._state[key]
                self._state[key] = (min(float(self.capacity), tokens + 1.0), last)


class ReplayCache:
    def __init__(self, size: int = 4096) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._size = size
        self._lock = threading.Lock()

    def seen(self, key: str) -> bool:
        with self._lock:
            if key in self._seen:
                return True
            self._seen[key] = time.time()
            while len(self._seen) > self._size:
                self._seen.popitem(last=False)
            return False


class WebhookDispatcher:
    """Bounded queue + one daemon worker that feeds events into the loop."""

    def __init__(self, emit: Callable[[Any], Any], *, maxsize: int = 256) -> None:
        self._emit = emit
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(target=self._run, name="ghost-webhook-dispatch", daemon=True)
        self._thread.start()

    def submit(self, event: Any) -> bool:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            return False
        return True

    def join(self, timeout: float = 5.0) -> bool:
        """Wait until queued events are processed (tests/diagnostics)."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return not self._queue.unfinished_tasks

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            try:
                self._emit(event)
            except Exception:
                logger.exception("Webhook event %s failed in the loop", getattr(event, "event_id", "?"))
            finally:
                self._queue.task_done()


def default_rate_limit() -> int:
    try:
        return max(1, int(os.environ.get("GHOSTCHIMERA_WEBHOOK_RATE_PER_MIN", "60")))
    except ValueError:
        return 60


__all__ = [
    "MAX_BODY_BYTES",
    "ReplayCache",
    "TokenBucket",
    "VA_ID_RE",
    "VerifiedDelivery",
    "WebhookDispatcher",
    "WebhookRejection",
    "lookup_secret",
    "parse_body",
    "slack_signature",
    "verify_gmail",
    "verify_google_oidc",
    "verify_slack",
    "verify_zendesk",
    "zendesk_signature",
]
