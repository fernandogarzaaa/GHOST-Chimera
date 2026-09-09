"""Phase 4 tests: BackgroundRuntime + full StealthLoop (meeting-prep demo)."""

from __future__ import annotations

from ghostchimera.stealth import (
    AutonomyLevel,
    GhostPolicy,
    InterventionOutcome,
    InterventionState,
    StealthLoop,
    new_event,
)
from ghostchimera.stealth.context import ContextFabric, ContextItem, InMemoryRetriever
from ghostchimera.stealth.loop import LoopResult
from ghostchimera.stealth.runtime import BackgroundRuntime
from ghostchimera.stealth.stealth_policy import Decision


def _meeting_fabric() -> ContextFabric:
    return ContextFabric(
        retrievers=[InMemoryRetriever([
            ContextItem(source="memory:episodic", kind="memory",
                        text="Alex emailed the Moovsoon proposal draft", score=0.9, confidence=0.9,
                        provenance={"origin": "email"}),
            ContextItem(source="graph:semantic", kind="fact",
                        text="Moovsoon repository is ghost-main", score=0.85, confidence=0.9,
                        provenance={"origin": "graph"}),
            ContextItem(source="doc:notes", kind="document",
                        text="Previous meeting notes: pricing section open", score=0.8, confidence=0.8,
                        provenance={"origin": "notes"}),
        ])],
        max_tokens=4000,
    )


def test_runtime_executes_with_retry_then_parks() -> None:
    runtime = BackgroundRuntime()
    calls: list[str] = []

    def flaky(job):
        calls.append(job.id)
        if len(calls) < 2:
            raise RuntimeError("transient connector failure")
        return {"ok": True}

    runtime.register("flaky", flaky)
    runtime.start()
    try:
        job = runtime.submit("flaky", {})
        done = runtime.wait_for(job.id, timeout=15.0)
        assert done is not None and done.status == "done"
        assert done.attempts == 2
    finally:
        runtime.stop()

    def always_fail(job):
        raise RuntimeError("github unavailable")

    runtime2 = BackgroundRuntime()
    runtime2.register("x", always_fail)
    runtime2.start()
    try:
        job = runtime2.submit("x", {}, max_attempts=1)
        done = runtime2.wait_for(job.id, timeout=10.0)
        assert done is not None and done.status == "dead"  # parked, runtime alive
        assert runtime2.stats()["total"] == 1
    finally:
        runtime2.stop()


def test_runtime_recovers_queued_jobs_from_disk(tmp_path) -> None:
    qfile = tmp_path / "queue.jsonl"
    runtime = BackgroundRuntime(queue_file=qfile)
    runtime.register("noop", lambda job: {"ok": True})
    job = runtime.submit("noop", {"a": 1})
    runtime.stop()
    # Simulate crash before workers drain: fresh runtime recovers the job.
    runtime2 = BackgroundRuntime(queue_file=qfile)
    runtime2.register("noop", lambda job: {"ok": True})
    runtime2.start()
    try:
        done = runtime2.wait_for(job.id, timeout=10.0)
        assert done is not None and done.status == "done"
    finally:
        runtime2.stop()


def test_loop_silence_by_default_on_weak_signal() -> None:
    loop = StealthLoop(fabric=_meeting_fabric())
    try:
        loop.emit(new_event("file.modified", source="fs", confidence=0.2))
        result = loop.last_result
        assert isinstance(result, LoopResult)
        assert result.decision == Decision.NONE
        assert result.intervention_id == ""
    finally:
        loop.close()


def test_loop_meeting_preparation_end_to_end() -> None:
    policy = GhostPolicy.conservative_default()
    policy.autonomy = AutonomyLevel.INJECT
    loop = StealthLoop(policy=policy, fabric=_meeting_fabric())
    try:
        # Train the workflow: calendar -> email -> session, several times.
        for _ in range(5):
            loop.emit(new_event("calendar.event_starting", source="calendar", actor="alex",
                                payload={"project": "moovsoon", "relevance": 0.9,
                                         "confidence": 0.9, "benefit": 0.9},
                                session_id="s", confidence=0.9))
            loop.emit(new_event("email.received", source="gmail", actor="alex",
                                payload={"project": "moovsoon", "relevance": 0.9,
                                         "confidence": 0.9, "benefit": 0.9},
                                session_id="s", confidence=0.9))
        assert loop.last_result is not None
        # Frequency cap (5/hr) may silence later emits; at least one
        # training event must have produced an intervention.
        assert loop.interventions, "expected ≥1 intervention from training events"
        iid = next(iter(loop.interventions))
        intervention = loop.interventions[iid]
        if intervention.state in (InterventionState.QUEUED, InterventionState.PREPARING):
            for _ in range(100):
                if loop.interventions[iid].state == InterventionState.READY:
                    break
                __import__("time").sleep(0.1)
        assert loop.interventions[iid].state == InterventionState.READY
        markdown = loop.inject(iid, host="claude")
        assert "Moovsoon" in markdown and "prepared by Ghost" in markdown
        assert loop.interventions[iid].state == InterventionState.INJECTED
        # Outcome feeds back into the learning loop.
        loop.observe_outcome(iid, InterventionOutcome.USEFUL)
        assert loop.interventions[iid].state.name == "OUTCOME"
        assert loop.graph.workflow_score(loop.interventions[iid].workflow) > 0.5
    finally:
        loop.close()


def test_loop_replay_is_side_effect_free() -> None:
    loop = StealthLoop(fabric=_meeting_fabric())
    try:
        events = [new_event("email.received", source="gmail", actor="alex",
                            payload={"project": "moovsoon"}, confidence=0.9) for _ in range(3)]
        for e in events:
            loop.emit(e)
        n_interventions = len(loop.interventions)
        delivered = loop.bus.replay(events, read_only=True)
        assert delivered == 3
        assert len(loop.interventions) == n_interventions  # replay created nothing
    finally:
        loop.close()


def test_loop_survives_connector_failure() -> None:
    from ghostchimera.stealth.context import ContextFabric

    class DeadSource:
        name = "dead"

        def retrieve(self, event, context):
            raise ConnectionError("gmail unavailable")

    policy = GhostPolicy.conservative_default()
    loop = StealthLoop(policy=policy, fabric=ContextFabric(retrievers=[DeadSource()]))
    try:
        loop.emit(new_event("email.received", source="gmail", actor="alex",
                            payload={"relevance": 0.95, "confidence": 0.93, "benefit": 0.9},
                            confidence=0.93))
        # Loop must not raise; decision may still prepare with empty context.
        assert loop.last_result is not None
    finally:
        loop.close()
