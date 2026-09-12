"""Custom Auth Engine: self-hosted OAuth2 + token vault + proxy. No Nango.

Replaces the Nango Cloud integration end to end:

- OAuth redirect link generation (per-provider env credentials, entity_id
  and provider sealed inside the `state` parameter, PKCE).
- Callback + code exchange with Fernet-encrypted storage.
- `get_valid_token()`: decrypt, 5-minute expiry skew, proactive refresh
  with per-token locks (single-flight under concurrency), invalid_grant
  demotion to NEEDS_REAUTH.
- `proxy_request()`: plain HTTPS with `Authorization: Bearer`, no middleman.

Secrets discipline: tokens are encrypted at rest, never appear in status
payloads, __repr__, or logs. SQLite/WAL here mirrors
migrations/0001_integration_auth_tokens.sql (Postgres) column for column.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REFRESH_SKEW_SECONDS = 300.0
STATE_TTL_SECONDS = 600.0


class AuthEngineError(RuntimeError):
    pass


class NeedsReauth(AuthEngineError):
    """Refresh token revoked/expired: user must reconnect this provider."""


class UnknownProvider(AuthEngineError):
    pass


@dataclass(frozen=True)
class EngineProvider:
    key: str
    display: str
    category: str
    api_base: str = ""
    docs: str = ""


# Canonical provider keys (superset of the former Nango catalog slugs so
# existing connection registries keep working; 'google-mail' aliases google).
PROVIDERS: dict[str, EngineProvider] = {
    "google-mail": EngineProvider("google-mail", "Gmail", "comms", "https://gmail.googleapis.com"),
    "slack": EngineProvider("slack", "Slack", "comms", "https://slack.com/api"),
    "zendesk": EngineProvider("zendesk", "Zendesk", "support"),
    "freshdesk": EngineProvider("freshdesk", "Freshdesk", "support"),
    "gorgias": EngineProvider("gorgias", "Gorgias", "support"),
    "hubspot": EngineProvider("hubspot", "HubSpot", "crm", "https://api.hubapi.com"),
    "salesforce": EngineProvider("salesforce", "Salesforce", "crm"),
    "notion": EngineProvider("notion", "Notion", "productivity", "https://api.notion.com/v1"),
    "airtable": EngineProvider("airtable", "Airtable", "productivity", "https://api.airtable.com/v0"),
    "hubstaff": EngineProvider("hubstaff", "Hubstaff", "workforce"),
    "time-doctor": EngineProvider("time-doctor", "Time Doctor", "workforce"),
    "github": EngineProvider("github", "GitHub", "dev", "https://api.github.com"),
    "linkedin": EngineProvider("linkedin", "LinkedIn", "social", "https://api.linkedin.com/v2"),
}

# Shipped shared logins: project-owned OAuth client IDs (Desktop/native type,
# PKCE, no secret) keyed by oauth preset id. Empty until the maintainer
# registers one app per provider — then every user gets 1-click login with
# zero setup. See docs/CUSTOM_AUTH.md ("Shared project logins").
#   Example: SHIPPED_CLIENT_IDS = {"github": "Iv1.abc123...", "slack": "1234.5678..."}
SHIPPED_CLIENT_IDS: dict[str, str] = {}
_CLIENT_ID_ENV: dict[str, tuple[str, ...]] = {
    "slack": ("SLACK_CLIENT_ID",),
    "google": ("GOOGLE_OAUTH_CLIENT_ID", "GMAIL_OAUTH_CLIENT_ID"),
    "github": ("GHOSTCHIMERA_GITHUB_CLIENT_ID", "GITHUB_CLIENT_ID"),
    "notion": ("NOTION_CLIENT_ID",),
    "linkedin": ("LINKEDIN_CLIENT_ID",),
    "hubspot": ("HUBSPOT_CLIENT_ID",),
    "salesforce": ("SALESFORCE_CLIENT_ID",),
    "zendesk": ("ZENDESK_CLIENT_ID",),
    "freshdesk": ("FRESHDESK_CLIENT_ID",),
    "gorgias": ("GORGIAS_CLIENT_ID",),
    "airtable": ("AIRTABLE_CLIENT_ID",),
    "hubstaff": ("HUBSTAFF_CLIENT_ID",),
    "time-doctor": ("TIMEDOCTOR_CLIENT_ID",),
}


def _env_client_id_names(preset_id: str) -> tuple[str, ...]:
    return _CLIENT_ID_ENV.get(preset_id, (f"{preset_id.upper()}_CLIENT_ID",))


_PRESET_FOR = {
    "google-mail": "google",
    "slack": "slack",
    "zendesk": "zendesk",
    "freshdesk": "freshdesk",
    "gorgias": "gorgias",
    "hubspot": "hubspot",
    "salesforce": "salesforce",
    "notion": "notion",
    "airtable": "airtable",
    "hubstaff": "hubstaff",
    "time-doctor": "time-doctor",
    "github": "github",
    "linkedin": "linkedin",
}


def _fernet() -> Any:
    from cryptography.fernet import Fernet

    return Fernet


def _vault_key() -> bytes:
    explicit = os.environ.get("GHOSTCHIMERA_VAULT_SECRET", "").strip()
    if explicit:
        return hashlib.sha256(explicit.encode()).digest()
    return hashlib.sha256(b"ghost-chimera-local-dev-vault").digest()


class AuthStore:
    """SQLite mirror of migrations/0001_integration_auth_tokens.sql."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock:
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS integration_auth_tokens (
              id TEXT PRIMARY KEY,
              entity_id TEXT NOT NULL,
              provider TEXT NOT NULL,
              access_token TEXT NOT NULL,
              refresh_token TEXT NOT NULL,
              expires_at REAL NOT NULL,
              scopes TEXT NOT NULL DEFAULT '[]',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              status TEXT NOT NULL DEFAULT 'ACTIVE',
              UNIQUE(entity_id, provider)
            );
            CREATE INDEX IF NOT EXISTS idx_auth_entity ON integration_auth_tokens(entity_id);
            """)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def upsert(
        self,
        entity_id: str,
        provider: str,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        scopes: list[str],
        *,
        status: str = "ACTIVE",
    ) -> str:
        record_id = f"auth-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO integration_auth_tokens(id, entity_id, provider, access_token,"
                " refresh_token, expires_at, scopes, created_at, updated_at, status)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(entity_id, provider) DO UPDATE SET"
                " access_token=excluded.access_token, refresh_token=excluded.refresh_token,"
                " expires_at=excluded.expires_at, scopes=excluded.scopes,"
                " updated_at=excluded.updated_at, status=excluded.status",
                (
                    record_id,
                    entity_id,
                    provider,
                    access_token,
                    refresh_token,
                    expires_at,
                    json.dumps(scopes),
                    now,
                    now,
                    status,
                ),
            )
            self._conn.commit()
        return record_id

    def get(self, entity_id: str, provider: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, access_token, refresh_token, expires_at, scopes, status,"
                " created_at, updated_at FROM integration_auth_tokens"
                " WHERE entity_id = ? AND provider = ?",
                (entity_id, provider),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "access_token": row[1],
            "refresh_token": row[2],
            "expires_at": row[3],
            "scopes": json.loads(row[4]),
            "status": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }

    def set_status(self, entity_id: str, provider: str, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE integration_auth_tokens SET status = ?, updated_at = ? WHERE entity_id = ? AND provider = ?",
                (status, time.time(), entity_id, provider),
            )
            self._conn.commit()

    def list_for(self, entity_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT provider, status, expires_at, scopes, updated_at"
                " FROM integration_auth_tokens WHERE entity_id = ?",
                (entity_id,),
            ).fetchall()
        return [
            {"provider": r[0], "status": r[1], "expires_at": r[2], "scopes": json.loads(r[3]), "updated_at": r[4]}
            for r in rows
        ]

    def revoke(self, entity_id: str, provider: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM integration_auth_tokens WHERE entity_id = ? AND provider = ?", (entity_id, provider)
            )
            self._conn.commit()
            return cursor.rowcount > 0


def _b64url_encode(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def _b64url_decode(raw: str) -> dict[str, Any]:
    padded = raw + "=" * (-len(raw) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
    if not isinstance(decoded, dict):
        raise ValueError("bad state payload")
    return decoded


class CustomAuthEngine:
    """Standalone OAuth + vault + proxy. `transport` injects HTTP for tests."""

    def __init__(self, state_dir: str | Path, *, transport: Any = None) -> None:
        self.state_dir = Path(state_dir)
        self.store = AuthStore(self.state_dir / "auth.sqlite3")
        self._transport = transport
        fernet_cls = _fernet()
        key = base64.urlsafe_b64encode(_vault_key())
        self._fernet = fernet_cls(key)
        self._locks_lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._used_nonces: set[str] = set()

    def close(self) -> None:
        self.store.close()

    def __repr__(self) -> str:  # never leak key material
        return f"CustomAuthEngine(state_dir={self.state_dir})"

    # -- provider config -----------------------------------------------------
    def _preset(self, provider: str):
        from .oauth import get_preset

        if provider not in _PRESET_FOR:
            raise UnknownProvider(f"Unknown provider: {provider}")
        return get_preset(_PRESET_FOR[provider])

    def _client_id(self, preset_id: str) -> str:
        """Resolve a provider client ID using environment, saved, then shipped values."""
        # 1. Environment always wins (production / containers).
        # 2. Console-saved IDs (per-user setup, no terminal).
        # 3. Shipped project defaults (shared Ghost logins, see below).
        for name in _env_client_id_names(preset_id):
            value = os.environ.get(name, "").strip()
            if value:
                return value
        # 2. Console-saved client IDs (~/.ghostchimera/config.json provider_oauth).
        try:
            from ..control_plane.config import load_config

            saved = load_config().get("provider_oauth", {})
            if isinstance(saved, dict):
                entry = saved.get(preset_id, {})
                if isinstance(entry, dict) and str(entry.get("client_id", "")).strip():
                    return str(entry["client_id"]).strip()
        except Exception:
            pass
        # 3. Shipped shared logins: one project-owned OAuth app per provider,
        #    so users get 1-click without registering anything. Desktop/native
        #    app type (PKCE, no secret) — safe to embed; see docs/CUSTOM_AUTH.md
        #    for the per-provider registration + verification notes.
        return SHIPPED_CLIENT_IDS.get(preset_id, "")

    def client_id_source(self, preset_id: str) -> str:
        """Where the effective client ID comes from (for honest UI)."""
        for name in _env_client_id_names(preset_id):
            if os.environ.get(name, "").strip():
                return "environment"
        try:
            from ..control_plane.config import load_config

            saved = load_config().get("provider_oauth", {})
            if (
                isinstance(saved, dict)
                and isinstance(saved.get(preset_id), dict)
                and str(saved[preset_id].get("client_id", "")).strip()
            ):
                return "saved"
        except Exception:
            pass
        if SHIPPED_CLIENT_IDS.get(preset_id):
            return "shared"
        return "none"

    # -- Step 1: authorize URL ------------------------------------------------
    def authorize_url(
        self, provider: str, entity_id: str, redirect_uri: str, *, scopes: list[str] | None = None
    ) -> dict[str, Any]:
        from .oauth import build_authorize_url, pkce_pair

        if provider not in PROVIDERS:
            raise UnknownProvider(f"Unknown provider: {provider}")
        preset = self._preset(provider)
        client_id = self._client_id(preset.id)
        if not client_id:
            raise AuthEngineError(f"No client ID configured for {provider}")
        nonce = secrets.token_urlsafe(16)
        state = _b64url_encode(
            {"entity_id": entity_id, "provider": provider, "nonce": nonce, "ts": time.time(), "redirect": redirect_uri}
        )
        verifier, challenge = pkce_pair()
        pending_file = self.state_dir / "connector_oauth" / f"pkce-{nonce}.json"
        try:
            pending_file.parent.mkdir(parents=True, exist_ok=True)
            pending_file.write_text(
                json.dumps(
                    {
                        "verifier": verifier,
                        "ts": time.time(),
                        "provider": provider,
                        "entity_id": entity_id,
                        "redirect_uri": redirect_uri,
                    }
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise AuthEngineError(f"Cannot persist PKCE state: {exc}") from exc
        url = build_authorize_url(
            preset,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            challenge=challenge,
            scopes=scopes if scopes is not None else list(preset.scopes),
        )
        return {"authorize_url": url, "state": state, "provider": provider, "entity_id": entity_id}

    # -- Step 2: callback + exchange -------------------------------------------
    def _pop_pkce(self, nonce: str) -> dict[str, Any]:
        pending_file = self.state_dir / "connector_oauth" / f"pkce-{nonce}.json"
        try:
            data = json.loads(pending_file.read_text(encoding="utf-8"))
            pending_file.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthEngineError(f"PKCE state missing/expired for this login: {exc}") from exc
        if time.time() - float(data.get("ts", 0)) > STATE_TTL_SECONDS:
            raise AuthEngineError("Login session expired; start over")
        if not isinstance(data, dict) or not str(data.get("verifier", "")):
            raise AuthEngineError("PKCE state missing/expired for this login")
        return data

    def handle_callback(self, provider: str, code: str, state: str, redirect_uri: str) -> dict[str, Any]:
        if provider not in PROVIDERS:
            raise UnknownProvider(f"Unknown provider: {provider}")
        try:
            payload = _b64url_decode(state)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthEngineError(f"Invalid OAuth state: {exc}") from exc
        if payload.get("provider") != provider or not payload.get("entity_id"):
            raise AuthEngineError("OAuth state mismatch (provider/entity)")
        if time.time() - float(payload.get("ts", 0)) > STATE_TTL_SECONDS:
            raise AuthEngineError("Login session expired; start over")
        nonce = str(payload.get("nonce", ""))
        with self._locks_lock:
            if nonce in self._used_nonces:
                raise AuthEngineError("OAuth state already used (replay blocked)")
            self._used_nonces.add(nonce)
        entity_id = str(payload["entity_id"])
        preset = self._preset(provider)
        pending = self._pop_pkce(nonce)
        if pending.get("provider") != provider or str(pending.get("entity_id", "")) != entity_id:
            raise AuthEngineError("OAuth state mismatch (provider/entity)")
        verifier = str(pending["verifier"])
        exchange = {
            "grant_type": "authorization_code",
            "client_id": self._client_id(preset.id),
            "client_secret": os.environ.get(f"{preset.id.upper()}_CLIENT_SECRET", ""),
            "code": code,
            "redirect_uri": str(pending.get("redirect_uri") or redirect_uri),
            "code_verifier": verifier,
        }
        token = self._post_form(preset.token_url, exchange)
        if "access_token" not in token:
            raise AuthEngineError(f"{provider} gave no access token: {token.get('error', 'unknown')}")
        return self._store_token(provider, entity_id, token)

    def _store_token(self, provider: str, entity_id: str, token: dict[str, Any]) -> dict[str, Any]:
        access = self._fernet.encrypt(str(token["access_token"]).encode()).decode()
        refresh = self._fernet.encrypt(str(token.get("refresh_token", "")).encode()).decode()
        now = time.time()
        expires_at = float(token.get("expires_at") or (now + float(token.get("expires_in") or 3600)))
        scopes = token.get("scope", "")
        scope_list = scopes.split() if isinstance(scopes, str) and scopes else list(token.get("scopes", []) or [])
        self.store.upsert(entity_id, provider, access, refresh, expires_at, scope_list)
        return {
            "ok": True,
            "entity_id": entity_id,
            "provider": provider,
            "expires_at": expires_at,
            "scopes": scope_list,
            "status": "ACTIVE",
        }

    # -- Step 3: vault + proactive refresh ---------------------------------------
    def _lock_for(self, entity_id: str, provider: str) -> threading.Lock:
        key = f"{entity_id}\x00{provider}"
        with self._locks_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def _post_form(self, url: str, payload: dict[str, str]) -> dict[str, Any]:
        # OAuth errors (invalid_grant, invalid_client) arrive WITH the 4xx
        # status — always parse the body before deciding.
        if self._transport is not None:
            status, raw_body = self._transport("POST", url, payload)
            raw = (
                raw_body.decode("utf-8", "replace")
                if isinstance(raw_body, (bytes, bytearray))
                else str(raw_body or "{}")
            )
        else:
            encoded = urllib.parse.urlencode(payload).encode()
            req = urllib.request.Request(
                url,
                data=encoded,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    status, raw = resp.status, resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read().decode("utf-8", "replace")
            except Exception as exc:
                raise AuthEngineError(f"token endpoint unreachable: {type(exc).__name__}") from exc
        try:
            decoded = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise AuthEngineError(f"token endpoint returned non-JSON (HTTP {status})") from exc
        if isinstance(decoded, dict) and decoded.get("error"):
            raise AuthEngineError(f"token endpoint error: {decoded.get('error')}")
        if not 200 <= status < 300:
            raise AuthEngineError(f"token endpoint HTTP {status}")
        return decoded if isinstance(decoded, dict) else {}

    def get_valid_token(self, entity_id: str, provider: str) -> str:
        """Fresh access token: cached, decrypted, proactively refreshed."""
        if provider not in PROVIDERS:
            raise UnknownProvider(f"Unknown provider: {provider}")
        with self._lock_for(entity_id, provider):  # single-flight refresh
            record = self.store.get(entity_id, provider)
            if record is None:
                raise NeedsReauth(f"No connection for {entity_id}/{provider}: connect first")
            if record["status"] == "NEEDS_REAUTH":
                raise NeedsReauth(f"Connection for {entity_id}/{provider} needs re-auth")
            access = self._fernet.decrypt(record["access_token"].encode()).decode()
            if float(record["expires_at"]) > time.time() + REFRESH_SKEW_SECONDS:
                return access
            refresh = self._fernet.decrypt(record["refresh_token"].encode()).decode()
            if not refresh:
                self.store.set_status(entity_id, provider, "NEEDS_REAUTH")
                raise NeedsReauth(f"No refresh token for {entity_id}/{provider}: reconnect")
            preset = self._preset(provider)
            try:
                fresh = self._post_form(
                    preset.token_url,
                    {
                        "grant_type": "refresh_token",
                        "client_id": self._client_id(preset.id),
                        "client_secret": os.environ.get(f"{preset.id.upper()}_CLIENT_SECRET", ""),
                        "refresh_token": refresh,
                    },
                )
            except AuthEngineError as exc:
                message = str(exc).lower()
                if "invalid_grant" in message or "invalid_request" in message:
                    self.store.set_status(entity_id, provider, "NEEDS_REAUTH")
                    raise NeedsReauth(f"Refresh rejected for {entity_id}/{provider}: reconnect") from exc
                raise
            if "access_token" not in fresh:
                raise AuthEngineError(f"Refresh gave no access token for {provider}")
            new_access = self._fernet.encrypt(str(fresh["access_token"]).encode()).decode()
            new_refresh = (
                self._fernet.encrypt(str(fresh["refresh_token"]).encode()).decode()
                if fresh.get("refresh_token")
                else record["refresh_token"]
            )
            now = time.time()
            expires_at = now + float(fresh.get("expires_in") or 3600)
            self.store.upsert(entity_id, provider, new_access, new_refresh, expires_at, record["scopes"])
            return str(fresh["access_token"])

    # -- proxy: act with a fresh token, no middleman ------------------------------
    def proxy_request(
        self,
        provider: str,
        entity_id: str,
        method: str,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        token = self.get_valid_token(entity_id, provider)
        full = url + ("?" + urllib.parse.urlencode(params) if params else "")
        body = json.dumps(data).encode() if data is not None and method.upper() != "GET" else None
        req = urllib.request.Request(
            full,
            data=body,
            method=method.upper(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        if self._transport is not None:
            status, payload = self._transport(
                "PROXY", full, {"method": method, "data": data, "token_prefix": token[:6]}
            )
            if not 200 <= status < 300:
                raise AuthEngineError(f"provider API HTTP {status}")
            try:
                decoded = json.loads(payload or b"{}")
            except json.JSONDecodeError as exc:
                raise AuthEngineError("provider API returned non-JSON") from exc
            return decoded if isinstance(decoded, dict) else {"data": decoded}
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                raw, status = resp.read().decode("utf-8", "replace"), resp.status
        except Exception as exc:
            raise AuthEngineError(f"provider API unreachable: {type(exc).__name__}") from exc
        try:
            decoded = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise AuthEngineError("provider API returned non-JSON") from exc
        if not 200 <= status < 300:
            raise AuthEngineError(f"provider API HTTP {status}: {decoded}")
        return decoded if isinstance(decoded, dict) else {"data": decoded}

    # -- redacted status ------------------------------------------------------------
    def status(self, entity_id: str) -> dict[str, Any]:
        now = time.time()
        out = []
        for record in self.store.list_for(entity_id):
            out.append(
                {
                    "provider": record["provider"],
                    "status": record["status"],
                    "expired": record["expires_at"] <= now,
                    "expires_in_s": max(0, int(record["expires_at"] - now)),
                    "scopes": record["scopes"],
                }
            )
        return {"entity_id": entity_id, "connections": out}

    def revoke(self, entity_id: str, provider: str) -> bool:
        return self.store.revoke(entity_id, provider)


@dataclass
class EngineAction:
    """One backend action trigger executed through the Custom Auth Engine."""

    provider: str
    url: str  # absolute provider API URL (api_base lives in PROVIDERS)
    payload: dict[str, Any] | None = None
    method: str = "POST"

    def execute(self, engine: CustomAuthEngine, entity_id: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return engine.proxy_request(self.provider, entity_id, self.method, self.url, data=self.payload, params=params)


__all__ = [
    "AuthEngineError",
    "AuthStore",
    "CustomAuthEngine",
    "EngineAction",
    "EngineProvider",
    "NeedsReauth",
    "PROVIDERS",
    "UnknownProvider",
]
