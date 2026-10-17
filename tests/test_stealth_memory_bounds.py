"""Event bus history and per-session state are bounded (audit2 poweruser F3)."""

from __future__ import annotations

from ghostchimera.stealth import StealthLoop, new_event
from ghostchimera.stealth.event_bus import EventBus


def test_bus_log_and_seen_ids_are_bounded() -> None:
    bus = EventBus(log_max=50, seen_ids_max=120)
    for i in range(500):
        assert bus.emit(new_event("file.modified", source="t", payload={"i": i}))
    assert len(bus.event_log()) == 50
    assert len(bus._seen_ids) == 120
    assert bus.processed == 500
    assert bus.event_log()[-1].payload["i"] == 499


def test_bus_still_drops_recent_duplicates() -> None:
    bus = EventBus(log_max=10, seen_ids_max=100)
    event = new_event("x.y", source="t")
    assert bus.emit(event) is True
    assert bus.emit(event) is False
    assert bus.dropped_duplicates == 1


def test_bus_log_cap_from_env(monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_BUS_LOG_MAX", "7")
    bus = EventBus()
    for i in range(20):
        bus.emit(new_event("x.y", source="t", payload={"i": i}))
    assert len(bus.event_log()) == 7


def test_per_session_state_is_evicted(monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_STEALTH_MAX_SESSIONS", "20")
    loop = StealthLoop(own_runtime=False)
    try:
        for i in range(200):
            loop.emit(new_event("file.modified", source="t", session_id=f"session-{i}", payload={"i": i}))
        assert len(loop._recent) == 20
        assert "session-199" in loop._recent and "session-0" not in loop._recent
        assert len(loop.learner._sequences) <= 21
    finally:
        loop.close()
