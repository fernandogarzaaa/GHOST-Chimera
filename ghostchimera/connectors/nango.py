"""Nango integration: 1-click OAuth + proxied API actions for Ghost connectors.

Ghost's Python runtime mirrors the standard Nango architecture:
- Frontend (dashboard / Ghost Console): `@nangohq/frontend` `nango.auth()`
  opens the native OAuth popup per providerConfigKey. See docs/NANGO.md.
- Backend (this module): `NangoClient.proxy()` executes API calls on
  behalf of a connection — no manual token refresh, no stored secrets.
  Stdlib-only (urllib), same credential discipline as connectors/oauth.py:
  the secret key lives in env, never in logs, responses, or memory stores.

Provider config keys follow Nango's catalog (e.g. 'google-mail', 'slack').
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NangoProvider:
    key: str  # Nango providerConfigKey
    display: str
    category: str  # comms | support | crm | productivity | workforce | dev | social
    # Default REST endpoint + send-message path for the flagship action.
    api_base: str = ""
    docs: str = ""


NANGO_CATALOG: dict[str, NangoProvider] = {
    # Comms
    "google-mail": NangoProvider("google-mail", "Gmail", "comms",
                                 "https://gmail.googleapis.com",
                                 "https://docs.nango.dev/integrations/all/google-mail"),
    "slack": NangoProvider("slack", "Slack", "comms",
                           "https://slack.com/api",
                           "https://docs.nango.dev/integrations/all/slack"),
    # Support desks
    "zendesk": NangoProvider("zendesk", "Zendesk", "support",
                             "https://{subdomain}.zendesk.com/api/v2",
                             "https://docs.nango.dev/integrations/all/zendesk"),
    "freshdesk": NangoProvider("freshdesk", "Freshdesk", "support",
                               "https://{domain}.freshdesk.com/api/v2",
                               "https://docs.nango.dev/integrations/all/freshdesk"),
    "gorgias": NangoProvider("gorgias", "Gorgias", "support",
                             "https://{domain}.gorgias.com/api",
                             "https://docs.nango.dev/integrations/all/gorgias"),
    # CRM
    "hubspot": NangoProvider("hubspot", "HubSpot", "crm",
                             "https://api.hubapi.com",
                             "https://docs.nango.dev/integrations/all/hubspot"),
    "salesforce": NangoProvider("salesforce", "Salesforce", "crm",
                                "https://{instance}.salesforce.com/services/data",
                                "https://docs.nango.dev/integrations/all/salesforce"),
    # Productivity
    "notion": NangoProvider("notion", "Notion", "productivity",
                            "https://api.notion.com/v1",
                            "https://docs.nango.dev/integrations/all/notion"),
    "airtable": NangoProvider("airtable", "Airtable", "productivity",
                              "https://api.airtable.com/v0",
                              "https://docs.nango.dev/integrations/all/airtable"),
    # Workforce / time tracking
    "hubstaff": NangoProvider("hubstaff", "Hubstaff", "workforce",
                              "https://api.hubstaff.com/v2",
                              "https://docs.nango.dev/integrations/all/hubstaff"),
    "time-doctor": NangoProvider("time-doctor", "Time Doctor", "workforce",
                                 "https://api2.timedoctor.com/api/1.0",
                                 "https://docs.nango.dev/integrations/all/time-doctor"),
    # Dev + social (already native elsewhere; Nango covers them too)
    "github": NangoProvider("github", "GitHub", "dev",
                            "https://api.github.com",
                            "https://docs.nango.dev/integrations/all/github"),
    "linkedin": NangoProvider("linkedin", "LinkedIn", "social",
                              "https://api.linkedin.com/v2",
                              "https://docs.nango.dev/integrations/all/linkedin"),
}


def nango_secret_key() -> str:
    return os.environ.get("NANGO_SECRET_KEY", "")


def nango_public_key() -> str:
    return os.environ.get("NANGO_PUBLIC_KEY", "")


def nango_base_url() -> str:
    return os.environ.get("NANGO_BASE_URL", "https://api.nango.dev")


class NangoError(RuntimeError):
    pass


class NangoClient:
    """Backend client for Nango Cloud (proxy + connections)."""

    def __init__(self, *, secret_key: str = "", base_url: str = "",
                 public_key: str = "", opener: Any = None) -> None:
        self.secret_key = secret_key or nango_secret_key()
        self.base_url = (base_url or nango_base_url()).rstrip("/")
        self.public_key = public_key or nango_public_key()
        self._opener = opener  # injectable transport for offline tests
        if not self.secret_key and opener is None:
            raise NangoError("NANGO_SECRET_KEY is not configured.")

    # -- low level ---------------------------------------------------------
    def _request(self, method: str, path: str, *, body: Any = None,
                 params: dict[str, str] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method.upper(),
            headers={"Authorization": f"Bearer {self.secret_key}",
                     "Content-Type": "application/json", "Accept": "application/json"})
        try:
            if self._opener is not None:
                status, payload = self._opener(method, url, body)
            else:
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    status, payload = resp.status, resp.read()
        except Exception as exc:
            raise NangoError(f"Nango request failed: {type(exc).__name__}: {exc}") from exc
        try:
            decoded = json.loads(payload or b"{}")
        except json.JSONDecodeError as exc:
            raise NangoError(f"Nango returned non-JSON (status={status})") from exc
        if not 200 <= status < 300:
            raise NangoError(f"Nango error {status}: {decoded}")
        return decoded if isinstance(decoded, dict) else {"data": decoded}

    # -- proxy: act on behalf of a connection --------------------------------
    def proxy(self, *, method: str, endpoint: str, provider_config_key: str,
              connection_id: str, data: dict[str, Any] | None = None,
              params: dict[str, str] | None = None) -> dict[str, Any]:
        """POST /proxy/:endpoint with provider/connection headers — the
        Stealth worker's action trigger. Token refresh handled by Nango."""
        if provider_config_key not in NANGO_CATALOG:
            raise NangoError(f"Unknown provider config key: {provider_config_key}")
        url = self.base_url + "/proxy" + endpoint
        query = {"provider_config_key": provider_config_key, "connection_id": connection_id}
        if params:
            query.update(params)
        full = url + "?" + urllib.parse.urlencode(query)
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            full, data=body if method.upper() != "GET" else None, method=method.upper(),
            headers={"Authorization": f"Bearer {self.secret_key}",
                     "Content-Type": "application/json",
                     "Provider-Config-Key": provider_config_key,
                     "Connection-Id": connection_id})
        try:
            if self._opener is not None:
                status, payload = self._opener(method, full, data)
            else:
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    status, payload = resp.status, resp.read()
        except Exception as exc:
            raise NangoError(f"Nango proxy failed: {type(exc).__name__}: {exc}") from exc
        try:
            decoded = json.loads(payload or b"{}")
        except json.JSONDecodeError as exc:
            raise NangoError(f"Nango proxy returned non-JSON (status={status})") from exc
        if not 200 <= status < 300:
            raise NangoError(f"Nango proxy error {status}: {decoded}")
        return decoded if isinstance(decoded, dict) else {"data": decoded}

    # -- connections ----------------------------------------------------------
    def get_connection(self, provider_config_key: str, connection_id: str) -> dict[str, Any]:
        return self._request("GET", f"/connection/{connection_id}",
                             params={"provider_config_key": provider_config_key})

    def list_connections(self, *, provider_config_key: str = "") -> list[dict[str, Any]]:
        params = {"provider_config_key": provider_config_key} if provider_config_key else None
        result = self._request("GET", "/connection", params=params)
        connections = result.get("connections", [])
        return connections if isinstance(connections, list) else []

    def delete_connection(self, provider_config_key: str, connection_id: str) -> bool:
        self._request("DELETE", f"/connection/{connection_id}",
                      params={"provider_config_key": provider_config_key})
        return True

    # -- frontend session ------------------------------------------------------
    def frontend_session(self, *, provider_config_key: str, connection_id: str) -> dict[str, Any]:
        """Public (non-secret) bundle the dashboard hands to @nangohq/frontend.
        The secret key is NEVER included."""
        if provider_config_key not in NANGO_CATALOG:
            raise NangoError(f"Unknown provider config key: {provider_config_key}")
        return {"publicKey": self.public_key, "providerConfigKey": provider_config_key,
                "connectionId": connection_id, "display": NANGO_CATALOG[provider_config_key].display}

    # -- webhooks ---------------------------------------------------------------
    @staticmethod
    def normalize_webhook(payload: dict[str, Any]) -> dict[str, Any]:
        """Map a Nango webhook delivery to a redacted Ghost-side record."""
        return {"type": str(payload.get("type", "")),
                "connectionId": str(payload.get("connectionId", "")),
                "providerConfigKey": str(payload.get("providerConfigKey", "")),
                "received_at": time.time()}


@dataclass
class NangoAction:
    """One backend action trigger, as emitted by the Stealth agent output."""
    provider: str
    endpoint: str
    payload: dict[str, Any] = field(default_factory=dict)
    method: str = "POST"

    def execute(self, client: NangoClient, *, connection_id: str,
                params: dict[str, str] | None = None) -> dict[str, Any]:
        return client.proxy(method=self.method, endpoint=self.endpoint,
                            provider_config_key=self.provider,
                            connection_id=connection_id, data=self.payload, params=params)


__all__ = ["NANGO_CATALOG", "NangoAction", "NangoClient", "NangoError", "NangoProvider",
           "nango_base_url", "nango_public_key", "nango_secret_key"]
