"""Generic OAuth2 for Ghost connectors (Slack, Notion, LinkedIn, GitHub, Google).

Follows the repo's established credential discipline (see
integrations/email_oauth.py): browser PKCE flow, tokens only in the
Ghost state dir with owner-only permissions, console/API surfaces
return configured/expiry status — never raw tokens. Stdlib-only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    display: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...] = ()
    # Some providers (Slack) rotate refresh tokens; all are optional except id/urls.
    use_pkce: bool = True
    extra_authorize: dict[str, str] = field(default_factory=dict)


OAUTH_PRESETS: dict[str, ProviderPreset] = {
    "slack": ProviderPreset(
        id="slack",
        display="Slack",
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=("channels:history", "channels:read", "groups:history", "groups:read", "users:read"),
    ),
    "notion": ProviderPreset(
        id="notion",
        display="Notion",
        authorize_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        scopes=(),
        extra_authorize={"owner": "user"},
    ),
    "linkedin": ProviderPreset(
        id="linkedin",
        display="LinkedIn",
        authorize_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        scopes=("openid", "profile", "email"),
    ),
    "github": ProviderPreset(
        id="github",
        display="GitHub",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes=("read:user", "repo"),
    ),
    "google": ProviderPreset(
        id="google",
        display="Google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=("openid", "email", "profile"),
        extra_authorize={"access_type": "offline", "prompt": "consent"},
    ),
    # Help / support desks (browser PKCE; server-side exchange via auth engine)
    "zendesk": ProviderPreset(
        id="zendesk",
        display="Zendesk",
        authorize_url="https://{subdomain}.zendesk.com/oauth/authorizations/new",
        token_url="https://{subdomain}.zendesk.com/oauth/tokens",
        scopes=("read", "write"),
    ),
    "freshdesk": ProviderPreset(
        id="freshdesk",
        display="Freshdesk",
        authorize_url="https://{domain}.freshdesk.com/oauth/authorize",
        token_url="https://{domain}.freshdesk.com/oauth/token",
        scopes=("read", "write"),
        use_pkce=False,  # API-key-first product; OAuth per account
    ),
    "gorgias": ProviderPreset(
        id="gorgias",
        display="Gorgias",
        authorize_url="https://{domain}.gorgias.com/oauth/authorize",
        token_url="https://{domain}.gorgias.com/oauth/token",
        scopes=("read", "write"),
    ),
    # CRM
    "hubspot": ProviderPreset(
        id="hubspot",
        display="HubSpot",
        authorize_url="https://app.hubspot.com/oauth/authorize",
        token_url="https://api.hubapi.com/oauth/v1/token",
        scopes=("crm.objects.contacts.read", "crm.objects.contacts.write", "tickets"),
    ),
    "salesforce": ProviderPreset(
        id="salesforce",
        display="Salesforce",
        authorize_url="https://login.salesforce.com/services/oauth2/authorize",
        token_url="https://login.salesforce.com/services/oauth2/token",
        scopes=("api", "refresh_token", "offline_access"),
    ),
    # Productivity
    "airtable": ProviderPreset(
        id="airtable",
        display="Airtable",
        authorize_url="https://airtable.com/oauth2/v1/authorize",
        token_url="https://airtable.com/oauth2/v1/token",
        scopes=("data.records:read", "data.records:write"),
    ),
    # Workforce / time tracking
    "hubstaff": ProviderPreset(
        id="hubstaff",
        display="Hubstaff",
        authorize_url="https://app.hubstaff.com/authorize",
        token_url="https://app.hubstaff.com/access_tokens",
        scopes=("hubstaff:read", "hubstaff:write"),
        use_pkce=False,
    ),
    "time-doctor": ProviderPreset(
        id="time-doctor",
        display="Time Doctor",
        authorize_url="https://api2.timedoctor.com/oauth/authorize",
        token_url="https://api2.timedoctor.com/oauth/token",
        scopes=("read", "write"),
    ),
}


def get_preset(provider: str) -> ProviderPreset:
    try:
        return OAUTH_PRESETS[provider]
    except KeyError as exc:
        raise ValueError(f"Unknown OAuth provider: {provider}. Known: {sorted(OAUTH_PRESETS)}") from exc


# -- PKCE -----------------------------------------------------------------
def pkce_pair(*, verifier: str | None = None) -> tuple[str, str]:
    """Return (verifier, S256 challenge). Fixed verifier enables test vectors."""
    raw = verifier or secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return raw, challenge


def build_authorize_url(preset: ProviderPreset, *, client_id: str, redirect_uri: str,
                        state: str, challenge: str, scopes: list[str] | None = None) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "scope": " ".join(scopes if scopes is not None else list(preset.scopes)),
        **preset.extra_authorize,
    }
    if preset.use_pkce:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    return preset.authorize_url + "?" + urllib.parse.urlencode(params)


def _form_post(url: str, payload: dict[str, str], *, timeout: float = 30.0) -> dict[str, Any]:
    body = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return dict(urllib.parse.parse_qsl(raw))


def exchange_code(preset: ProviderPreset, *, client_id: str, client_secret: str,
                  code: str, redirect_uri: str, verifier: str) -> dict[str, Any]:
    payload = {"grant_type": "authorization_code", "client_id": client_id,
               "code": code, "redirect_uri": redirect_uri}
    if client_secret:
        payload["client_secret"] = client_secret
    if preset.use_pkce:
        payload["code_verifier"] = verifier
    token = _form_post(preset.token_url, payload)
    if "access_token" not in token:
        raise ValueError(f"{preset.id} did not return an access token: "
                         f"{token.get('error', 'unknown error')}")
    now = time.time()
    token["provider"] = preset.id
    token["created_at"] = now
    token["expires_at"] = now + float(token.get("expires_in") or 3600)
    return token


def refresh_access_token(preset: ProviderPreset, *, client_id: str, client_secret: str,
                         refresh_token: str) -> dict[str, Any]:
    token = _form_post(preset.token_url, {
        "grant_type": "refresh_token", "client_id": client_id,
        "client_secret": client_secret, "refresh_token": refresh_token})
    if "access_token" not in token:
        raise ValueError(f"{preset.id} refresh failed: {token.get('error', 'unknown error')}")
    now = time.time()
    token["provider"] = preset.id
    token["created_at"] = now
    token["expires_at"] = now + float(token.get("expires_in") or 3600)
    if "refresh_token" not in token:
        token["refresh_token"] = refresh_token  # providers that don't rotate
    return token


# -- Token vault ------------------------------------------------------------
class TokenVault:
    """Owner-only JSON token files under the state dir. Status is redacted."""

    def __init__(self, state_dir: str | Path) -> None:
        self._dir = Path(state_dir) / "connector_oauth"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, provider: str) -> Path:
        safe = "".join(c for c in provider if c.isalnum() or c in ("-", "_"))
        return self._dir / f"{safe}.token.json"

    def save(self, provider: str, token: dict[str, Any]) -> None:
        path = self._path(provider)
        path.write_text(json.dumps(token), encoding="utf-8")
        with suppress(OSError):  # owner-only perms; best-effort on Windows
            os.chmod(path, 0o600)

    def load(self, provider: str) -> dict[str, Any] | None:
        path = self._path(provider)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError):
            return None

    def revoke(self, provider: str) -> bool:
        path = self._path(provider)
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def valid_token(self, provider: str, *, skew_seconds: float = 60.0) -> dict[str, Any] | None:
        """Return the stored token if unexpired, else None (caller refreshes)."""
        token = self.load(provider)
        if not token or not token.get("access_token"):
            return None
        if float(token.get("expires_at") or 0) <= time.time() + skew_seconds:
            return None
        return token

    def status(self, provider: str) -> dict[str, Any]:
        token = self.load(provider)
        if not token:
            return {"provider": provider, "connected": False}
        return {
            "provider": provider,
            "connected": bool(token.get("access_token")),
            "expires_at": float(token.get("expires_at") or 0),
            "expired": float(token.get("expires_at") or 0) <= time.time(),
            "has_refresh_token": bool(token.get("refresh_token")),
        }


def oauth_status(state_dir: str | Path) -> dict[str, dict[str, Any]]:
    vault = TokenVault(state_dir)
    return {pid: vault.status(pid) for pid in OAUTH_PRESETS}


__all__ = ["OAUTH_PRESETS", "ProviderPreset", "TokenVault", "build_authorize_url",
           "exchange_code", "get_preset", "oauth_status", "pkce_pair", "refresh_access_token"]
