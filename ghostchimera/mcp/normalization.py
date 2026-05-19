"""MCP capability normalization helpers.

These helpers make MCP servers reviewable capability sources without requiring
an external MCP server at runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SECRET_KEYS = ("token", "secret", "api_key", "apikey", "password", "authorization", "credential")


def normalize_mcp_server_entry(
    server_id: str,
    details: dict[str, Any],
    *,
    source_path: Path | str | None = None,
) -> dict[str, Any]:
    """Normalize a raw MCP registry entry into safe Console metadata."""

    safe_details = {str(k): v for k, v in details.items() if not _is_secret_key(str(k))}
    transport = str(safe_details.get("transport") or "").strip().lower()
    if not transport:
        if safe_details.get("url"):
            transport = "http"
        elif safe_details.get("command"):
            transport = "stdio"
        else:
            transport = "unknown"
    enabled = bool(safe_details.get("enabled", True))
    entry: dict[str, Any] = {
        "id": str(server_id),
        "name": str(safe_details.get("name") or str(server_id).replace("_", " ").replace("-", " ").title()),
        "transport": transport,
        "status": "registered" if enabled else "disabled",
        "enabled": enabled,
        "source": str(source_path) if source_path else "unknown",
        "kind": "mcp_server",
        "requires_approval": True,
    }
    for key in ("description", "url", "command"):
        if safe_details.get(key):
            entry[key] = str(safe_details[key])
    if isinstance(safe_details.get("args"), list):
        entry["args"] = [str(item) for item in safe_details["args"]]
    return entry


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_KEYS)


__all__ = ["normalize_mcp_server_entry"]
