"""SyncScheduler tests: intervals, isolation, lifecycle (offline)."""

from __future__ import annotations

from unittest.mock import Mock, patch

from ghostchimera.connectors import Connector, GitHubEventConnector, SyncRecord, SyncScheduler


def _github():
    def fetch(path: str):
        if "/commits" in path:
            return [{"sha": "abc123def456", "commit": {"author": {"name": "octocat"}, "message": "fix"}}]
        return []

    return GitHubEventConnector("o/r", fetcher=fetch)


def test_sync_delivers_then_dedups() -> None:
    seen: list = []
    scheduler = SyncScheduler(seen.append, tick_s=60.0)
    scheduler.register(_github(), interval_s=5.0)
    try:
        assert scheduler.run_due_now() == {"github": 1}
        assert scheduler.run_due_now() == {}  # interval not elapsed
        status = scheduler.status()
        assert status["syncs"][0]["runs"] == 1
        assert status["syncs"][0]["last_delivered"] == 1
    finally:
        scheduler.stop()


def test_failing_connector_does_not_stop_schedule() -> None:
    from ghostchimera.connectors import Connector

    class Dead(Connector):
        def poll_once(self):
            raise ConnectionError("down")

    dead = Dead()
    dead.id = "dead"
    seen: list = []
    scheduler = SyncScheduler(seen.append, tick_s=60.0)
    scheduler.register(dead, interval_s=5.0)
    scheduler.register(_github(), interval_s=5.0)
    try:
        results = scheduler.run_due_now()
        assert results == {"dead": 0, "github": 1}  # dead isolated, healthy flows
        assert seen  # github event reached the emitter
        status = scheduler.status()
        dead_record = next(item for item in status["syncs"] if item["connector_id"] == "dead")
        assert dead_record["last_error"] == "ConnectionError: down"
    finally:
        scheduler.stop()


def test_lifecycle_and_unregister() -> None:
    threads: list[Mock] = []

    def make_thread(**kwargs):
        thread = Mock()
        thread.is_alive.return_value = True
        thread.target = kwargs["target"]
        thread.name = kwargs["name"]
        thread.daemon = kwargs["daemon"]
        threads.append(thread)
        return thread

    scheduler = SyncScheduler(lambda e: None, tick_s=0.05)
    scheduler.register(_github(), interval_s=5.0)
    with patch("ghostchimera.connectors.syncs.threading.Thread", side_effect=make_thread):
        scheduler.start()
        scheduler.start()  # idempotent while the worker is alive

        assert len(threads) == 1
        assert threads[0].name == "ghost-syncs"
        assert threads[0].daemon is True
        threads[0].start.assert_called_once_with()
        assert scheduler.status()["running"] is True

        assert scheduler.unregister("github") is True
        assert scheduler.unregister("github") is False
        assert scheduler.status()["syncs"] == []

        scheduler.stop(timeout=0.25)
        threads[0].join.assert_called_once_with(timeout=0.25)
        # The mocked worker never exits, so the timed stop retains the thread
        # and a restart cannot overlap the live worker.
        assert scheduler.status()["running"] is True
        scheduler.start()
        assert len(threads) == 1

        # Once the worker has exited, stop clears the thread and restart works.
        threads[0].is_alive.return_value = False
        scheduler.stop()
        assert scheduler.status()["running"] is False
        scheduler.start()
        assert len(threads) == 2
        threads[1].start.assert_called_once_with()
        threads[1].is_alive.return_value = False
        scheduler.stop()


def test_effective_interval_stored_and_updated_on_reregister() -> None:
    scheduler = SyncScheduler(lambda e: None, tick_s=60.0)
    try:
        connector = _github()
        scheduler.register(connector, interval_s=1.0)
        status = scheduler.status()
        assert status["syncs"][0]["interval_s"] == 5.0
        scheduler.register(connector, interval_s=60.0)
        status = scheduler.status()
        assert len(status["syncs"]) == 1
        assert status["syncs"][0]["interval_s"] == 60.0
    finally:
        scheduler.stop()


def test_concurrent_unregister_during_run_is_safe() -> None:
    import threading

    from ghostchimera.connectors import Connector

    entered = threading.Event()
    release = threading.Event()

    class Slow(Connector):
        def poll_once(self):
            entered.set()
            release.wait(5.0)
            return []

    slow = Slow()
    slow.id = "slow"
    scheduler = SyncScheduler(lambda e: None, tick_s=60.0)
    scheduler.register(slow, interval_s=5.0)
    errors: list = []

    def run() -> None:
        try:
            scheduler.run_due_now()
        except Exception as exc:  # noqa: BLE001 - the test must surface any leak
            errors.append(exc)

    worker = threading.Thread(target=run)
    try:
        worker.start()
        assert entered.wait(5.0)
        assert scheduler.unregister("slow") is True
        results = scheduler.run_due_now()
        assert results == {}
    finally:
        release.set()
        worker.join(5.0)
        scheduler.stop()
    assert not worker.is_alive()
    assert errors == []
    assert scheduler.status()["syncs"] == []


