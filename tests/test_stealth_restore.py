"""Interventions and counters survive a restart (audit2 poweruser F17)."""

from __future__ import annotations

from pathlib import Path

from ghostchimera.connectors import stealth_service
from ghostchimera.stealth import StealthLoop, new_event
from ghostchimera.stealth.intervention import Intervention, InterventionState
from ghostchimera.stealth.store import StealthStore

_HIGH_VALUE = {"title": "Prod is down", "confidence": 0.95, "relevance": 0.95, "benefit": 0.9}


def _seed(path: Path) -> tuple[str, int]:
    store = StealthStore(path)
    loop = StealthLoop(own_runtime=False, store=store)
    try:
        for i in range(3):
            loop.emit(new_event("incident.opened", source="pager", payload={**_HIGH_VALUE, "i": i}))
        ids = [i for i in loop.interventions]
        assert ids
        return ids[0], 3
    finally:
        loop.close()
        store.close()


def test_restore_from_store_rehydrates_pending_interventions(tmp_path: Path) -> None:
    db = tmp_path / "ghost-stealth.sqlite3"
    intervention_id, events = _seed(db)
    store = StealthStore(db)
    loop = StealthLoop(own_runtime=False, store=store)
    try:
        assert loop.interventions == {}
        restored = loop.restore_from_store()
        assert restored["interventions"] >= 1
        assert intervention_id in loop.interventions
        restored_item = loop.interventions[intervention_id]
        assert isinstance(restored_item, Intervention)
        assert restored_item.state != InterventionState.OUTCOME
        assert loop.events_processed == events
        loop.emit(new_event("file.modified", source="fs", payload={"p": 1}))
        assert loop.events_processed == events + 1
    finally:
        loop.close()
        store.close()


def test_terminal_interventions_are_not_restored(tmp_path: Path) -> None:
    store = StealthStore(tmp_path / "s.sqlite3")
    store.record_intervention(Intervention(id="int-done", state=InterventionState.OUTCOME))
    store.record_intervention(
        Intervention(id="int-ready", state=InterventionState.READY, provenance={"trace": {"x": 1}})
    )
    loop = StealthLoop(own_runtime=False, store=store)
    try:
        loop.restore_from_store()
        assert "int-ready" in loop.interventions and "int-done" not in loop.interventions
        assert loop.interventions["int-ready"].provenance == {"trace": {"x": 1}}
    finally:
        loop.close()
        store.close()


def test_service_loop_restores_on_start(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    intervention_id, _ = _seed(tmp_path / "ghost-stealth.sqlite3")
    monkeypatch.setattr(stealth_service, "_loops", {})
    loop = stealth_service.get_service_loop(tmp_path)
    try:
        assert intervention_id in loop.interventions
    finally:
        loop.close()
        stealth_service._loops.pop(str(tmp_path), None)
