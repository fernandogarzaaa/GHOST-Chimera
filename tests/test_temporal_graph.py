"""Tests for the bi-temporal knowledge-graph memory store."""

from __future__ import annotations

from ghostchimera.memory_layer.temporal_graph import TemporalGraphStore


def _store(tmp_path) -> TemporalGraphStore:
    return TemporalGraphStore(tmp_path / "tg.sqlite")


def test_add_and_query_active_fact(tmp_path):
    store = _store(tmp_path)
    fid = store.add_fact("user", "works_at", obj="Acme", confidence=0.9)
    assert fid > 0
    facts = store.active_facts(subject="user", predicate="works_at")
    assert len(facts) == 1
    assert facts[0].obj == "Acme"
    assert facts[0].confidence == 0.9
    assert store.count(active_only=True) == 1


def test_exclusive_belief_revision_expires_prior(tmp_path):
    store = _store(tmp_path)
    store.add_fact("user", "works_at", obj="Acme", exclusive=True, recorded_at="2026-01-01T00:00:00+00:00")
    store.add_fact("user", "works_at", obj="Globex", exclusive=True, recorded_at="2026-06-01T00:00:00+00:00")

    active = store.active_facts(subject="user", predicate="works_at")
    assert len(active) == 1
    assert active[0].obj == "Globex"

    # History retains both edges.
    hist = store.history(subject="user", predicate="works_at")
    assert [f.obj for f in hist] == ["Acme", "Globex"]
    assert hist[0].expired_at is not None
    assert hist[1].expired_at is None


def test_system_time_travel_sees_prior_belief(tmp_path):
    store = _store(tmp_path)
    store.add_fact("user", "works_at", obj="Acme", exclusive=True, recorded_at="2026-01-01T00:00:00+00:00")
    store.add_fact("user", "works_at", obj="Globex", exclusive=True, recorded_at="2026-06-01T00:00:00+00:00")

    # As the system knew it on 2026-03-01, only "Acme" had been recorded.
    past = store.active_facts(
        subject="user", predicate="works_at", system_time="2026-03-01T00:00:00+00:00"
    )
    assert len(past) == 1
    assert past[0].obj == "Acme"


def test_valid_time_window_filtering(tmp_path):
    store = _store(tmp_path)
    store.add_fact(
        "user",
        "lived_in",
        obj="Tokyo",
        valid_from="2020-01-01T00:00:00+00:00",
        valid_to="2022-12-31T00:00:00+00:00",
    )
    in_window = store.active_facts(subject="user", predicate="lived_in", as_of="2021-06-01T00:00:00+00:00")
    assert len(in_window) == 1
    out_window = store.active_facts(subject="user", predicate="lived_in", as_of="2026-06-01T00:00:00+00:00")
    assert out_window == []


def test_invalidate_fact(tmp_path):
    store = _store(tmp_path)
    fid = store.add_fact("user", "owns", obj="car")
    assert store.active_facts(subject="user") != []
    assert store.invalidate_fact(fid) is True
    assert store.active_facts(subject="user") == []
    # Idempotent: re-invalidating an already-expired fact returns False.
    assert store.invalidate_fact(fid) is False


def test_multi_hop_neighbors(tmp_path):
    store = _store(tmp_path)
    store.add_fact("user", "works_at", obj="Acme")
    store.add_fact("Acme", "located_in", obj="Springfield")
    store.add_fact("Springfield", "in_country", obj="USA")

    one_hop = store.neighbors("user", max_hops=1)
    assert {f.obj for f in one_hop} == {"Acme"}

    two_hop = {f.obj for f in store.neighbors("user", max_hops=2)}
    assert two_hop == {"Acme", "Springfield"}

    three_hop = {f.obj for f in store.neighbors("user", max_hops=3)}
    assert three_hop == {"Acme", "Springfield", "USA"}


def test_min_confidence_filter(tmp_path):
    store = _store(tmp_path)
    store.add_fact("user", "likes", obj="coffee", confidence=0.4)
    store.add_fact("user", "likes", obj="tea", confidence=0.95)
    high = store.active_facts(subject="user", predicate="likes", min_confidence=0.7)
    assert {f.obj for f in high} == {"tea"}


def test_value_facts_and_validation(tmp_path):
    store = _store(tmp_path)
    fid = store.add_fact("user", "timezone", value="Asia/Manila")
    assert fid > 0
    facts = store.active_facts(subject="user", predicate="timezone")
    assert facts[0].value == "Asia/Manila"

    import pytest

    with pytest.raises(ValueError):
        store.add_fact("user", "timezone")  # neither object nor value
    with pytest.raises(ValueError):
        store.add_fact("", "predicate", value="x")
