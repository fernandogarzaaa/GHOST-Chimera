"""Immutable JSONL audit trail for connector trust events.

Append-only: approval requested/approved/denied/consumed/expired, token
stored/refreshed/revoked/imported, proxy calls (host + digest only — never
bodies, tokens, or secrets), and write-gate denials. Each line is one JSON
object {ts, event, entity_id, provider, detail}. The file is never
rewritten; rotation is out of scope (state-dir local file).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

_FILENAME = "connector-audit.jsonl"
_MAX_DETAIL_BYTES = 2048


class AuditTrail:
    """Append-only redacted event log."""

    def __init__(self, state_dir: str | Path) -> None:
        self.path = Path(state_dir) / "audit" / _FILENAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event: str, *, entity_id: str = "", provider: str = "", detail: Any = None) -> None:
        try:
            payload = json.dumps(
                {
                    "ts": time.time(),
                    "event": str(event),
                    "entity_id": str(entity_id or ""),
                    "provider": str(provider or ""),
                    "detail": _redact(detail),
                }
            )[:_MAX_DETAIL_BYTES]
        except (TypeError, ValueError):
            return
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(payload + "\n")
            except OSError:
                pass

    def recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(200, limit))
        try:
            with open(self.path, encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return []
        out = []
        for line in lines[-limit:]:
            try:
                entry = json.loads(line)
                if isinstance(entry, dict):
                    out.append(entry)
            except json.JSONDecodeError:
                continue
        return out


def _redact(detail: Any) -> Any:
    """Strip anything shaped like a secret; keep hosts and digests."""
    if isinstance(detail, dict):
        clean: dict[str, Any] = {}
        for key, value in detail.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("secret", "token", "password", "key", "auth", "code", "verifier")):
                clean[key] = "[redacted]"
            elif key == "url" and isinstance(value, str):
                clean[key] = _host_only(value)
            else:
                clean[key] = _redact(value)
        return clean
    if isinstance(detail, list):
        return [_redact(item) for item in detail[:20]]
    if isinstance(detail, str) and len(detail) > 300:
        return detail[:300] + "…"
    return detail


def _host_only(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://{parsed.hostname or '?'}…" if parsed.hostname else "[url]"
    except Exception:
        return "[url]"


__all__ = ["AuditTrail"]
