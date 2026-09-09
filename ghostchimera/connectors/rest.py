"""Shared REST helper for polling connectors (stdlib urllib, bearer auth)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

Fetcher = Callable[[str], Any]


def bearer_get_json(url: str, token: str, *, params: dict[str, str] | None = None,
                    timeout: float = 30.0) -> Any:
    """GET JSON with a Bearer token. Raises on transport/HTTP errors."""
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def vault_token(state_dir: str, provider: str) -> str:
    """Read a usable access token from the connector vault, or ''."""
    from pathlib import Path

    from .oauth import TokenVault

    token = TokenVault(state_dir).valid_token(provider)
    return str((token or {}).get("access_token", ""))


__all__ = ["Fetcher", "bearer_get_json", "vault_token"]
