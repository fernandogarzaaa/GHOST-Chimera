"""SQLite-backed memory store for Conscious Workspace Retrieval."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_FRESHNESS_HALF_LIFE_DAYS: float = 30.0


def _freshness_score(created_at: str, *, half_life_days: float = _DEFAULT_FRESHNESS_HALF_LIFE_DAYS) -> float:
    """Return a [0, 1] freshness score using exponential decay from *created_at*.

    A document created now scores 1.0; a document created *half_life_days* ago
    scores ~0.5; older documents approach 0.0 asymptotically.
    """
    if not created_at:
        return 0.5
    try:
        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        age_days = max(0.0, (datetime.now(UTC) - ts).total_seconds() / 86400.0)
    except (ValueError, TypeError):
        return 0.5
    if half_life_days <= 0:
        return 1.0
    import math
    return round(math.exp(-math.log(2) * age_days / half_life_days), 6)


def _citation_quality(content: str, freshness: float) -> float:
    """Heuristic citation-quality score combining content length and freshness.

    A short, stale document scores low; a long, fresh document scores high.
    The score is bounded to [0, 1].
    """
    length_score = min(1.0, len(content) / 200.0)
    return round(min(1.0, 0.6 * freshness + 0.4 * length_score), 6)


class MemoryStore:
    """Persist and search local memory documents."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def add_document(
        self,
        source: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if not source.strip():
            raise ValueError("source is required")
        if not content.strip():
            raise ValueError("content is required")

        metadata_json = json.dumps(metadata or {}, sort_keys=True)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO memory_documents(source, content, metadata_json) VALUES (?, ?, ?)",
                (source, content, metadata_json),
            )
            rowid = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO memory_documents_fts(rowid, source, content) VALUES (?, ?, ?)",
                (rowid, source, content),
            )
            return rowid

    def add_document_once(
        self,
        source: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[int, bool]:
        """Insert a memory document unless the same source/content already exists."""

        if not source.strip():
            raise ValueError("source is required")
        if not content.strip():
            raise ValueError("content is required")
        metadata_json = json.dumps(metadata or {}, sort_keys=True)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM memory_documents WHERE source = ? AND content = ? LIMIT 1",
                (source, content),
            ).fetchone()
            if existing:
                return int(existing["id"]), False
            cursor = conn.execute(
                "INSERT INTO memory_documents(source, content, metadata_json) VALUES (?, ?, ?)",
                (source, content, metadata_json),
            )
            rowid = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO memory_documents_fts(rowid, source, content) VALUES (?, ?, ?)",
                (rowid, source, content),
            )
            return rowid, True

    def count(self) -> int:
        """Return the total number of documents in the store."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM memory_documents").fetchone()
            return int(row["n"]) if row else 0

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        stale_after_days: float | None = None,
        freshness_half_life_days: float = _DEFAULT_FRESHNESS_HALF_LIFE_DAYS,
    ) -> list[dict[str, Any]]:
        """Full-text search against the memory store.

        Parameters
        ----------
        query:
            Search terms.  An empty query returns an empty list immediately.
        limit:
            Maximum number of results (capped at 25).
        stale_after_days:
            When set, documents older than this many days are excluded from
            results.  ``None`` (default) disables age filtering.
        freshness_half_life_days:
            Half-life in days used by the exponential-decay freshness score.
        """
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(int(limit), 25))
        fts_query = self._to_fts_query(query)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.source, d.content, d.metadata_json,
                       d.created_at, bm25(memory_documents_fts) AS rank
                FROM memory_documents_fts
                JOIN memory_documents d ON d.id = memory_documents_fts.rowid
                WHERE memory_documents_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit * 4 if stale_after_days is not None else limit),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            created_at = row["created_at"] or ""
            freshness = _freshness_score(created_at, half_life_days=freshness_half_life_days)

            if stale_after_days is not None and stale_after_days > 0:
                try:
                    ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                    age_days = (datetime.now(UTC) - ts).total_seconds() / 86400.0
                    if age_days > stale_after_days:
                        continue
                except (ValueError, TypeError):
                    pass

            content = row["content"]
            results.append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "content": content,
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                    "score": round(1.0 / (1.0 + abs(float(row["rank"]))), 6),
                    "freshness_score": freshness,
                    "citation_quality": _citation_quality(content, freshness),
                    "created_at": created_at,
                }
            )
            if len(results) >= limit:
                break

        return results

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_documents_fts
                USING fts5(source, content, content='memory_documents', content_rowid='id')
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backend_id TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    latency_ms REAL NOT NULL,
                    verifier_score REAL NOT NULL DEFAULT 0.0,
                    policy_warnings_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def record_outcome(
        self,
        *,
        backend_id: str,
        task_kind: str,
        success: bool,
        latency_ms: float,
        verifier_score: float = 0.0,
        policy_warnings: list[str] | None = None,
    ) -> int:
        warnings_json = json.dumps(policy_warnings or [], sort_keys=True)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO orchestration_outcomes(
                    backend_id, task_kind, success, latency_ms, verifier_score, policy_warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (backend_id, task_kind, 1 if success else 0, float(latency_ms), float(verifier_score), warnings_json),
            )
            return int(cursor.lastrowid)

    def recent_outcomes(self, *, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT backend_id, task_kind, success, latency_ms, verifier_score, policy_warnings_json, created_at
                FROM orchestration_outcomes
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "backend_id": row["backend_id"],
                "task_kind": row["task_kind"],
                "success": bool(row["success"]),
                "latency_ms": float(row["latency_ms"]),
                "verifier_score": float(row["verifier_score"]),
                "policy_warnings": json.loads(row["policy_warnings_json"] or "[]"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _to_fts_query(self, query: str) -> str:
        terms = [term.replace('"', "") for term in query.split() if term.strip()]
        if not terms:
            return '""'
        return " OR ".join(f'"{term}"' for term in terms)
