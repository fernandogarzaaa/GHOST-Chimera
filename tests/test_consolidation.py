"""Tests for sleep-time memory consolidation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ghostchimera.memory_layer.consolidation import MemoryConsolidator, heat_score
from ghostchimera.memory_layer.store import MemoryStore
from ghostchimera.memory_layer.temporal_graph import TemporalGraphStore


def _pair(tmp_path):
    episodic = MemoryStore(tmp_path / "episodic.sqlite")
    semantic = TemporalGraphStore(tmp_path / "semantic.sqlite")
    return episodic, semantic


def test_heat_score_recent_dense_beats_old_sparse():
    now = datetime(2026, 6, 16, tzinfo=UTC)
    fresh = heat_score(
        created_at=now.isoformat(),
        access_count=10,
        content="the user prefers dark roast coffee brewed with a chemex every morning",
        now=now,
    )
    stale = heat_score(
        created_at=(now - timedelta(days=400)).isoformat(),
        access_count=0,
        content="ok",
        now=now,
    )
    assert fresh > stale
    assert 0.0 <= stale <= fresh <= 1.0


def test_promotes_structured_metadata_triple(tmp_path):
    episodic, semantic = _pair(tmp_path)
    episodic.add_document(
        "conversation",
        "User mentioned their employer during onboarding chat about benefits.",
        {"subject": "user", "predicate": "works_at", "object": "Globex", "access_count": 8},
    )
    consolidator = MemoryConsolidator(episodic, semantic, promotion_threshold=0.3)
    report = consolidator.consolidate()
    assert report.promoted == 1
    facts = semantic.active_facts(subject="user", predicate="works_at")
    assert len(facts) == 1
    assert facts[0].obj == "Globex"
    assert facts[0].provenance["episodic_id"] is not None


def test_low_heat_is_not_promoted(tmp_path):
    episodic, semantic = _pair(tmp_path)
    episodic.add_document(
        "note",
        "x",  # tiny, no access -> low heat
        {"subject": "user", "predicate": "likes", "object": "x"},
    )
    consolidator = MemoryConsolidator(episodic, semantic, promotion_threshold=0.9)
    report = consolidator.consolidate()
    assert report.promoted == 0
    assert report.skipped_low_heat == 1
    assert semantic.count() == 0


def test_unparseable_content_skipped(tmp_path):
    episodic, semantic = _pair(tmp_path)
    episodic.add_document(
        "note",
        "this is a long rambling reflection with no clean triple structure whatsoever indeed",
        {"access_count": 20},
    )
    consolidator = MemoryConsolidator(episodic, semantic, promotion_threshold=0.1)
    report = consolidator.consolidate()
    assert report.promoted == 0
    assert report.skipped_unparseable == 1


def test_expire_stale_facts(tmp_path):
    episodic, semantic = _pair(tmp_path)
    semantic.add_fact(
        "user",
        "lived_in",
        obj="Tokyo",
        valid_to="2010-01-01T00:00:00+00:00",
    )
    consolidator = MemoryConsolidator(episodic, semantic, stale_after_days=365.0)
    expired = consolidator.expire_stale(now=datetime(2026, 6, 16, tzinfo=UTC))
    assert expired == 1
    assert semantic.active_facts(subject="user", predicate="lived_in") == []


def test_consolidation_is_idempotent(tmp_path):
    episodic, semantic = _pair(tmp_path)
    episodic.add_document(
        "chat",
        "employer fact",
        {"subject": "user", "predicate": "works_at", "object": "Globex", "access_count": 9},
    )
    consolidator = MemoryConsolidator(episodic, semantic, promotion_threshold=0.3)

    first = consolidator.consolidate()
    second = consolidator.consolidate()

    assert first.promoted == 1
    assert second.promoted == 0
    assert second.skipped_already_promoted == 1
    # No duplicate facts created on the second pass.
    assert semantic.count(active_only=True) == 1


def test_non_integer_access_count_does_not_abort(tmp_path):
    episodic, semantic = _pair(tmp_path)
    episodic.add_document(
        "chat",
        "fact one",
        {"subject": "user", "predicate": "uses", "object": "Linux", "access_count": "lots"},
    )
    consolidator = MemoryConsolidator(episodic, semantic, promotion_threshold=0.0)
    report = consolidator.consolidate()
    assert report.scanned == 1
    assert report.promoted == 1


def test_run_reports_combined(tmp_path):
    episodic, semantic = _pair(tmp_path)
    episodic.add_document(
        "chat",
        "irrelevant",
        {"subject": "user", "predicate": "uses", "object": "Linux", "access_count": 12},
    )
    semantic.add_fact("user", "lived_in", obj="Osaka", valid_to="2000-01-01T00:00:00+00:00")
    consolidator = MemoryConsolidator(episodic, semantic, promotion_threshold=0.3, stale_after_days=365.0)
    report = consolidator.run(now=datetime(2026, 6, 16, tzinfo=UTC))
    assert report.promoted == 1
    assert report.expired_stale == 1
    assert report.as_dict()["promoted"] == 1
