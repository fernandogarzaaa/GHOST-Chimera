"""Sleep-time memory consolidation for Ghost Chimera.

Long-running agents degrade if memory is a flat, ever-growing log.  Cognitive
agent research (Generative Agents, MemoryOS, Letta sleep-time compute) converges
on a *consolidation* phase analogous to human sleep: recent episodic evidence is
scored, the most salient items are promoted into durable semantic memory, and
stale or superseded items are expired.

This module operates on the :class:`~ghostchimera.memory_layer.store.MemoryStore`
(episodic full-text buffer) and the
:class:`~ghostchimera.memory_layer.temporal_graph.TemporalGraphStore` (durable
bi-temporal facts).  It is deterministic and dependency-free so it can run as a
recurring local job via the existing CronScheduler without any model call.

The heat score follows MemoryOS: a composite of recency, access frequency, and
content salience.  Only items above a promotion threshold graduate to the
semantic graph, with provenance pointing back to the originating episodic id.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .store import MemoryStore
from .temporal_graph import TemporalGraphStore

_RECENCY_HALF_LIFE_DAYS = 14.0
_DEFAULT_PROMOTION_THRESHOLD = 0.55
# subject predicate object  — a minimal triple grammar for promotion.
_TRIPLE_RE = re.compile(r"^\s*(?P<s>[\w .'-]+?)\s+(?P<p>[a-z_]+)\s+(?P<o>.+?)\s*$")


def _recency_score(created_at: str, *, now: datetime, half_life_days: float = _RECENCY_HALF_LIFE_DAYS) -> float:
    if not created_at:
        return 0.5
    try:
        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return 0.5
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    return math.exp(-math.log(2) * age_days / half_life_days)


def _salience_score(content: str) -> float:
    """Longer, information-dense content is more salient, bounded to [0, 1]."""

    words = content.split()
    if not words:
        return 0.0
    length_score = min(1.0, len(words) / 40.0)
    unique_ratio = len(set(w.lower() for w in words)) / len(words)
    return round(0.7 * length_score + 0.3 * unique_ratio, 6)


def heat_score(
    *,
    created_at: str,
    access_count: int,
    content: str,
    now: datetime | None = None,
) -> float:
    """Composite recency + frequency + salience score in [0, 1] (MemoryOS-style)."""

    now = now or datetime.now(UTC)
    recency = _recency_score(created_at, now=now)
    frequency = 1.0 - math.exp(-max(0, int(access_count)) / 5.0)
    salience = _salience_score(content)
    return round(0.45 * recency + 0.25 * frequency + 0.30 * salience, 6)


@dataclass
class ConsolidationReport:
    """Outcome of a single consolidation pass."""

    scanned: int = 0
    promoted: int = 0
    skipped_low_heat: int = 0
    skipped_unparseable: int = 0
    expired_stale: int = 0
    promoted_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "promoted": self.promoted,
            "skipped_low_heat": self.skipped_low_heat,
            "skipped_unparseable": self.skipped_unparseable,
            "expired_stale": self.expired_stale,
            "promoted_ids": list(self.promoted_ids),
        }


class MemoryConsolidator:
    """Promote salient episodic memories into the durable temporal graph."""

    def __init__(
        self,
        episodic: MemoryStore,
        semantic: TemporalGraphStore,
        *,
        promotion_threshold: float = _DEFAULT_PROMOTION_THRESHOLD,
        stale_after_days: float = 365.0,
    ) -> None:
        self.episodic = episodic
        self.semantic = semantic
        self.promotion_threshold = float(promotion_threshold)
        self.stale_after_days = float(stale_after_days)

    def consolidate(self, *, limit: int = 200, now: datetime | None = None) -> ConsolidationReport:
        """Run one consolidation pass over recent episodic memory."""

        now = now or datetime.now(UTC)
        report = ConsolidationReport()
        for doc in self.episodic.recent_documents(limit=limit):
            report.scanned += 1
            content = (doc.get("content") or "").strip()
            metadata = doc.get("metadata") or {}
            access_count = int(metadata.get("access_count", 0))
            heat = heat_score(
                created_at=doc.get("created_at", ""),
                access_count=access_count,
                content=content,
                now=now,
            )
            if heat < self.promotion_threshold:
                report.skipped_low_heat += 1
                continue
            triple = self._extract_triple(content, metadata)
            if triple is None:
                report.skipped_unparseable += 1
                continue
            subject, predicate, obj = triple
            self.semantic.add_fact(
                subject,
                predicate,
                obj=obj,
                confidence=round(min(1.0, heat), 6),
                exclusive=bool(metadata.get("exclusive", False)),
                provenance={
                    "episodic_id": doc.get("id"),
                    "source": doc.get("source"),
                    "heat": heat,
                },
            )
            report.promoted += 1
            report.promoted_ids.append(int(doc["id"]))
        return report

    def expire_stale(self, *, now: datetime | None = None, limit: int = 1000) -> int:
        """System-expire durable facts whose validity ended long ago."""

        now = now or datetime.now(UTC)
        cutoff = now.timestamp() - self.stale_after_days * 86400.0
        expired = 0
        for fact in self.semantic.system_active_facts(limit=limit):
            if not fact.valid_to:
                continue
            try:
                vt = datetime.fromisoformat(fact.valid_to.replace("Z", "+00:00"))
                if vt.tzinfo is None:
                    vt = vt.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue
            if vt.timestamp() < cutoff and self.semantic.invalidate_fact(fact.id, at=now):
                expired += 1
        return expired

    def run(self, *, limit: int = 200, now: datetime | None = None) -> ConsolidationReport:
        """Full sleep-time pass: promote salient memories then expire stale facts."""

        now = now or datetime.now(UTC)
        report = self.consolidate(limit=limit, now=now)
        report.expired_stale = self.expire_stale(now=now)
        return report

    def _extract_triple(
        self, content: str, metadata: dict[str, Any]
    ) -> tuple[str, str, str] | None:
        """Derive a (subject, predicate, object) triple for the semantic graph.

        Structured metadata wins; otherwise a minimal triple grammar is applied
        to the content.  Returns ``None`` when no confident triple is available.
        """

        s = str(metadata.get("subject", "")).strip()
        p = str(metadata.get("predicate", "")).strip()
        o = str(metadata.get("object", "")).strip()
        if s and p and o:
            return s, p, o
        match = _TRIPLE_RE.match(content)
        if not match:
            return None
        obj = match.group("o").strip()
        if len(obj.split()) > 6:  # too long to be a clean object node
            return None
        return match.group("s").strip(), match.group("p").strip(), obj
