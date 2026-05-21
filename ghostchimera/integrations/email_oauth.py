"""OAuth-backed Gmail and Outlook email crawling helpers.

All flows are explicit and local-first:

* no browser cookies or mail-client stores are read;
* access tokens are stored only in the Ghost state directory;
* Console responses return configured/pending status, not raw tokens;
* crawls are bounded by max message counts and use read-only mail scopes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..memory_layer.store import MemoryStore
from ..model_layer.minimind_lifecycle import MiniMindLifecycle

GMAIL_DEVICE_ENDPOINT = "https://oauth2.googleapis.com/device/code"
GMAIL_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GMAIL_MESSAGES_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
OUTLOOK_MESSAGES_ENDPOINT = "https://graph.microsoft.com/v1.0/me/messages"

EMAIL_PROVIDERS = {"gmail", "outlook"}
SECRET_KEYS = {"access_token", "refresh_token", "id_token", "client_secret"}
_CERTIFI_CONTEXT: ssl.SSLContext | None = None
_WINDOWS_CONTEXT: ssl.SSLContext | None = None


@dataclass(frozen=True)
class EmailOAuthResult:
    ok: bool
    provider: str
    status: str
    message: str
    pending_id: str = ""
    user_code: str = ""
    verification_uri: str = ""
    expires_in: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "status": self.status,
            "message": self.message,
            "pending_id": self.pending_id,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "expires_in": self.expires_in,
            "error": self.error,
            "raw_secret_returned": False,
            "policy": {
                "read_only_scopes": True,
                "secrets_are_write_only": True,
                "browser_cookies_read": False,
                "mail_client_stores_read": False,
            },
        }


def _email_oauth_dir(state_dir: str | Path) -> Path:
    path = Path(state_dir).expanduser() / "email_oauth"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pending_path(state_dir: str | Path, provider: str, pending_id: str) -> Path:
    return _email_oauth_dir(state_dir) / f"{provider}-{pending_id}.pending.json"


def _browser_pending_path(state_dir: str | Path, provider: str, state: str) -> Path:
    return _email_oauth_dir(state_dir) / f"{provider}-browser-{state}.pending.json"


def _token_path(state_dir: str | Path, provider: str) -> Path:
    return _email_oauth_dir(state_dir) / f"{provider}.token.json"


def _is_certificate_error(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    text = str(exc).lower()
    return "certificate_verify_failed" in text or "certificate verify failed" in text


def _certifi_ssl_context() -> ssl.SSLContext:
    global _CERTIFI_CONTEXT
    if _CERTIFI_CONTEXT is not None:
        return _CERTIFI_CONTEXT
    try:
        import certifi  # type: ignore[import-not-found]

        _CERTIFI_CONTEXT = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        _CERTIFI_CONTEXT = ssl.create_default_context()
    return _CERTIFI_CONTEXT


def _windows_ssl_context() -> ssl.SSLContext:
    """Build a verified context from the Windows certificate stores when available."""

    global _WINDOWS_CONTEXT
    if _WINDOWS_CONTEXT is not None:
        return _WINDOWS_CONTEXT
    context = ssl.create_default_context()
    enum_certificates = getattr(ssl, "enum_certificates", None)
    if enum_certificates is None:
        _WINDOWS_CONTEXT = context
        return _WINDOWS_CONTEXT
    for store_name in ("ROOT", "CA"):
        try:
            certificates = enum_certificates(store_name)
        except OSError:
            continue
        for cert_bytes, encoding_type, _trust in certificates:
            if encoding_type != "x509_asn":
                continue
            try:
                context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(cert_bytes))
            except (OSError, ssl.SSLError, ValueError):
                continue
    _WINDOWS_CONTEXT = context
    return _WINDOWS_CONTEXT


def _powershell_json_request(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: dict[str, str] | None = None,
    content_type: str = "application/x-www-form-urlencoded",
    timeout: float = 30.0,
) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Windows native TLS fallback is only available on Windows.")
    script = r"""
