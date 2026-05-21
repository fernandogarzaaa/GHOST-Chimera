"""Provider-specific OAuth launch helpers for Ghost Chimera.

The helpers in this module start official provider OAuth flows without reading
browser cookies, CLI token stores, or raw credentials from disk.  Runtime use is
only enabled for flows that return a provider-supported API credential through
an official exchange endpoint.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OAuthLaunchResult:
    """Safe OAuth launch response returned to Console clients."""

    ok: bool
    provider: str
    status: str
    message: str
    auth_url: str = ""
    user_code: str = ""
    verification_uri: str = ""
    pending_id: str = ""
    login_launched: bool = False
    login_command: str = ""
    runtime_activation_supported: bool = False
    activation_provider: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "status": self.status,
            "message": self.message,
            "auth_url": self.auth_url,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "pending_id": self.pending_id,
            "login_launched": self.login_launched,
            "login_command": self.login_command,
            "runtime_activation_supported": self.runtime_activation_supported,
            "activation_provider": self.activation_provider,
            "error": self.error,
        }


@dataclass(frozen=True)
class OAuthExchangeResult:
    """Safe result of exchanging an OAuth callback/device code."""

    ok: bool
    provider: str
    api_key: str = ""
    status: str = ""
    message: str = ""
    error: str = ""


def _oauth_dir(state_dir: str | Path) -> Path:
    root = Path(state_dir) / "provider_oauth"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _json_post(url: str, payload: dict[str, Any], *, timeout: float = 20.0) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _form_post(url: str, payload: dict[str, str], *, timeout: float = 20.0) -> dict[str, Any]:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _safe_open_browser(url: str) -> bool:
    try:
        import webbrowser

        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


def _callback_base(ctx: dict[str, Any], fallback_port: int = 8766) -> str:
    headers = ctx.get("headers", {}) if isinstance(ctx.get("headers"), dict) else {}
    host = str(headers.get("host") or headers.get("Host") or f"127.0.0.1:{fallback_port}")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def start_openrouter_pkce(ctx: dict[str, Any], state_dir: str | Path, *, launch: bool = False) -> OAuthLaunchResult:
    """Start OpenRouter PKCE and persist only the verifier/state pair."""

    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    callback_url = f"{_callback_base(ctx)}/api/console/provider-auth/openrouter/callback?state={state}"
    auth_url = "https://openrouter.ai/auth?" + urllib.parse.urlencode(
        {
            "callback_url": callback_url,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    pending = {
        "provider": "openrouter",
        "state": state,
        "code_verifier": verifier,
        "created_at": time.time(),
        "callback_url": callback_url,
    }
    (_oauth_dir(state_dir) / f"openrouter-{state}.json").write_text(json.dumps(pending), encoding="utf-8")
    launched = _safe_open_browser(auth_url) if launch else False
    return OAuthLaunchResult(
        ok=True,
        provider="openrouter",
        status="authorization_pending",
        message="OpenRouter OAuth started. Authorize in the browser; Ghost will store the returned API key write-only.",
        auth_url=auth_url,
        pending_id=state,
        login_launched=launched,
        runtime_activation_supported=True,
        activation_provider="openrouter",
    )


def exchange_openrouter_code(state_dir: str | Path, *, state: str, code: str) -> OAuthExchangeResult:
    """Exchange an OpenRouter PKCE code for a user-controlled API key."""

    state = state.strip()
    code = code.strip()
    if not state or not code:
        return OAuthExchangeResult(ok=False, provider="openrouter", error="Missing OAuth state or code.")
    path = _oauth_dir(state_dir) / f"openrouter-{state}.json"
    if not path.exists():
        return OAuthExchangeResult(ok=False, provider="openrouter", error="Unknown or expired OAuth state.")
    pending = json.loads(path.read_text(encoding="utf-8"))
    if time.time() - float(pending.get("created_at") or 0) > 900:
        path.unlink(missing_ok=True)
        return OAuthExchangeResult(ok=False, provider="openrouter", error="OpenRouter OAuth state expired.")
    try:
        payload = _json_post(
            "https://openrouter.ai/api/v1/auth/keys",
            {
                "code": code,
                "code_verifier": str(pending.get("code_verifier") or ""),
                "code_challenge_method": "S256",
            },
        )
    except Exception as exc:
        return OAuthExchangeResult(ok=False, provider="openrouter", error=f"OpenRouter key exchange failed: {exc}")
    key = str(payload.get("key") or "").strip()
    if not key:
        return OAuthExchangeResult(ok=False, provider="openrouter", error="OpenRouter did not return an API key.")
    path.unlink(missing_ok=True)
    return OAuthExchangeResult(
        ok=True,
        provider="openrouter",
        api_key=key,
        status="connected",
        message="OpenRouter OAuth completed. The returned API key was stored write-only.",
    )


def start_huggingface_device_flow(state_dir: str | Path, *, launch: bool = False) -> OAuthLaunchResult:
    """Start Hugging Face device-code OAuth if a public OAuth client is configured."""

    client_id = os.environ.get("HUGGINGFACE_OAUTH_CLIENT_ID") or os.environ.get("HF_OAUTH_CLIENT_ID")
    if not client_id:
        return OAuthLaunchResult(
            ok=True,
            provider="huggingface",
            status="needs_client_id",
            message=(
                "Hugging Face supports device-code OAuth, but Ghost needs HUGGINGFACE_OAUTH_CLIENT_ID "
                "for your public OAuth app before it can start the flow."
            ),
            auth_url="https://huggingface.co/settings/applications",
            verification_uri="https://huggingface.co/settings/applications",
            runtime_activation_supported=False,
            activation_provider="huggingface",
        )
    try:
        payload = _form_post(
            "https://huggingface.co/oauth/device",
            {"client_id": client_id, "scope": "openid profile inference-api"},
        )
    except Exception as exc:
        return OAuthLaunchResult(
            ok=False,
            provider="huggingface",
            status="error",
            message="Hugging Face OAuth device flow failed.",
            error=str(exc),
        )
    pending_id = secrets.token_urlsafe(18)
    pending = {
        "provider": "huggingface",
        "pending_id": pending_id,
        "client_id": client_id,
        "device_code": str(payload.get("device_code") or ""),
        "created_at": time.time(),
        "expires_in": int(payload.get("expires_in") or 900),
    }
    (_oauth_dir(state_dir) / f"huggingface-{pending_id}.json").write_text(json.dumps(pending), encoding="utf-8")
    verification_uri = str(payload.get("verification_uri") or payload.get("verification_uri_complete") or "")
    launched = _safe_open_browser(verification_uri) if launch and verification_uri else False
    return OAuthLaunchResult(
        ok=True,
        provider="huggingface",
        status="authorization_pending",
        message="Hugging Face device OAuth started. Enter the user code in the browser, then poll from Ghost.",
        auth_url=verification_uri,
        verification_uri=verification_uri,
        user_code=str(payload.get("user_code") or ""),
        pending_id=pending_id,
        login_launched=launched,
        runtime_activation_supported=True,
        activation_provider="huggingface",
    )


def poll_huggingface_device_flow(state_dir: str | Path, pending_id: str) -> OAuthExchangeResult:
    """Poll a pending Hugging Face device-code OAuth flow."""

    pending_id = pending_id.strip()
    path = _oauth_dir(state_dir) / f"huggingface-{pending_id}.json"
    if not path.exists():
        return OAuthExchangeResult(ok=False, provider="huggingface", error="Unknown Hugging Face OAuth pending id.")
    pending = json.loads(path.read_text(encoding="utf-8"))
    if time.time() - float(pending.get("created_at") or 0) > float(pending.get("expires_in") or 900):
        path.unlink(missing_ok=True)
        return OAuthExchangeResult(ok=False, provider="huggingface", error="Hugging Face OAuth device code expired.")
    try:
        payload = _form_post(
            "https://huggingface.co/oauth/token",
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": str(pending.get("device_code") or ""),
                "client_id": str(pending.get("client_id") or ""),
            },
        )
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            reason = str(body.get("error") or body.get("error_description") or exc)
        except Exception:
            reason = str(exc)
        return OAuthExchangeResult(ok=False, provider="huggingface", status="authorization_pending", error=reason)
    except Exception as exc:
        return OAuthExchangeResult(ok=False, provider="huggingface", error=f"Hugging Face token polling failed: {exc}")
    token = str(payload.get("access_token") or "").strip()
    if not token:
        return OAuthExchangeResult(ok=False, provider="huggingface", error="Hugging Face did not return a token.")
    path.unlink(missing_ok=True)
    return OAuthExchangeResult(
        ok=True,
        provider="huggingface",
        api_key=token,
        status="connected",
        message="Hugging Face OAuth completed. The access token was stored write-only.",
    )


def _launch_fixed_cli(command: str, args: list[str]) -> tuple[bool, str, int | None]:
    executable = shutil.which(command)
    if executable is None:
        return False, f"{command} was not found on PATH.", None
    kwargs: dict[str, Any] = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    else:
        kwargs.update({"start_new_session": True, "stdin": subprocess.DEVNULL})
    try:
        process = subprocess.Popen([executable, *args], **kwargs)  # noqa: S603 - fixed executable and arguments.
    except OSError as exc:
        return False, str(exc), None
    return True, "Login flow launched.", process.pid


def start_google_adc_flow(*, launch: bool = False) -> OAuthLaunchResult:
    """Prepare Google ADC OAuth for Gemini/Vertex workflows."""

    login_command = "gcloud auth application-default login"
    launched = False
    detail = "Run gcloud auth application-default login to configure Google OAuth ADC."
    if launch:
        launched, detail, _pid = _launch_fixed_cli("gcloud", ["auth", "application-default", "login"])
    return OAuthLaunchResult(
        ok=True,
        provider="gemini",
        status="adc_login_launched" if launched else "adc_login_available",
        message=detail,
        login_command=login_command,
        login_launched=launched,
        runtime_activation_supported=False,
        activation_provider="gemini",
    )


__all__ = [
    "OAuthExchangeResult",
    "OAuthLaunchResult",
    "exchange_openrouter_code",
    "poll_huggingface_device_flow",
    "start_google_adc_flow",
    "start_huggingface_device_flow",
    "start_openrouter_pkce",
]
