"""Tests for the console background run manager (threading overhaul)."""

from __future__ import annotations

import threading
import time
import unittest

from ghostchimera.control_plane.run_jobs import ConsoleRunManager


class ConsoleRunManagerTests(unittest.TestCase):
    def test_submit_runs_in_background_and_completes(self) -> None:
        manager = ConsoleRunManager(max_concurrent=4)
        started = threading.Event()

        def fn():
            started.set()
            time.sleep(0.2)
            return {"ok": True}

        run = manager.submit("demo", fn)
        self.assertTrue(run.run_id)
        # Returns immediately; the work happens off-thread.
        self.assertIn(run.status, ("queued", "running"))
        self.assertTrue(started.wait(timeout=5))

        deadline = time.time() + 10
        while time.time() < deadline and manager.get(run.run_id).status not in (
            "completed",
            "failed",
            "cancelled",
        ):
            time.sleep(0.05)
        record = manager.get(run.run_id)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.result, {"ok": True})
        self.assertIsNotNone(record.started_at)
        self.assertIsNotNone(record.finished_at)

    def test_failure_is_captured_not_raised(self) -> None:
        manager = ConsoleRunManager()

        def boom():
            raise RuntimeError("kaput")

        run = manager.submit("boom", boom)
        deadline = time.time() + 10
        while time.time() < deadline and manager.get(run.run_id).status not in (
            "completed",
            "failed",
            "cancelled",
        ):
            time.sleep(0.05)
        record = manager.get(run.run_id)
        self.assertEqual(record.status, "failed")
        self.assertIn("kaput", record.error)

    def test_cancel_queued_run_never_starts(self) -> None:
        manager = ConsoleRunManager(max_concurrent=1)
        gate = threading.Event()
        started_second = threading.Event()

        def slow():
            gate.wait(timeout=10)
            return "slow"

        def second():
            started_second.set()
            return "second"

        first = manager.submit("slow", slow)
        # Occupy the single slot.
        deadline = time.time() + 10
        while time.time() < deadline and manager.get(first.run_id).status != "running":
            time.sleep(0.05)
        queued = manager.submit("second", second)
        result = manager.cancel(queued.run_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "cancelled")
        gate.set()
        # Let the first finish.
        deadline = time.time() + 10
        while time.time() < deadline and manager.get(first.run_id).status != "completed":
            time.sleep(0.05)
        time.sleep(0.2)
        self.assertFalse(started_second.is_set())
        self.assertEqual(manager.get(queued.run_id).status, "cancelled")

    def test_cancel_unknown_run(self) -> None:
        manager = ConsoleRunManager()
        result = manager.cancel("nope")
        self.assertFalse(result["ok"])

    def test_history_lists_newest_first(self) -> None:
        manager = ConsoleRunManager()
        first = manager.submit("a", lambda: 1)
        time.sleep(0.05)
        second = manager.submit("b", lambda: 2)
        deadline = time.time() + 10
        while time.time() < deadline and any(
            r["status"] not in ("completed", "failed", "cancelled") for r in manager.list()
        ):
            time.sleep(0.05)
        runs = manager.list()
        ids = [r["run_id"] for r in runs]
        self.assertEqual(ids[0], second.run_id)
        self.assertEqual(ids[1], first.run_id)


if __name__ == "__main__":
    unittest.main()