$ErrorActionPreference = 'Stop'
$raw = [Console]::In.ReadToEnd()
$request = $raw | ConvertFrom-Json
$headers = @{}
if ($request.headers) {
  foreach ($prop in $request.headers.PSObject.Properties) {
    $headers[$prop.Name] = [string]$prop.Value
  }
}
try {
  if ($request.method -eq 'POST') {
    $body = @{}
    if ($request.payload) {
      foreach ($prop in $request.payload.PSObject.Properties) {
        $body[$prop.Name] = [string]$prop.Value
      }
    }
    $response = Invoke-RestMethod -Method Post -Uri $request.url -Headers $headers -ContentType $request.content_type -Body $body -TimeoutSec $request.timeout
  } else {
    $response = Invoke-RestMethod -Method Get -Uri $request.url -Headers $headers -TimeoutSec $request.timeout
  }
  $response | ConvertTo-Json -Depth 32 -Compress
} catch {
  $resp = $_.Exception.Response
  if ($resp -ne $null) {
    $stream = $resp.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    [pscustomobject]@{
      __ghost_http_error = $true
      status = [int]$resp.StatusCode
      body = $reader.ReadToEnd()
    } | ConvertTo-Json -Depth 8 -Compress
    exit 0
  }
  throw
}
"""
    request = {
        "url": url,
        "method": method.upper(),
        "headers": headers,
        "payload": payload or {},
        "content_type": content_type,
        "timeout": max(1, int(timeout)),
    }
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout + 10,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "PowerShell HTTPS request failed").strip())
    data = json.loads(completed.stdout or "{}")
    if isinstance(data, dict) and data.get("__ghost_http_error"):
        body = str(data.get("body") or "")
        raise urllib.error.HTTPError(url, int(data.get("status") or 500), body, {}, None)
    if not isinstance(data, dict):
        raise RuntimeError("PowerShell HTTPS request returned a non-object response.")
    return data


def _urlopen_json(req: urllib.request.Request, *, timeout: float) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        if not _is_certificate_error(exc):
            raise
        last_error: urllib.error.URLError = exc
        for context in (_certifi_ssl_context(), _windows_ssl_context()):
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.URLError as retry_exc:
                if not _is_certificate_error(retry_exc):
                    raise
                last_error = retry_exc
        if os.name == "nt":
            return _powershell_json_request(
                str(req.full_url),
                method=str(req.get_method()),
                headers={key: str(value) for key, value in req.header_items()},
                payload=dict(urllib.parse.parse_qsl((req.data or b"").decode("utf-8"))),
                timeout=timeout,
            )
        raise last_error from exc


def _form_post(url: str, payload: dict[str, str], *, timeout: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    return _urlopen_json(req, timeout=timeout)


def _json_get(url: str, token: str, *, timeout: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"})
    return _urlopen_json(req, timeout=timeout)


def _client_id(provider: str) -> str:
    if provider == "gmail":
        return os.environ.get("GMAIL_OAUTH_CLIENT_ID") or os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    if provider == "outlook":
        return os.environ.get("OUTLOOK_OAUTH_CLIENT_ID") or os.environ.get("MS_GRAPH_CLIENT_ID", "")
    return ""


def _client_secret(provider: str) -> str:
    if provider == "gmail":
        return os.environ.get("GMAIL_OAUTH_CLIENT_SECRET") or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    return ""


def _outlook_tenant() -> str:
    return os.environ.get("OUTLOOK_TENANT_ID") or os.environ.get("MICROSOFT_TENANT_ID") or "common"


def _device_endpoint(provider: str) -> str:
    if provider == "gmail":
        return GMAIL_DEVICE_ENDPOINT
    return f"https://login.microsoftonline.com/{_outlook_tenant()}/oauth2/v2.0/devicecode"


def _token_endpoint(provider: str) -> str:
    if provider == "gmail":
        return GMAIL_TOKEN_ENDPOINT
    return f"https://login.microsoftonline.com/{_outlook_tenant()}/oauth2/v2.0/token"


def _scopes(provider: str) -> str:
    if provider == "gmail":
        return "https://www.googleapis.com/auth/gmail.readonly"
    return "offline_access User.Read Mail.Read"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            redacted[key] = "[redacted]" if str(key).lower() in SECRET_KEYS and item else _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _random_urlsafe(length: int = 32) -> str:
    return secrets.token_urlsafe(length).rstrip("=")


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def email_oauth_status(state_dir: str | Path) -> dict[str, Any]:
    providers: list[dict[str, Any]] = []
    for provider in sorted(EMAIL_PROVIDERS):
        token_path = _token_path(state_dir, provider)
        token_data: dict[str, Any] = {}
        if token_path.exists():
            try:
                token_data = json.loads(token_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                token_data = {}
        providers.append(
            {
                "provider": provider,
                "configured": token_path.exists() and bool(token_data.get("access_token")),
                "client_id_configured": bool(_client_id(provider)),
                "scopes": _scopes(provider).split(),
                "expires_at": float(token_data.get("expires_at") or 0),
            }
        )
    return {
        "ok": True,
        "providers": providers,
        "policy": {
            "read_only_scopes": True,
            "secrets_are_write_only": True,
            "browser_cookies_read": False,
            "mail_client_stores_read": False,
        },
    }


def start_email_oauth(provider: str, state_dir: str | Path) -> dict[str, Any]:
    provider = provider.strip().lower()
    if provider not in EMAIL_PROVIDERS:
        return {"ok": False, "error": f"Unsupported email provider: {provider}"}
    client_id = _client_id(provider)
    if not client_id:
        env_name = "GMAIL_OAUTH_CLIENT_ID" if provider == "gmail" else "OUTLOOK_OAUTH_CLIENT_ID"
        return EmailOAuthResult(
            ok=False,
            provider=provider,
            status="needs_client_id",
            message=f"Set {env_name} for a public OAuth app before starting {provider} device login.",
            verification_uri=(
                "https://console.cloud.google.com/apis/credentials"
                if provider == "gmail"
                else "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
            ),
            error=f"{env_name} is not configured.",
        ).to_dict()
    try:
        payload = _form_post(_device_endpoint(provider), {"client_id": client_id, "scope": _scopes(provider)})
    except Exception as exc:
        return EmailOAuthResult(
            ok=False,
            provider=provider,
            status="error",
            message=f"{provider} OAuth device flow could not start.",
            error=str(exc),
        ).to_dict()
    pending_id = f"{provider}-{int(time.time())}"
    pending = {
        "provider": provider,
        "pending_id": pending_id,
        "client_id": client_id,
        "device_code": payload.get("device_code"),
        "created_at": time.time(),
        "expires_in": int(payload.get("expires_in") or 900),
    }
    _pending_path(state_dir, provider, pending_id).write_text(json.dumps(pending), encoding="utf-8")
    return EmailOAuthResult(
        ok=True,
        provider=provider,
        status="authorization_pending",
        message=f"{provider} OAuth started. Open the verification URL and enter the user code.",
        pending_id=pending_id,
        user_code=str(payload.get("user_code") or ""),
        verification_uri=str(
            payload.get("verification_url")
            or payload.get("verification_uri")
            or payload.get("verification_uri_complete")
            or ""
        ),
        expires_in=int(payload.get("expires_in") or 900),
    ).to_dict()


def start_gmail_browser_oauth(state_dir: str | Path, redirect_uri: str) -> dict[str, Any]:
    """Start a Gmail browser OAuth flow using authorization-code + PKCE."""

    client_id = _client_id("gmail")
    if not client_id:
        return EmailOAuthResult(
            ok=False,
            provider="gmail",
            status="needs_client_id",
            message="Set GMAIL_OAUTH_CLIENT_ID before starting Gmail browser sign-in.",
            verification_uri="https://console.cloud.google.com/apis/credentials",
            error="GMAIL_OAUTH_CLIENT_ID is not configured.",
        ).to_dict()
    if not redirect_uri.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
        return {
            "ok": False,
            "provider": "gmail",
            "status": "invalid_redirect_uri",
            "error": "Gmail browser OAuth requires a local loopback or HTTPS redirect URI.",
        }
    state = _random_urlsafe(24)
    code_verifier = _random_urlsafe(48)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _scopes("gmail"),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    pending = {
        "provider": "gmail",
        "flow": "browser_pkce",
        "state": state,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "created_at": time.time(),
        "expires_in": 900,
    }
    _browser_pending_path(state_dir, "gmail", state).write_text(json.dumps(pending), encoding="utf-8")
    return {
        "ok": True,
        "provider": "gmail",
        "status": "browser_authorization_pending",
        "message": "Gmail browser OAuth started. Approve access in the browser window.",
        "state": state,
        "redirect_uri": redirect_uri,
        "auth_url": GMAIL_AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params),
        "expires_in": 900,
        "raw_secret_returned": False,
        "policy": {
            "read_only_scopes": True,
            "secrets_are_write_only": True,
            "browser_cookies_read": False,
            "mail_client_stores_read": False,
            "pkce_enabled": True,
        },
    }


def finish_gmail_browser_oauth(state_dir: str | Path, state: str, code: str) -> dict[str, Any]:
    state = state.strip()
    code = code.strip()
    if not state or not code:
        return {"ok": False, "provider": "gmail", "status": "invalid_callback", "error": "Missing state or code."}
    pending_file = _browser_pending_path(state_dir, "gmail", state)
    if not pending_file.exists():
        return {"ok": False, "provider": "gmail", "status": "missing_pending_flow", "error": "Unknown OAuth state."}
    pending = json.loads(pending_file.read_text(encoding="utf-8"))
    if time.time() - float(pending.get("created_at") or 0) > float(pending.get("expires_in") or 900):
        pending_file.unlink(missing_ok=True)
        return {"ok": False, "provider": "gmail", "status": "expired", "error": "Gmail browser login expired."}
    payload = {
        "client_id": str(pending.get("client_id") or ""),
        "code": code,
        "code_verifier": str(pending.get("code_verifier") or ""),
        "grant_type": "authorization_code",
        "redirect_uri": str(pending.get("redirect_uri") or ""),
    }
    client_secret = _client_secret("gmail")
    if client_secret:
        payload["client_secret"] = client_secret
    try:
        token = _form_post(GMAIL_TOKEN_ENDPOINT, payload)
    except Exception as exc:
        return {
            "ok": False,
            "provider": "gmail",
            "status": "error",
            "error": str(exc),
            "raw_secret_returned": False,
        }
    if "access_token" not in token:
        return {"ok": False, "provider": "gmail", "status": "error", "error": "Provider did not return access token."}
    token["provider"] = "gmail"
    token["created_at"] = time.time()
    token["expires_at"] = time.time() + float(token.get("expires_in") or 3600)
    _token_path(state_dir, "gmail").write_text(json.dumps(token), encoding="utf-8")
    pending_file.unlink(missing_ok=True)
    return {
        "ok": True,
        "provider": "gmail",
        "status": "connected",
        "configured": True,
        "raw_secret_returned": False,
        "token": _redact(token),
    }


def poll_email_oauth(provider: str, state_dir: str | Path, pending_id: str) -> dict[str, Any]:
    provider = provider.strip().lower()
    if provider not in EMAIL_PROVIDERS:
        return {"ok": False, "error": f"Unsupported email provider: {provider}"}
    pending_file = _pending_path(state_dir, provider, pending_id.strip())
    if not pending_file.exists():
        return {"ok": False, "provider": provider, "status": "missing_pending_flow", "error": "Unknown pending id."}
    pending = json.loads(pending_file.read_text(encoding="utf-8"))
    if time.time() - float(pending.get("created_at") or 0) > float(pending.get("expires_in") or 900):
        pending_file.unlink(missing_ok=True)
        return {"ok": False, "provider": provider, "status": "expired", "error": "Device code expired."}
    try:
        token = _form_post(
            _token_endpoint(provider),
            {
                "client_id": str(pending.get("client_id") or ""),
                "device_code": str(pending.get("device_code") or ""),
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            error = str(body.get("error") or body.get("error_description") or exc)
        except Exception:
            error = str(exc)
        return {"ok": False, "provider": provider, "status": "authorization_pending", "error": error}
    except Exception as exc:
        return {"ok": False, "provider": provider, "status": "error", "error": str(exc)}
    if "access_token" not in token:
        return {"ok": False, "provider": provider, "status": "error", "error": "Provider did not return access token."}
    token["provider"] = provider
    token["created_at"] = time.time()
    token["expires_at"] = time.time() + float(token.get("expires_in") or 3600)
    _token_path(state_dir, provider).write_text(json.dumps(token), encoding="utf-8")
    pending_file.unlink(missing_ok=True)
    return {
        "ok": True,
        "provider": provider,
        "status": "connected",
        "configured": True,
        "raw_secret_returned": False,
        "token": _redact(token),
    }


def _gmail_body(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    stack = [payload]
    while stack:
        part = stack.pop()
        stack.extend(part.get("parts") or [])
        mime = str(part.get("mimeType") or "")
        data = str(part.get("body", {}).get("data") or "")
        if data and mime.startswith("text/"):
            try:
                texts.append(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace"))
            except Exception:
                continue
    return "\n\n".join(texts)


def _gmail_headers(payload: dict[str, Any]) -> dict[str, str]:
    return {str(item.get("name") or "").lower(): str(item.get("value") or "") for item in payload.get("headers") or []}


def _normalize_gmail_message(raw: dict[str, Any]) -> dict[str, str]:
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    headers = _gmail_headers(payload)
    return {
        "id": str(raw.get("id") or ""),
        "subject": headers.get("subject", ""),
        "sender": headers.get("from", ""),
        "date": headers.get("date", ""),
        "body": (_gmail_body(payload) or str(raw.get("snippet") or ""))[:3000],
        "source": "gmail",
    }


def _normalize_outlook_message(raw: dict[str, Any]) -> dict[str, str]:
    sender = raw.get("from", {}).get("emailAddress", {}) if isinstance(raw.get("from"), dict) else {}
    return {
        "id": str(raw.get("id") or ""),
        "subject": str(raw.get("subject") or ""),
        "sender": str(sender.get("address") or sender.get("name") or ""),
        "date": str(raw.get("receivedDateTime") or ""),
        "body": str(raw.get("bodyPreview") or "")[:3000],
        "source": "outlook",
    }


def _message_to_content(message: dict[str, str]) -> str:
    parts = [
        f"Subject: {message.get('subject', '')}",
        f"From: {message.get('sender', '')}",
        f"Date: {message.get('date', '')}",
        "",
        str(message.get("body") or ""),
    ]
    return "\n".join(part for part in parts if part is not None).strip()


def crawl_email_provider(
    provider: str,
    state_dir: str | Path,
    *,
    memory_db: str | Path,
    max_messages: int = 10,
    query: str = "",
    generate_training: bool = True,
) -> dict[str, Any]:
    provider = provider.strip().lower()
    if provider not in EMAIL_PROVIDERS:
        return {"ok": False, "error": f"Unsupported email provider: {provider}"}
    token_file = _token_path(state_dir, provider)
    if not token_file.exists():
        return {"ok": False, "provider": provider, "status": "not_connected", "error": "Connect OAuth first."}
    token = json.loads(token_file.read_text(encoding="utf-8"))
    access_token = str(token.get("access_token") or "")
    if not access_token:
        return {"ok": False, "provider": provider, "status": "not_connected", "error": "Missing access token."}
    max_messages = max(1, min(int(max_messages), 50))
    messages: list[dict[str, str]] = []
    if provider == "gmail":
        params = {"maxResults": str(max_messages)}
        if query.strip():
            params["q"] = query.strip()
        listed = _json_get(GMAIL_MESSAGES_ENDPOINT + "?" + urllib.parse.urlencode(params), access_token)
        for item in listed.get("messages") or []:
            message_id = str(item.get("id") or "")
            if not message_id:
                continue
            raw = _json_get(f"{GMAIL_MESSAGES_ENDPOINT}/{urllib.parse.quote(message_id)}?format=full", access_token)
            messages.append(_normalize_gmail_message(raw))
    else:
        params = {"$top": str(max_messages), "$select": "id,subject,from,receivedDateTime,bodyPreview"}
        url = OUTLOOK_MESSAGES_ENDPOINT + "?" + urllib.parse.urlencode(params)
        listed = _json_get(url, access_token)
        messages.extend(_normalize_outlook_message(item) for item in listed.get("value") or [])
    store = MemoryStore(memory_db)
    inserted = 0
    dataset_records: list[dict[str, str]] = []
    for message in messages:
        content = _message_to_content(message)
        if not content:
            continue
        _, is_new = store.add_document_once(
            source=f"email:{provider}",
            content=content,
            metadata={
                "provider": provider,
                "message_id": message.get("id", ""),
                "subject": message.get("subject", ""),
                "sender": message.get("sender", ""),
                "date": message.get("date", ""),
                "oauth": True,
            },
        )
        if is_new:
            inserted += 1
            dataset_records.append(
                {
                    "prompt": f"Remember and use this read-only {provider} email context.",
                    "response": content[:4000],
                }
            )
    dataset_path = ""
    if dataset_records and generate_training:
        dataset_path = str(MiniMindLifecycle(state_dir=state_dir).generate_dataset(dataset_records))
    return {
        "ok": True,
        "provider": provider,
        "messages_seen": len(messages),
        "ingested": inserted,
        "skipped": len(messages) - inserted,
        "memory_count": store.count(),
        "dataset_records": len(dataset_records),
        "dataset_path": dataset_path,
        "raw_secret_returned": False,
    }


__all__ = [
    "crawl_email_provider",
    "email_oauth_status",
    "finish_gmail_browser_oauth",
    "poll_email_oauth",
    "start_gmail_browser_oauth",
    "start_email_oauth",
]
