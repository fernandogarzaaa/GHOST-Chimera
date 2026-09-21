"""Single-use scoped action approvals for connector side effects.

A write (non-GET) connector call is bound at request time to
sha256(provider + method + url + canonical-body + scope): the approval
authorizes exactly that action, once, within a TTL. Any byte difference —
different destination, different payload, replay — fails closed. Reads
(GET) never need approval. Decisions are human-only (console UI); the
agent proposes, never self-approves. SQLite-backed, single-use enforced
in a transaction.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_ACTION_TTL_S = 600.0
MAX_BODY_BYTES = 8 * 1024


class ActionApprovalError(RuntimeError):
    pass


def action_digest(provider: str, method: str, url: str, data: Any, scope: str = "") -> str:
    """Stable hash binding an approval to exactly one action."""
    try:
        body = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        body = str(data)
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise ActionApprovalError("action body too large to approve safely")
    canonical = "\x00".join(
        [provider.strip().lower(), method.strip().upper(), url.strip(), body, str(scope or "").strip()]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ActionApprovalStore:
    """SQLite single-use approval ledger."""

    def __init__(self, state_dir: str | Path) -> None:
        self.path = Path(state_dir) / "action_approvals.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock:
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS action_approvals (
              id TEXT PRIMARY KEY,
              entity_id TEXT NOT NULL,
              provider TEXT NOT NULL,
              method TEXT NOT NULL,
              url TEXT NOT NULL,
              digest TEXT NOT NULL,
              scope TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              state TEXT NOT NULL DEFAULT 'PENDING',
              requested_by TEXT NOT NULL DEFAULT '',
              decided_by TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              expires_at REAL NOT NULL,
              decided_at REAL NOT NULL DEFAULT 0,
              used_at REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_action_entity ON action_approvals(entity_id, state);
            """)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def request(
        self,
        entity_id: str,
        provider: str,
        method: str,
        url: str,
        data: Any,
        *,
        scope: str = "",
        summary: str = "",
        requested_by: str = "",
        ttl_s: float = DEFAULT_ACTION_TTL_S,
    ) -> dict[str, Any]:
        if not entity_id or not provider or not url:
            raise ActionApprovalError("entity_id, provider, and url are required")
        method = method.upper()
        if method == "GET":
            raise ActionApprovalError("reads never need approval")
        digest = action_digest(provider, method, url, data, scope)
        record_id = f"act-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO action_approvals(id, entity_id, provider, method, url, digest,"
                " scope, summary, state, requested_by, created_at, expires_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id,
                    entity_id,
                    provider.strip().lower(),
                    method,
                    url.strip(),
                    digest,
                    str(scope or ""),
                    str(summary or "")[:300],
                    "PENDING",
                    str(requested_by or ""),
                    now,
                    now + max(1.0, float(ttl_s)),
                ),
            )
            self._conn.commit()
        return {"id": record_id, "digest": digest, "state": "PENDING"}

    def decide(self, approval_id: str, *, approved: bool, actor: str) -> dict[str, Any]:
        """Human decision. Terminal; late decisions expire instead."""
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT state, expires_at FROM action_approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                raise ActionApprovalError("unknown approval")
            state, expires_at = row
            if state != "PENDING" or now >= float(expires_at):
                self._conn.execute(
                    "UPDATE action_approvals SET state='EXPIRED', decided_at=? WHERE id=? AND state='PENDING'",
                    (now, approval_id),
                )
                self._conn.commit()
                return {"id": approval_id, "state": "EXPIRED"}
            final = "APPROVED" if approved else "DENIED"
            self._conn.execute(
                "UPDATE action_approvals SET state=?, decided_by=?, decided_at=? WHERE id=?",
                (final, actor, now, approval_id),
            )
            self._conn.commit()
            return {"id": approval_id, "state": final}

    def consume(self, entity_id: str, provider: str, method: str, url: str, data: Any, approval_id: str) -> bool:
        """Verify an approval matches this exact action and burn it (single-use)."""
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT entity_id, provider, scope, state, expires_at FROM action_approvals WHERE id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return False
            try:
                digest = action_digest(provider, method, url, data, row[2] or "")
            except ActionApprovalError:
                return False
            check = self._conn.execute("SELECT digest FROM action_approvals WHERE id = ?", (approval_id,)).fetchone()
            if (
                row[0] != entity_id
                or row[1] != provider.strip().lower()
                or check[0] != digest
                or row[3] != "APPROVED"
                or now >= float(row[4])
            ):
                return False
            cursor = self._conn.execute(
                "UPDATE action_approvals SET state='USED', used_at=? WHERE id=? AND state='APPROVED'",
                (now, approval_id),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def pending(self, entity_id: str) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE action_approvals SET state='EXPIRED' WHERE state='PENDING' AND expires_at <= ?", (now,)
            )
            self._conn.commit()
            rows = self._conn.execute(
                "SELECT id, provider, method, url, scope, summary, requested_by, created_at, expires_at"
                " FROM action_approvals WHERE entity_id = ? AND state = 'PENDING' ORDER BY created_at",
                (entity_id,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "provider": r[1],
                "method": r[2],
                "url": r[3],
                "scope": r[4],
                "summary": r[5],
                "requested_by": r[6],
                "created_at": r[7],
                "expires_at": r[8],
            }
            for r in rows
        ]

    def describe(self, approval_id: str) -> dict[str, Any] | None:
        """Fetch one record by id (for cross-system sync). Redacted summary only."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, entity_id, provider, method, url, scope, summary,"
                " state, requested_by, decided_by, created_at, expires_at"
                " FROM action_approvals WHERE id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "entity_id": row[1],
            "provider": row[2],
            "method": row[3],
            "url": row[4],
            "scope": row[5],
            "summary": row[6],
            "state": row[7],
            "requested_by": row[8],
            "decided_by": row[9],
            "created_at": row[10],
            "expires_at": row[11],
        }

    def sweep(self) -> int:
        now = time.time()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE action_approvals SET state='EXPIRED' WHERE state='PENDING' AND expires_at <= ?", (now,)
            )
            self._conn.commit()
            return cursor.rowcount


__all__ = [
    "DEFAULT_ACTION_TTL_S",
    "ActionApprovalError",
    "ActionApprovalStore",
    "action_digest",
]
