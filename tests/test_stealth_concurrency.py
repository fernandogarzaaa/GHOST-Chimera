"""StealthLoop is safe to share across threads (audit2 poweruser F16)."""

from __future__ import annotations

import logging
import threading

from ghostchimera.stealth import StealthLoop, new_event
from ghostchimera.stealth.workflow_learner import WorkflowLearner


def test_concurrent_emits_drop_nothing(caplog) -> None:
    loop = StealthLoop(own_runtime=False)
    processed: list[str] = []
    lock = threading.Lock()
    original = loop._process_event

    def counting(event):
        original(event)
        with lock:
            processed.append(event.event_id)

    loop._process_event = counting  # type: ignore[method-assign]
    types = ["file.modified", "agent.tool_called", "agent.response_completed", "github.issue_created"]

    def worker(n: int) -> None:
        for i in range(150):
            loop.emit(new_event(types[i % 4], source="t", session_id=f"s{n % 3}", payload={"i": i, "n": n}))

    try:
        with caplog.at_level(logging.WARNING):
            threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        assert "changed size during iteration" not in caplog.text
        assert "EventBus consumer" not in caplog.text
        assert len(processed) == 8 * 150
    finally:
        loop.close()


def test_last_result_is_per_thread_and_emit_and_get_matches_event() -> None:
    loop = StealthLoop(own_runtime=False)
    mismatches: list[tuple[str, str]] = []

    def worker(n: int) -> None:
        for i in range(60):
            event = new_event("file.modified", source="t", session_id=f"s{n}", payload={"i": i, "n": n})
            result = loop.emit_and_get(event)
            if result is None or result.event_id != event.event_id:
                mismatches.append(("emit_and_get", event.event_id))
            event2 = new_event("agent.tool_called", source="t", session_id=f"s{n}", payload={"i": i, "n": n})
            loop.emit(event2)
            if loop.last_result is None or loop.last_result.event_id != event2.event_id:
                mismatches.append(("last_result", event2.event_id))

    try:
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert mismatches == []
        assert loop.result_for("missing") is None
    finally:
        loop.close()


def test_workflow_learner_hypotheses_tolerates_concurrent_observe() -> None:
    learner = WorkflowLearner()
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        i = 0
        while not stop.is_set():
            learner.observe(f"s{i % 50}", f"type.{i % 97}")
            i += 1

    def reader() -> None:
        try:
            for _ in range(300):
                learner.hypotheses()
        except BaseException as exc:  # pragma: no cover - the regression
            errors.append(exc)

    w = threading.Thread(target=writer)
    w.start()
    try:
        reader()
    finally:
        stop.set()
        w.join()
    assert errors == []
