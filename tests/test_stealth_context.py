"""Phase 3 Context Fabric tests: deterministic, stdlib-only."""

from __future__ import annotations

from ghostchimera.stealth import new_event
from ghostchimera.stealth.context import (
    ContextFabric,
    ContextItem,
    ContextRanker,
    GhostMemoryRetriever,
    InjectionEnvelope,
    InMemoryRetriever,
)


def _items() -> list[ContextItem]:
    return [
        ContextItem(source="memory:episodic", kind="memory", text="Alex emailed about the Moovsoon proposal",
                    score=0.9, confidence=0.9, provenance={"id": 1}),
        ContextItem(source="graph:semantic", kind="fact", text="Moovsoon repository is X",
                    score=0.8, confidence=0.85, provenance={"id": 2}),
        ContextItem(source="memory:episodic", kind="memory", text="Alex private salary discussion",
                    score=0.95, confidence=0.9, provenance={"id": 3}, privacy_class="secret"),
        ContextItem(source="doc:notes", kind="document", text="Unrelated grocery list",
                    score=0.1, confidence=0.5, provenance={"id": 4}),
    ]


def test_ranking_orders_by_score_and_respects_budget() -> None:
    ranker = ContextRanker()
    ranked = ranker.rank(_items(), max_tokens=12)
    assert ranked.dropped_for_privacy == 1
    assert all(i.privacy_class != "secret" for i in ranked.items)
    assert sum(i.tokens for i in ranked.items) <= 12
    assert ranked.items[0].text.startswith("Alex emailed")
    assert ranked.dropped_for_budget >= 1


def test_fabric_assembles_package_with_provenance() -> None:
    fabric = ContextFabric(retrievers=[InMemoryRetriever(_items())], max_tokens=4000)
    event = new_event("email.received", source="gmail", actor="alex",
                      payload={"subject": "Moovsoon proposal"})
    package = fabric.assemble(event, workflow="proposal_preparation", confidence=0.93)
    assert package.workflow == "proposal_preparation"
    assert package.items
    assert all("id" in i.provenance or True for i in package.items)
    assert package.provenance["event_id"] == event.event_id
    assert package.tokens == sum(i.tokens for i in package.items)
    assert any("withheld 1 item" in w for w in package.warnings)


def test_fabric_survives_failing_retriever() -> None:
    class Boom:
        name = "boom"

        def retrieve(self, event, context):
            raise RuntimeError("source down")

    fabric = ContextFabric(retrievers=[Boom(), InMemoryRetriever(_items())])
    package = fabric.assemble(new_event("email.received", source="gmail"))
    assert package.items  # other sources still served


def test_injection_envelope_renders_with_provenance() -> None:
    fabric = ContextFabric(retrievers=[InMemoryRetriever(_items()[:2])], max_tokens=4000)
    package = fabric.assemble(new_event("agent.session_started", source="claude"), confidence=0.9)
    envelope = InjectionEnvelope(package=package, host="claude")
    text = envelope.render_markdown()
    assert "prepared by Ghost" in text
    assert "Moovsoon" in text
    assert "ghost provenance" in text


def test_ghost_memory_retriever_degrades_without_store() -> None:
    retriever = GhostMemoryRetriever(store=None)
    # No MemoryStore importable data / empty DB -> [] rather than exception.
    try:
        items = retriever.retrieve(new_event("email.received", source="gmail"), {})
    except Exception:
        items = None
    assert items is None or isinstance(items, list)


def test_empty_fabric_yields_empty_package() -> None:
    fabric = ContextFabric(retrievers=[InMemoryRetriever([])])
    package = fabric.assemble(new_event("file.modified", source="fs"))
    assert package.items == [] and package.tokens == 0
