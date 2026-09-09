"""StealthStore: durable SQLite backbone for the ambient runtime.

Do we need a database? Yes — but an embedded one. Ghost is local-first:
the hot path stays in memory while SQLite/WAL durably journals events,
interventions, outcomes, and workflow hypotheses. No server, no network,
crash-safe. Postgres (or the existing SaaS store) remains the answer
only for multi-user hosted deployments — not for the local runtime.

Tables:
- events(event_id PK, event_type, timestamp, source, actor, payload,
  provenance, correlation_id, session_id, privacy_class, confidence)
- interventions(id PK, trigger_event_id, workflow, confidence, state,
  outcome, reason, provenance, created_at, updated_at)
- outcomes(id PK, intervention_id, workflow, outcome, recorded_at)
- workflows(name PK, pattern_json, support, confidence, explicit,
  updated_at)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  timestamp REAL NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  actor TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}',
  provenance TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL DEFAULT '',
  session_id TEXT NOT NULL DEFAULT '',
  privacy_class TEXT NOT NULL DEFAULT 'internal',
  confidence REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, timestamp);
CREATE TABLE IF NOT EXISTS interventions (
  id TEXT PRIMARY KEY,
  trigger_event_id TEXT NOT NULL DEFAULT '',
  workflow TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0.0,
  state TEXT NOT NULL DEFAULT 'created',
  outcome TEXT NOT NULL DEFAULT 'pending',
  reason TEXT NOT NULL DEFAULT '',
  provenance TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  intervention_id TEXT NOT NULL,
  workflow TEXT NOT NULL DEFAULT '',
  outcome TEXT NOT NULL,
  recorded_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outcomes_workflow ON outcomes(workflow, recorded_at);
CREATE TABLE IF NOT EXISTS workflows (
  name TEXT PRIMARY KEY,
  pattern_json TEXT NOT NULL DEFAULT '[]',
  support INTEGER NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0.0,
  explicit INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL
);
"""


class StealthStore:
    """Thread-safe SQLite journal. All writes are INSERT OR REPLACE —
    replays are idempotent by primary key."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- events -----------------------------------------------------------
    def record_event(self, event: Any) -> None:
        d = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO events(event_id, event_type, timestamp, source, actor,"
                " payload, provenance, correlation_id, session_id, privacy_class, confidence)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (d["event_id"], d["event_type"], float(d.get("timestamp", time.time())),
                 str(d.get("source", "")), str(d.get("actor", "")),
                 json.dumps(d.get("payload") or {}), json.dumps(d.get("provenance") or {}),
                 str(d.get("correlation_id", "")), str(d.get("session_id", "")),
                 str(d.get("privacy_classification", d.get("privacy_class", "internal"))),
                 float(d.get("confidence", 1.0))),
            )
            self._conn.commit()

    def recent_events(self, *, event_type: str | None = None, session_id: str | None = None,
                      limit: int = 100) -> list[dict[str, Any]]:
        query = ("SELECT event_id, event_type, timestamp, source, actor, payload, provenance,"
                 " correlation_id, session_id, privacy_class, confidence FROM events")
        clauses: list[str] = []
        params: list[Any] = []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        out = []
        for row in rows:
            out.append({
                "event_id": row[0], "event_type": row[1], "timestamp": row[2], "source": row[3],
                "actor": row[4], "payload": json.loads(row[5]), "provenance": json.loads(row[6]),
                "correlation_id": row[7], "session_id": row[8],
                "privacy_classification": row[9], "confidence": row[10],
            })
        return out

    def count_events(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    # -- interventions + outcomes ------------------------------------------
    def record_intervention(self, intervention: Any) -> None:
        d = intervention.__dict__ if not hasattr(intervention, "to_dict") else None
        now = time.time()
        with self._lock:
            if d is None:  # duck-typed mapping
                m = dict(intervention)
                self._conn.execute(
                    "INSERT OR REPLACE INTO interventions(id, trigger_event_id, workflow, confidence,"
                    " state, outcome, reason, provenance, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (m["id"], m.get("trigger_event_id", ""), m.get("workflow", ""),
                     float(m.get("confidence", 0.0)), m.get("state", "created"),
                     m.get("outcome", "pending"), m.get("reason", ""),
                     json.dumps(m.get("provenance") or {}),
                     float(m.get("created_at", now)), now))
            else:
                self._conn.execute(
                    "INSERT OR REPLACE INTO interventions(id, trigger_event_id, workflow, confidence,"
                    " state, outcome, reason, provenance, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (d["id"], d.get("trigger_event_id", ""), d.get("workflow", ""),
                     float(d.get("confidence", 0.0)), str(d.get("state", "created")),
                     str(d.get("outcome", "pending")), str(d.get("reason", "")),
                     json.dumps(d.get("provenance") or {}),
                     float(d.get("created_at", now)), now))
            self._conn.commit()

    def record_outcome(self, intervention_id: str, workflow: str, outcome: str) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute("INSERT INTO outcomes(intervention_id, workflow, outcome, recorded_at)"
                               " VALUES(?,?,?,?)", (intervention_id, workflow, outcome, now))
            self._conn.execute("UPDATE interventions SET outcome = ?, state = 'outcome',"
                               " updated_at = ? WHERE id = ?", (outcome, now, intervention_id))
            self._conn.commit()

    def useful_intervention_rate(self, workflow: str | None = None) -> float:
        """The key product metric, straight from the journal."""
        clauses, params = [], []
        if workflow:
            clauses.append("workflow = ?")
            params.append(workflow)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            total = int(self._conn.execute(
                f"SELECT COUNT(*) FROM outcomes{where}", params).fetchone()[0])
            useful = int(self._conn.execute(
                f"SELECT COUNT(*) FROM outcomes{where}"
                f"{' AND' if where else ' WHERE'} outcome IN ('useful','successful')",
                params).fetchone()[0])
        if not total:
            return 0.0
        return useful / total

    # -- workflows ------------------------------------------------------------
    def upsert_workflow(self, name: str, pattern: list[str], support: int,
                        confidence: float, *, explicit: bool = False) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO workflows(name, pattern_json, support, confidence,"
                " explicit, updated_at) VALUES(?,?,?,?,?,?)",
                (name, json.dumps(pattern), support, confidence, int(explicit), time.time()))
            self._conn.commit()

    def load_workflows(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, pattern_json, support, confidence, explicit FROM workflows").fetchall()
        return [{"name": r[0], "pattern": json.loads(r[1]), "support": r[2],
                 "confidence": r[3], "explicit": bool(r[4])} for r in rows]


__all__ = ["StealthStore"]
