"""SQLite-backed memory store for Conscious Workspace Retrieval."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import Any


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

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(int(limit), 25))
        fts_query = self._to_fts_query(query)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.source, d.content, d.metadata_json, bm25(memory_documents_fts) AS rank
                FROM memory_documents_fts
                JOIN memory_documents d ON d.id = memory_documents_fts.rowid
                WHERE memory_documents_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "source": row["source"],
                "content": row["content"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "score": round(1.0 / (1.0 + abs(float(row["rank"]))), 6),
            }
            for row in rows
        ]

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
