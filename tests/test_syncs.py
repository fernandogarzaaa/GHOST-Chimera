"""SyncScheduler tests: intervals, isolation, lifecycle (offline)."""

from __future__ import annotations

import time

from ghostchimera.connectors import GitHubEventConnector, SyncScheduler


def _github():
    def fetch(path: str):
        if "/commits" in path:
            return [{"sha": "abc123def456", "commit": {"author": {"name": "octocat"},
                     "message": "fix"}}]
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
    finally:
        scheduler.stop()


def test_lifecycle_and_unregister() -> None:
    scheduler = SyncScheduler(lambda e: None, tick_s=0.05)
    scheduler.register(_github(), interval_s=5.0)
    try:
        scheduler.start()
        scheduler.start()  # idempotent
        time.sleep(0.2)
        assert scheduler.status()["running"] is True
        assert scheduler.unregister("github") is True
        assert scheduler.unregister("github") is False
        assert scheduler.status()["syncs"] == []
    finally:
        scheduler.stop()
    assert scheduler.status()["running"] is False


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
