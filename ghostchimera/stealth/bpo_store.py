"""BPO production store: VAs, connection registry, encrypted browser profiles.

Extends the Stealth SQLite journal with the multi-tenant tables from the
production architecture: va_users, oauth_connections (Nango mapping),
browser_profiles (Fernet-encrypted auth.json blobs for MicroVM hydration),
plus execution_mode/pathway on the audit trail. SQLite + WAL, stdlib +
cryptography only. Postgres remains the hosted answer; this is the
local-first equivalent with the same column contract.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS va_users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  organization_id TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_connections (
  id TEXT PRIMARY KEY,
  va_id TEXT NOT NULL REFERENCES va_users(id) ON DELETE CASCADE,
  provider_config_key TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  updated_at REAL NOT NULL,
  UNIQUE(va_id, provider_config_key, connection_id)
);
CREATE TABLE IF NOT EXISTS browser_profiles (
  id TEXT PRIMARY KEY,
  va_id TEXT NOT NULL REFERENCES va_users(id) ON DELETE CASCADE,
  domain TEXT NOT NULL,
  encrypted_auth_state TEXT NOT NULL,
  last_verified_at REAL NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(va_id, domain)
);
CREATE TABLE IF NOT EXISTS ghost_audit_logs (
  id TEXT PRIMARY KEY,
  va_id TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL,
  confidence_score REAL NOT NULL DEFAULT 0.0,
  execution_mode TEXT NOT NULL DEFAULT '',
  execution_pathway TEXT NOT NULL DEFAULT '',
  payload_snapshot TEXT NOT NULL DEFAULT '{}',
  timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_va_time ON ghost_audit_logs(va_id, timestamp);
"""


def _vault_key(state_dir: Path) -> bytes:
    """Stable machine-local key: server secret env or generated-and-stored.

    Never logged, never returned. Falls back to a generated file key with
    owner-only permissions when no GHOSTCHIMERA_VAULT_SECRET is set.
    """
    explicit = os.environ.get("GHOSTCHIMERA_VAULT_SECRET", "").strip()
    if explicit:
        return hashlib.sha256(explicit.encode()).digest()
    key_file = Path(state_dir) / "connector_oauth" / ".vault.key"
    if key_file.exists():
        raw = key_file.read_bytes().strip()
        if len(raw) == 32:
            return raw
    raw = os.urandom(32)
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(raw)
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return raw


class BpoStore:
    """VA registry + connection map + encrypted browser profiles + audit."""

    def __init__(self, path: str | Path, *, state_dir: str | Path | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        from cryptography.fernet import Fernet

        base32 = base64.urlsafe_b64encode(_vault_key(Path(state_dir) if state_dir else self.path.parent))
        self._fernet = Fernet(base32)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- VAs ---------------------------------------------------------------
    def create_va(self, email: str, *, organization_id: str = "") -> dict[str, Any]:
        va_id = f"va-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute(
                "INSERT INTO va_users(id, email, organization_id, created_at) VALUES(?,?,?,?)",
                (va_id, email, organization_id, time.time()),
            )
            self._conn.commit()
        return {"id": va_id, "email": email, "organization_id": organization_id}

    def get_va(self, va_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, organization_id, created_at FROM va_users WHERE id = ?", (va_id,)
            ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "email": row[1], "organization_id": row[2], "created_at": row[3]}

    # -- connection registry (Nango mapping) ----------------------------------
    def register_connection(
        self, va_id: str, provider_config_key: str, connection_id: str, *, status: str = "ACTIVE"
    ) -> dict[str, Any]:
        record_id = f"conn-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO oauth_connections(id, va_id, provider_config_key,"
                " connection_id, status, updated_at) VALUES(?,?,?,?,?,?)",
                (record_id, va_id, provider_config_key, connection_id, status, now),
            )
            self._conn.commit()
        return {
            "id": record_id,
            "va_id": va_id,
            "provider_config_key": provider_config_key,
            "connection_id": connection_id,
            "status": status,
        }

    def connections_for(self, va_id: str, *, provider_config_key: str = "") -> list[dict[str, Any]]:
        query = (
            "SELECT id, va_id, provider_config_key, connection_id, status, updated_at"
            " FROM oauth_connections WHERE va_id = ?"
        )
        params: list[Any] = [va_id]
        if provider_config_key:
            query += " AND provider_config_key = ?"
            params.append(provider_config_key)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "id": r[0],
                "va_id": r[1],
                "provider_config_key": r[2],
                "connection_id": r[3],
                "status": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]

    # -- encrypted browser profiles --------------------------------------------
    def save_browser_profile(self, va_id: str, domain: str, auth_state: dict[str, Any]) -> dict[str, Any]:
        blob = self._fernet.encrypt(json.dumps(auth_state).encode()).decode()
        profile_id = f"bp-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO browser_profiles(id, va_id, domain, encrypted_auth_state,"
                " last_verified_at, is_active) VALUES(?,?,?,?,?,1)",
                (profile_id, va_id, domain, blob, now),
            )
            self._conn.commit()
        return {"id": profile_id, "va_id": va_id, "domain": domain, "last_verified_at": now}

    def load_browser_profile(self, va_id: str, domain: str) -> dict[str, Any] | None:
        """Decrypt and return the stored auth state. Raw cookies never logged."""
        with self._lock:
            row = self._conn.execute(
                "SELECT encrypted_auth_state FROM browser_profiles WHERE va_id = ? AND domain = ? AND is_active = 1",
                (va_id, domain),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(self._fernet.decrypt(row[0].encode()).decode())
        except Exception:
            return None

    def deactivate_browser_profile(self, va_id: str, domain: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE browser_profiles SET is_active = 0 WHERE va_id = ? AND domain = ?", (va_id, domain)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    # -- audit trail --------------------------------------------------------------
    def record_audit(
        self,
        *,
        va_id: str = "",
        event_type: str,
        confidence_score: float = 0.0,
        execution_mode: str = "",
        execution_pathway: str = "",
        payload_snapshot: dict[str, Any] | None = None,
    ) -> str:
        audit_id = f"audit-{uuid.uuid4().hex[:12]}"
        # Snapshot is redacted by callers; enforce a ceiling anyway.
        snapshot = json.dumps(payload_snapshot or {})[:20000]
        with self._lock:
            self._conn.execute(
                "INSERT INTO ghost_audit_logs(id, va_id, event_type, confidence_score,"
                " execution_mode, execution_pathway, payload_snapshot, timestamp)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (
                    audit_id,
                    va_id,
                    event_type,
                    confidence_score,
                    execution_mode,
                    execution_pathway,
                    snapshot,
                    time.time(),
                ),
            )
            self._conn.commit()
        return audit_id

    def audit_for(self, va_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, event_type, confidence_score, execution_mode, execution_pathway,"
                " timestamp FROM ghost_audit_logs WHERE va_id = ? ORDER BY timestamp DESC LIMIT ?",
                (va_id, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "event_type": r[1],
                "confidence_score": r[2],
                "execution_mode": r[3],
                "execution_pathway": r[4],
                "timestamp": r[5],
            }
            for r in rows
        ]


__all__ = ["BpoStore"]
