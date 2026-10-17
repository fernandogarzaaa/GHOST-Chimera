"""emit() must not block on Nemotron (audit2 poweruser F1).

UNDERSTAND/PREDICT run on a bounded cloud worker; results are attached to the
event's trace and intervention when they land, identical events share one
call, and a per-minute budget caps spend.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from ghostchimera.stealth import StealthLoop, new_event
from ghostchimera.stealth.cloud_worker import CloudEnricher
from ghostchimera.stealth.store import StealthStore


class SlowReasoner:
    available = True

    def __init__(self, delay: float = 0.5) -> None:
        self.delay = delay
        self.calls = 0
        self._lock = threading.Lock()

    def understand(self, event, hypothesis=None, predictions=None):
        with self._lock:
            self.calls += 1
        time.sleep(self.delay)
        return {"intent": f"saw:{event.event_type}", "confidence": 0.8}

    def predict_next(self, history_summary, hypothesis=""):
        return None


_HIGH_VALUE = {"title": "Prod is down", "confidence": 0.95, "relevance": 0.95, "benefit": 0.9}


def test_emit_returns_before_the_cloud_call_finishes() -> None:
    reasoner = SlowReasoner(delay=0.6)
    loop = StealthLoop(reasoner=reasoner, own_runtime=False, cloud_mode="async")
    try:
        started = time.perf_counter()
        loop.emit(new_event("github.issue_created", source="github", payload={"title": "crash"}))
        elapsed = time.perf_counter() - started
        assert elapsed < 0.4, f"emit blocked for {elapsed:.2f}s"
        result = loop.last_result
        assert "nemotron" not in result.trace
        assert loop.wait_for_cloud(5.0)
        # The insight is attached to the same event's trace once it lands.
        assert result.trace["nemotron"]["intent"] == "saw:github.issue_created"
    finally:
        loop.close()


def test_insight_reaches_intervention_and_store(tmp_path: Path) -> None:
    store = StealthStore(tmp_path / "s.sqlite3")
    loop = StealthLoop(reasoner=SlowReasoner(delay=0.2), own_runtime=False, cloud_mode="async", store=store)
    try:
        loop.emit(new_event("incident.opened", source="pager", payload=_HIGH_VALUE))
        intervention_id = loop.last_result.intervention_id
        assert intervention_id, loop.last_result.decision
        assert loop.wait_for_cloud(5.0)
        intervention = loop.interventions[intervention_id]
        assert intervention.provenance["trace"]["nemotron"]["intent"] == "saw:incident.opened"
        row = (
            sqlite3.connect(tmp_path / "s.sqlite3")
            .execute("SELECT provenance FROM interventions WHERE id=?", (intervention_id,))
            .fetchone()
        )
        assert json.loads(row[0])["trace"]["nemotron"]["intent"] == "saw:incident.opened"
    finally:
        loop.close()


def test_identical_events_share_one_call() -> None:
    reasoner = SlowReasoner(delay=0.3)
    loop = StealthLoop(reasoner=reasoner, own_runtime=False, cloud_mode="async")
    try:
        results = []
        for _ in range(5):
            loop.emit(new_event("file.modified", source="fs", payload={"path": "a.py"}))
            results.append(loop.last_result)
        assert loop.wait_for_cloud(5.0)
        assert reasoner.calls == 1
        # Every duplicate still gets the shared insight attached.
        assert all(r.trace.get("nemotron", {}).get("intent") == "saw:file.modified" for r in results)
        # A later identical event is served from cache, inline.
        loop.emit(new_event("file.modified", source="fs", payload={"path": "a.py"}))
        assert loop.last_result.trace["nemotron"]["intent"] == "saw:file.modified"
        assert reasoner.calls == 1
    finally:
        loop.close()


def test_per_minute_budget_caps_calls(monkeypatch) -> None:
    # The budget covers every cloud call: event 0 spends one UNDERSTAND and
    # one (gated, once per stream) PREDICT, event 1 the last UNDERSTAND.
    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_CALLS_PER_MIN", "3")
    reasoner = SlowReasoner(delay=0.0)
    loop = StealthLoop(reasoner=reasoner, own_runtime=False, cloud_mode="async")
    try:
        for i in range(4):
            loop.emit(new_event("file.modified", source="fs", payload={"path": f"f{i}.py"}))
        assert loop.wait_for_cloud(5.0)
        assert reasoner.calls == 2
        assert loop.cloud.snapshot()["budget"] == 2
    finally:
        loop.close()


def test_sync_mode_is_inline_and_deterministic() -> None:
    reasoner = SlowReasoner(delay=0.0)
    loop = StealthLoop(reasoner=reasoner, own_runtime=False, cloud_mode="sync")
    try:
        loop.emit(new_event("github.issue_created", source="github", payload={"title": "x"}))
        assert loop.last_result.trace["nemotron"]["intent"] == "saw:github.issue_created"
    finally:
        loop.close()


def test_enricher_queue_cap_drops_excess() -> None:
    gate = threading.Event()
    enricher = CloudEnricher(mode="async", workers=1, max_pending=2, calls_per_minute=0)
    try:
        statuses = [enricher.request(i, gate.wait, lambda _v: None) for i in range(4)]
        assert statuses == ["submitted", "submitted", "queue_full", "queue_full"]
    finally:
        gate.set()
        assert enricher.wait_idle(5.0)
        enricher.close()


def test_enricher_does_not_cache_failures() -> None:
    enricher = CloudEnricher(mode="sync", calls_per_minute=0)
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("HTTP Error 503")

    assert enricher.request("k", boom, lambda _v: None) == "error"
    assert enricher.request("k", boom, lambda _v: None) == "error"
    assert len(calls) == 2


def test_enricher_cache_expires() -> None:
    now = [0.0]
    enricher = CloudEnricher(mode="sync", calls_per_minute=0, cache_ttl_s=10, clock=lambda: now[0])
    seen = []
    assert enricher.request("k", lambda: "v1", seen.append) == "done"
    assert enricher.request("k", lambda: "v2", seen.append) == "cached"
    now[0] = 11.0
    assert enricher.request("k", lambda: "v3", seen.append) == "done"
    assert seen == ["v1", "v1", "v3"]
