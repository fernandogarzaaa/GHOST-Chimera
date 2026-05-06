"""Tests for durable console-facing autonomy job queue."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.autonomy_jobs import AutonomyJobResult
from ghostchimera.chimera_pilot.autonomy_queue import AutonomyJobQueue


class AutonomyJobQueueTests(unittest.TestCase):
    def test_enqueue_runs_preview_job_and_persists_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-queue-") as tmp:
            queue = AutonomyJobQueue(state_dir=tmp)

            record = queue.enqueue("repair-preview", profile="supervised", execute=False)

            self.assertEqual(record["name"], "repair-preview")
            self.assertEqual(record["status"], "preview")
            self.assertFalse(record["execute"])
            self.assertIn("result", record)
            self.assertTrue((Path(tmp) / "autonomy" / "jobs.json").exists())

            reloaded = AutonomyJobQueue(state_dir=tmp)
            history = reloaded.list_jobs()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["id"], record["id"])
            self.assertEqual(history[0]["status"], "preview")

    def test_execute_high_impact_job_is_rejected_for_supervised_profile(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-queue-") as tmp:
            queue = AutonomyJobQueue(state_dir=tmp)

            with self.assertRaises(PermissionError):
                queue.enqueue("test-regression", profile="supervised", execute=True)

            self.assertEqual(queue.list_jobs(), [])

    def test_cancel_queued_job(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-queue-") as tmp:
            queue = AutonomyJobQueue(state_dir=tmp)

            record = queue.enqueue("self-audit", profile="autonomous", execute=False, run_now=False)
            cancelled = queue.cancel(record["id"])

            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(queue.get(record["id"])["status"], "cancelled")

    def test_failed_runner_is_recorded_as_error(self) -> None:
        class FailingRunner:
            @staticmethod
            def list_jobs():
                return []

            def run(self, job_name: str, *, execute: bool = False) -> AutonomyJobResult:
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory(prefix="ghostchimera-queue-") as tmp:
            queue = AutonomyJobQueue(
                state_dir=tmp,
                runner_factory=lambda **kwargs: FailingRunner(),
            )

            record = queue.enqueue("self-audit", profile="autonomous")

            self.assertEqual(record["status"], "error")
            self.assertEqual(record["error"], "boom")


if __name__ == "__main__":
    unittest.main()
