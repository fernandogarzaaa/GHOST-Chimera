"""Context Fabric: what should the host AI see right now?

Not "RAG" — adaptive context selection. Given the current event,
session, world state, matched workflow, predictions, host, token
budget, and privacy policy, assemble ranked, provenance-preserving
context. Every injected item retains provenance. Privacy-denied items
never leave the fabric.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .events import Event


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Cheap; no tokenizer needed."""
    return max(1, len(text) // 4)


@dataclass
class ContextItem:
    source: str  # e.g. "memory:episodic", "graph:semantic", "workflow:state"
    kind: str  # "fact" | "memory" | "event" | "workflow" | "warning" | "document"
    text: str
    score: float = 0.5
    confidence: float = 0.5
    provenance: dict[str, Any] = field(default_factory=dict)
    privacy_class: str = "internal"
    recency: float = field(default_factory=time.time)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "text": self.text,
            "score": round(self.score, 3),
            "confidence": self.confidence,
            "provenance": dict(self.provenance),
            "privacy_class": self.privacy_class,
        }


class Retriever(Protocol):
    """Pluggable evidence source. Implementations query MemoryStore,
    TemporalGraphStore, PersonalContextProvider, files, etc."""

    name: str

    def retrieve(self, event: Event, context: dict[str, Any]) -> list[ContextItem]: ...


class InMemoryRetriever:
    """Deterministic test/dev retriever over a fixed item list."""

    name = "inmemory"

    def __init__(self, items: list[ContextItem] | None = None) -> None:
        self._items = list(items or [])

    def add(self, item: ContextItem) -> None:
        self._items.append(item)

    def retrieve(self, event: Event, context: dict[str, Any]) -> list[ContextItem]:
        query = " ".join([event.event_type, event.actor] + [str(v) for v in event.payload.values()]).lower()
        terms = {t for t in query.replace(".", " ").replace("_", " ").split() if len(t) > 2}
        out = []
        for item in self._items:
            text = item.text.lower()
            overlap = sum(1 for t in terms if t in text)
            relevance = overlap / max(1, len(terms))
            out.append(
                ContextItem(
                    source=item.source,
                    kind=item.kind,
                    text=item.text,
                    score=round(0.3 + 0.7 * relevance, 3),
                    confidence=item.confidence,
                    provenance=item.provenance,
                    privacy_class=item.privacy_class,
                    recency=item.recency,
                )
            )
        return out


class GhostMemoryRetriever:
    """Adapter over the existing MemoryStore (lazy import, no hard dep).

    Emits ``memory:*`` items with provenance + privacy passthrough.
    Failures degrade to [] — the fabric must never break the host.
    """

    name = "ghost-memory"

    def __init__(self, store: Any = None, *, limit: int = 8) -> None:
        self._store = store
        self._limit = limit

    def retrieve(self, event: Event, context: dict[str, Any]) -> list[ContextItem]:
        store = self._store
        if store is None:
            try:
                from ..memory_layer.store import MemoryStore

                store = MemoryStore()
            except Exception:
                return []
        query = f"{event.event_type} {event.actor} {' '.join(str(v) for v in event.payload.values())}"[:500]
        try:
            results = store.search(query, limit=self._limit)
        except Exception:
            return []
        items = []
        for row in results or []:
            if isinstance(row, dict):
                text = str(row.get("text") or row.get("content") or "")
                provenance = {k: v for k, v in row.items() if k not in ("text", "content")}
            else:
                text = str(getattr(row, "text", row))
                provenance = {"row": str(row)}
            if not text.strip():
                continue
            items.append(
                ContextItem(
                    source="memory:episodic",
                    kind="memory",
                    text=text[:2000],
                    score=float(provenance.get("score", 0.5)) if isinstance(provenance.get("score"), (int, float)) else 0.5,
                    confidence=float(provenance.get("confidence", 0.6)) if isinstance(provenance.get("confidence"), (int, float)) else 0.6,
                    provenance={"retriever": self.name, "query": query[:120], **provenance},
                    privacy_class=str(provenance.get("privacy_class", "internal")),
                )
            )
        return items


@dataclass
class RankedContext:
    items: list[ContextItem]
    dropped_for_budget: int = 0
    dropped_for_privacy: int = 0