def test_start_stop_restart_runs_single_worker() -> None:
    import threading

    from ghostchimera.connectors import Connector

    state = {"active": 0, "max_active": 0}
    entered = threading.Event()
    release = threading.Event()

    class Blocking(Connector):
        def poll_once(self):
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            entered.set()
            try:
                release.wait(5.0)
            finally:
                state["active"] -= 1
            return []

    connector = Blocking()
    connector.id = "blocking"
    scheduler = SyncScheduler(lambda e: None, tick_s=0.02)
    scheduler.register(connector, interval_s=5.0)
    try:
        scheduler.start()
        assert entered.wait(5.0)
        first_thread = scheduler._thread
        starters = [threading.Thread(target=scheduler.start) for _ in range(4)]
        for starter in starters:
            starter.start()
        for starter in starters:
            starter.join(5.0)
        assert scheduler._thread is first_thread
        scheduler.stop(timeout=0.05)
        assert scheduler._thread is first_thread
        scheduler.start()
        assert scheduler._thread is first_thread
        release.set()
    finally:
        scheduler.stop()
        release.set()
    assert state["max_active"] == 1
    assert scheduler.status()["running"] is False
    scheduler.start()
    try:
        assert scheduler.status()["running"] is True
        assert scheduler._thread is not first_thread
    finally:
        scheduler.stop()


def test_loop_integration() -> None:
    from ghostchimera.stealth import StealthLoop

    loop = StealthLoop()
    try:
        scheduler = SyncScheduler(loop.emit, tick_s=60.0)
        scheduler.register(_github(), interval_s=5.0)
        try:
            assert scheduler.run_due_now() == {"github": 1}
            assert loop.bus.processed == 1
        finally:
            scheduler.stop()
    finally:
        loop.close()


def _polling_connector(connector_id: str, delivered: int = 1) -> Mock:
    connector = Mock(spec=Connector)
    connector.id = connector_id
    connector.poll.return_value = delivered
    return connector


def test_interval_boundaries_and_minimum_interval_are_deterministic() -> None:
    fast = _polling_connector("fast", delivered=2)
    slow = _polling_connector("slow", delivered=3)
    scheduler = SyncScheduler(Mock(), tick_s=60.0)
    scheduler.register(fast, interval_s=1.0)  # clamped to the five-second minimum
    scheduler.register(slow, interval_s=10.0)

    with patch("ghostchimera.connectors.syncs.time.time") as clock:
        clock.return_value = 100.0
        assert scheduler.run_due_now() == {"fast": 2, "slow": 3}

        clock.return_value = 104.999
        assert scheduler.run_due_now() == {}

        clock.return_value = 105.0
        assert scheduler.run_due_now() == {"fast": 2}

        clock.return_value = 110.0
        assert scheduler.run_due_now() == {"fast": 2, "slow": 3}

    assert fast.poll.call_count == 3
    assert slow.poll.call_count == 2


def test_poll_failure_is_recorded_per_connector_and_cleared_after_recovery() -> None:
    emit = Mock()
    failing = _polling_connector("failing")
    failing.poll.side_effect = RuntimeError("source unavailable")
    healthy = _polling_connector("healthy", delivered=4)
    scheduler = SyncScheduler(emit)
    scheduler.register(failing, interval_s=5.0)
    scheduler.register(healthy, interval_s=5.0)

    with patch("ghostchimera.connectors.syncs.time.time") as clock:
        clock.return_value = 100.0
        assert scheduler.run_due_now() == {"failing": 0, "healthy": 4}

        status_by_id = {entry["connector_id"]: entry for entry in scheduler.status()["syncs"]}
        assert status_by_id["failing"] == {
            "connector_id": "failing",
            "interval_s": 5.0,
            "runs": 1,
            "last_delivered": 0,
            "last_error": "RuntimeError: source unavailable",
            "last_run_at": 100.0,
        }
        assert status_by_id["healthy"]["last_error"] == ""
        assert status_by_id["healthy"]["last_delivered"] == 4

        failing.poll.side_effect = None
        failing.poll.return_value = 2
        clock.return_value = 105.0
        assert scheduler.run_due_now() == {"failing": 2, "healthy": 4}

    recovered = {entry["connector_id"]: entry for entry in scheduler.status()["syncs"]}["failing"]
    assert recovered["runs"] == 2
    assert recovered["last_delivered"] == 2
    assert recovered["last_error"] == ""


def test_registering_same_id_replaces_connector_without_duplicate_status() -> None:
    original = _polling_connector("source", delivered=1)
    replacement = _polling_connector("source", delivered=7)
    scheduler = SyncScheduler(Mock())

    with patch("ghostchimera.connectors.syncs.time.time") as clock:
        scheduler.register(original, interval_s=5.0)
        clock.return_value = 100.0
        assert scheduler.run_due_now() == {"source": 1}

        scheduler.register(replacement, interval_s=5.0)
        clock.return_value = 105.0
        assert scheduler.run_due_now() == {"source": 7}

    original.poll.assert_called_once()
    replacement.poll.assert_called_once()
    assert scheduler.status()["syncs"] == [
        {
            "connector_id": "source",
            "interval_s": 5.0,
            "runs": 2,
            "last_delivered": 7,
            "last_error": "",
            "last_run_at": 105.0,
        }
    ]


def test_empty_scheduler_and_status_snapshots_are_safe_to_mutate() -> None:
    scheduler = SyncScheduler(Mock())
    assert scheduler.run_due_now() == {}
    assert scheduler.status() == {"running": False, "syncs": []}

    scheduler.register(_polling_connector("source"), interval_s=30.0)
    first_status = scheduler.status()
    first_status["syncs"][0]["runs"] = 99

    assert scheduler.status()["syncs"][0] == {
        "connector_id": "source",
        "interval_s": 30.0,
        "runs": 0,
        "last_delivered": 0,
        "last_error": "",
        "last_run_at": 0.0,
    }


def test_sync_types_are_exported_from_connectors_package() -> None:
    record = SyncRecord("source", 15.0)
    assert record.connector_id == "source"
    assert record.interval_s == 15.0
    assert record.runs == 0
