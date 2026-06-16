"""Bi-temporal knowledge-graph memory for Ghost Chimera.

This module adds a *beyond-RAG* memory primitive on top of the existing
:class:`~ghostchimera.memory_layer.store.MemoryStore` full-text store.  Instead
of treating memory as a flat, append-only log, facts are modelled as edges in a
knowledge graph between entity nodes, and every edge carries **bi-temporal**
provenance:

* ``valid_from`` / ``valid_to`` — when the fact is/was true *in the world*.
* ``recorded_at`` / ``expired_at`` — when the system *learned* / *retired* it.

This is the design proven by temporal-knowledge-graph agent memory (Zep /
Graphiti): it lets Ghost change its beliefs about the user over time without
rewriting history, and answer point-in-time questions ("what was true as of
last week?") while keeping a tamper-evident provenance trail.

The store is intentionally dependency-free (pure ``sqlite3``) so it runs on the
same constrained local hardware as the rest of the runtime.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_iso(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        ts = value if value.tzinfo else value.replace(tzinfo=UTC)
        return ts.isoformat()
    return str(value)


@dataclass(frozen=True)
class Fact:
    """A single bi-temporal edge in the knowledge graph."""

    id: int
    subject: str
    predicate: str
    obj: str | None
    value: str | None
    confidence: float
    valid_from: str | None
    valid_to: str | None
    recorded_at: str
    expired_at: str | None
    provenance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.obj,
            "value": self.value,
            "confidence": self.confidence,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "recorded_at": self.recorded_at,
            "expired_at": self.expired_at,
            "provenance": self.provenance,
        }


def _iso_le(a: str | None, b: str | None) -> bool:
    """Return True if timestamp *a* <= *b*, treating None as open bounds."""

    if a is None or b is None:
        return True
    return a <= b


class TemporalGraphStore:
    """Persist and query a bi-temporal knowledge graph of facts."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # -- mutation ---------------------------------------------------------
    def add_entity(self, name: str, *, kind: str = "entity") -> int:
        name = name.strip()
        if not name:
            raise ValueError("entity name is required")
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM tg_entities WHERE name = ?", (name,)).fetchone()
            if row:
                return int(row["id"])
            cursor = conn.execute(
                "INSERT INTO tg_entities(name, kind, created_at) VALUES (?, ?, ?)",
                (name, kind, _now_iso()),
            )
            return int(cursor.lastrowid)

    def add_fact(
        self,
        subject: str,
        predicate: str,
        *,
        obj: str | None = None,
        value: str | None = None,
        confidence: float = 1.0,
        valid_from: str | datetime | None = None,
        valid_to: str | datetime | None = None,
        provenance: dict[str, Any] | None = None,
        exclusive: bool = False,
        recorded_at: str | datetime | None = None,
    ) -> int:
        """Record a new fact edge.

        When ``exclusive`` is set, any currently-active fact with the same
        ``subject``/``predicate`` is system-expired first (belief revision):
        the old edge is retained for history but no longer returned by
        :meth:`active_facts`.
        """

        subject = subject.strip()
        predicate = predicate.strip()
        if not subject or not predicate:
            raise ValueError("subject and predicate are required")
        if obj is None and value is None:
            raise ValueError("a fact requires either an object or a value")
        confidence = max(0.0, min(1.0, float(confidence)))
        now = _as_iso(recorded_at) or _now_iso()

        self.add_entity(subject)
        if obj is not None:
            self.add_entity(obj)

        with self._connect() as conn:
            if exclusive:
                conn.execute(
                    """
                    UPDATE tg_facts SET expired_at = ?
                    WHERE subject = ? AND predicate = ? AND expired_at IS NULL
                    """,
                    (now, subject, predicate),
                )
            cursor = conn.execute(
                """
                INSERT INTO tg_facts(
                    subject, predicate, object, value, confidence,
                    valid_from, valid_to, recorded_at, expired_at, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    subject,
                    predicate,
                    obj,
                    value,
                    confidence,
                    _as_iso(valid_from),
                    _as_iso(valid_to),
                    now,
                    json.dumps(provenance or {}, sort_keys=True),
                ),
            )
            return int(cursor.lastrowid)

    def invalidate_fact(self, fact_id: int, *, at: str | datetime | None = None) -> bool:
        """System-expire a fact (it was wrong or has been retracted)."""

        stamp = _as_iso(at) or _now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE tg_facts SET expired_at = ? WHERE id = ? AND expired_at IS NULL",
                (stamp, int(fact_id)),
            )
            return cursor.rowcount > 0

    # -- query ------------------------------------------------------------
    def active_facts(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        as_of: str | datetime | None = None,
        system_time: str | datetime | None = None,
        min_confidence: float = 0.0,
        limit: int = 100,
    ) -> list[Fact]:
        """Return facts that hold at a point in *valid* and *system* time.

        ``as_of`` filters the real-world validity window; ``system_time``
        filters which facts the system believed at that moment.  Both default
        to "now".
        """

        as_of_iso = _as_iso(as_of) or _now_iso()
        sys_iso = _as_iso(system_time) or _now_iso()
        limit = max(1, min(int(limit), 1000))

        clauses = ["recorded_at <= ?", "(expired_at IS NULL OR expired_at > ?)", "confidence >= ?"]
        params: list[Any] = [sys_iso, sys_iso, float(min_confidence)]
        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject.strip())
        if predicate is not None:
            clauses.append("predicate = ?")
            params.append(predicate.strip())

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM tg_facts WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
                (*params, limit * 4),
            ).fetchall()

        facts: list[Fact] = []
        for row in rows:
            if not _iso_le(row["valid_from"], as_of_iso):
                continue
            if row["valid_to"] is not None and not _iso_le(as_of_iso, row["valid_to"]):
                continue
            facts.append(self._row_to_fact(row))
            if len(facts) >= limit:
                break
        return facts

    def neighbors(self, entity: str, *, max_hops: int = 1, as_of: str | datetime | None = None) -> list[Fact]:
        """Breadth-first traversal of active fact edges from *entity*."""

        entity = entity.strip()
        max_hops = max(1, min(int(max_hops), 5))
        seen_facts: dict[int, Fact] = {}
        frontier = {entity}
        visited: set[str] = set()
        for _ in range(max_hops):
            next_frontier: set[str] = set()
            for node in frontier:
                if node in visited:
                    continue
                visited.add(node)
                for fact in self.active_facts(subject=node, as_of=as_of, limit=1000):
                    seen_facts[fact.id] = fact
                    if fact.obj and fact.obj not in visited:
                        next_frontier.add(fact.obj)
            frontier = next_frontier
            if not frontier:
                break
        return sorted(seen_facts.values(), key=lambda f: f.id)

    def system_active_facts(self, *, limit: int = 1000) -> list[Fact]:
        """Return all facts the system currently believes (``expired_at IS NULL``).

        Unlike :meth:`active_facts`, this ignores the real-world validity window,
        so callers (e.g. consolidation) can inspect facts whose ``valid_to`` lies
        in the past in order to retire them.
        """

        limit = max(1, min(int(limit), 10000))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tg_facts WHERE expired_at IS NULL ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_fact(row) for row in rows]

    def history(self, *, subject: str, predicate: str) -> list[Fact]:
        """Return all edges (active and expired) for a subject/predicate."""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tg_facts WHERE subject = ? AND predicate = ? ORDER BY id ASC",
                (subject.strip(), predicate.strip()),
            ).fetchall()
        return [self._row_to_fact(row) for row in rows]

    def count(self, *, active_only: bool = False) -> int:
        sql = "SELECT COUNT(*) AS n FROM tg_facts"
        if active_only:
            sql += " WHERE expired_at IS NULL"
        with self._connect() as conn:
            row = conn.execute(sql).fetchone()
            return int(row["n"]) if row else 0

    # -- internals --------------------------------------------------------
    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
        return Fact(
            id=int(row["id"]),
            subject=row["subject"],
            predicate=row["predicate"],
            obj=row["object"],
            value=row["value"],
            confidence=float(row["confidence"]),
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            recorded_at=row["recorded_at"],
            expired_at=row["expired_at"],
            provenance=json.loads(row["provenance_json"] or "{}"),
        )

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tg_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL DEFAULT 'entity',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tg_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT,
                    value TEXT,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    valid_from TEXT,
                    valid_to TEXT,
                    recorded_at TEXT NOT NULL,
                    expired_at TEXT,
                    provenance_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tg_facts_sp ON tg_facts(subject, predicate)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tg_facts_active ON tg_facts(expired_at)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