class ContextRanker:
    """Deterministic rank: relevance + confidence + recency, minus cost/risk.

    Recency decays over 7 days. Privacy filtering happens before ranking
    so denied items can never leak via scores or ordering.
    """

    def __init__(self, *, w_relevance: float = 0.5, w_confidence: float = 0.3, w_recency: float = 0.2) -> None:
        self.w_relevance = w_relevance
        self.w_confidence = w_confidence
        self.w_recency = w_recency

    def rank(
        self,
        items: list[ContextItem],
        *,
        max_tokens: int = 4000,
        blocked_privacy: frozenset[str] = frozenset({"secret"}),
    ) -> RankedContext:
        now = time.time()
        kept: list[ContextItem] = []
        dropped_privacy = 0
        for item in items:
            if item.privacy_class in blocked_privacy:
                dropped_privacy += 1
                continue
            age_days = max(0.0, now - item.recency) / 86400.0
            recency = 1.0 / (1.0 + age_days / 7.0)
            item.score = round(
                self.w_relevance * item.score + self.w_confidence * item.confidence + self.w_recency * recency, 3
            )
            kept.append(item)
        kept.sort(key=lambda i: i.score, reverse=True)
        selected: list[ContextItem] = []
        used = 0
        dropped_budget = 0
        for item in kept:
            if used + item.tokens <= max_tokens:
                selected.append(item)
                used += item.tokens
            else:
                dropped_budget += 1
        return RankedContext(items=selected, dropped_for_budget=dropped_budget, dropped_for_privacy=dropped_privacy)


@dataclass
class ContextPackage:
    reason: str
    confidence: float
    workflow: str = ""
    items: list[ContextItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "confidence": self.confidence,
            "workflow": self.workflow,
            "tokens": self.tokens,
            "items": [i.to_dict() for i in self.items],
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }


class ContextFabric:
    """retrieve -> rank -> package. Host-agnostic; injection is separate."""

    def __init__(
        self,
        retrievers: list[Retriever] | None = None,
        ranker: ContextRanker | None = None,
        *,
        max_tokens: int = 4000,
    ) -> None:
        self.retrievers = list(retrievers or [InMemoryRetriever()])
        self.ranker = ranker or ContextRanker()
        self.max_tokens = max_tokens

    def assemble(
        self,
        event: Event,
        *,
        workflow: str = "",
        confidence: float = 0.0,
        reason: str = "workflow_match",
        extra_context: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> ContextPackage:
        ctx = dict(extra_context or {})
        gathered: list[ContextItem] = []
        for retriever in self.retrievers:
            try:
                gathered.extend(retriever.retrieve(event, ctx))
            except Exception:
                continue  # a failing source must not break the fabric
        ranked = self.ranker.rank(gathered, max_tokens=max_tokens or self.max_tokens)
        warnings = []
        if ranked.dropped_for_privacy:
            warnings.append(f"withheld {ranked.dropped_for_privacy} item(s) by privacy policy")
        package = ContextPackage(
            reason=reason,
            confidence=confidence,
            workflow=workflow,
            items=ranked.items,
            warnings=warnings,
            provenance={"event_id": event.event_id, "event_type": event.event_type},
        )
        package.tokens = sum(i.tokens for i in ranked.items)
        return package


@dataclass
class InjectionEnvelope:
    """Host-ready rendering of a ContextPackage. The host adapter decides
    placement (system preamble, tool result, subagent context...)."""

    package: ContextPackage
    host: str = "unknown"

    def render_markdown(self) -> str:
        lines = [
            f"> Relevant context prepared by Ghost (reason: {self.package.reason}, "
            f"confidence: {self.package.confidence:.2f}):",
            "",
        ]
        for item in self.package.items:
            lines.append(f"- [{item.kind}/{item.source}] {item.text}")
        if self.package.warnings:
            lines.append("")
            lines.extend(f"- ⚠ {w}" for w in self.package.warnings)
        lines.append("")
        lines.append(f"<!-- ghost provenance: {self.package.provenance} -->")
        return "\n".join(lines)


__all__ = [
    "ContextFabric",
    "ContextItem",
    "ContextPackage",
    "ContextRanker",
    "GhostMemoryRetriever",
    "InMemoryRetriever",
    "InjectionEnvelope",
    "RankedContext",
    "Retriever",
    "estimate_tokens",
]
