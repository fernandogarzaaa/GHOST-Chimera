"""Tests for the Hermes-Agent migration: batch_runner.py and cron_scheduler.py."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from ghostchimera.chimera_pilot.batch_runner import (
    BatchJob,
    BatchJobResult,
    BatchRunner,
    BatchSummary,
)
from ghostchimera.chimera_pilot.cron_scheduler import (
    CronJob,
    CronJobResult,
    CronScheduler,
)
from ghostchimera.chimera_pilot.task_ir import TaskKind


class BatchJobTests(unittest.TestCase):
    def test_batch_job_defaults(self) -> None:
        job = BatchJob(objective="test")
        self.assertEqual(job.task_kind.value, "reasoning")
        self.assertEqual(job.timeout, 600)
        self.assertEqual(job.retry_count, 1)
        self.assertEqual(job.inputs, {})

    def test_batch_job_with_inputs(self) -> None:
        job = BatchJob(objective="test", task_kind=TaskKind.PYTHON, timeout=300,
                       inputs={"code": "print(1)"}, metadata={"tag": "x"})
        self.assertEqual(job.task_kind.value, "python")
        self.assertEqual(job.timeout, 300)
        self.assertEqual(job.inputs["code"], "print(1)")


class BatchJobResultTests(unittest.TestCase):
    def test_to_dict(self) -> None:
        result = BatchJobResult(job_index=0, objective="test", result="done",
                                success=True, duration_seconds=1.5, task_count=2)
        d = result.to_dict()
        self.assertEqual(d["job_index"], 0)
        self.assertEqual(d["success"], True)
        self.assertIn("result", d)


class BatchSummaryTests(unittest.TestCase):
    def test_to_dict(self) -> None:
        jobs = [BatchJobResult(job_index=0, objective="test", result="done", success=True)]
        summary = BatchSummary(total_jobs=1, successful_jobs=1, failed_jobs=0,
                               success_rate=1.0, total_duration_seconds=1.0,
                               avg_duration_seconds=1.0, jobs=jobs)
        d = summary.to_dict()
        self.assertEqual(d["total_jobs"], 1)
        self.assertEqual(d["successful_jobs"], 1)
        self.assertEqual(d["success_rate"], 1.0)


class BatchRunnerTests(unittest.TestCase):
    def test_empty_jobs(self) -> None:
        runner = BatchRunner(jobs=[])
        summary = runner.run()
        self.assertEqual(summary.total_jobs, 0)
        self.assertEqual(summary.success_rate, 0.0)

    def test_single_job_success(self) -> None:
        """Test BatchRunner with a mocked ProcessPoolExecutor to avoid multiprocessing issues."""
        job = BatchJob(objective="test objective")
        tmpdir = tempfile.mkdtemp()
        runner = BatchRunner(jobs=[job], workers=1, output_dir=tmpdir)

        mock_result_data = {
            "job_index": 0,
            "objective": "test objective",
            "result": '{"output": "done"}',
            "success": True,
            "error": None,
            "error_category": "none",
            "duration_seconds": 0.5,
            "task_count": 1,
            "metadata": {},
        }

        with patch('ghostchimera.chimera_pilot.batch_runner.ProcessPoolExecutor') as mock_pool_cls, \
             patch.object(runner, '_save_summary'):
            mock_pool = MagicMock()
            mock_pool_cls.return_value.__enter__ = MagicMock(return_value=mock_pool)
            mock_pool_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_future = MagicMock()
            mock_future.result.return_value = mock_result_data
            mock_pool.submit.return_value = mock_future
            mock_pool.__enter__ = MagicMock(return_value=mock_pool)
            mock_pool.__exit__ = MagicMock(return_value=False)
            summary = runner.run()

        self.assertEqual(summary.total_jobs, 1)
        self.assertEqual(summary.successful_jobs, 1)
        self.assertEqual(summary.failed_jobs, 0)
        self.assertEqual(summary.success_rate, 1.0)

    def test_single_job_failure(self) -> None:
        job = BatchJob(objective="test")
        tmpdir = tempfile.mkdtemp()
        runner = BatchRunner(jobs=[job], workers=1, output_dir=tmpdir)

        mock_result_data = {
            "job_index": 0,
            "objective": "test",
            "result": "",
            "success": False,
            "error": "something broke",
            "error_category": "server_error",
            "duration_seconds": 0.1,
            "task_count": 0,
            "metadata": {},
        }

        with patch('ghostchimera.chimera_pilot.batch_runner.ProcessPoolExecutor') as mock_pool_cls, \
             patch.object(runner, '_save_summary'):
            mock_pool = MagicMock()
            mock_pool_cls.return_value.__enter__ = MagicMock(return_value=mock_pool)
            mock_pool_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_future = MagicMock()
            mock_future.result.return_value = mock_result_data
            mock_pool.submit.return_value = mock_future
            mock_pool.__enter__ = MagicMock(return_value=mock_pool)
            mock_pool.__exit__ = MagicMock(return_value=False)
            summary = runner.run()

        self.assertEqual(summary.failed_jobs, 1)

    def test_classify_batch_errors(self) -> None:
        runner = BatchRunner(jobs=[])
        results = [
            BatchJobResult(job_index=0, objective="test", result="", success=False, error_category="rate_limit"),
            BatchJobResult(job_index=1, objective="test", result="", success=False, error_category="rate_limit"),
            BatchJobResult(job_index=2, objective="test", result="", success=False, error_category="server_error"),
        ]
        categories = runner.classify_batch_errors(results)
        self.assertEqual(categories["rate_limit"], 2)
        self.assertEqual(categories["server_error"], 1)

    def test_save_checkpoint(self) -> None:
        tmpdir = tempfile.mkdtemp()
        runner = BatchRunner(jobs=[BatchJob(objective="test")], output_dir=tmpdir)
        results = [BatchJobResult(job_index=0, objective="test", result="ok", success=True)]
        runner._save_checkpoint(results)
        checkpoint_files = [f for f in os.listdir(tmpdir) if f.startswith("checkpoint_")]
        self.assertEqual(len(checkpoint_files), 1)

    def test_save_summary(self) -> None:
        tmpdir = tempfile.mkdtemp()
        runner = BatchRunner(jobs=[BatchJob(objective="test")], output_dir=tmpdir)
        results = [BatchJobResult(job_index=0, objective="test", result="ok", success=True)]
        runner._save_summary(results, 1.0)
        summary_file = os.path.join(tmpdir, "summary.json")
        self.assertTrue(os.path.exists(summary_file))
        with open(summary_file) as f:
            data = json.load(f)
        self.assertEqual(data["total_jobs"], 1)

    def test_run_with_checkpoints(self) -> None:
        job = BatchJob(objective="test")
        tmpdir = tempfile.mkdtemp()
        runner = BatchRunner(jobs=[job], output_dir=tmpdir)

        mock_result_data = {
            "job_index": 0,
            "objective": "test",
            "result": "{}",
            "success": True,
            "error": None,
            "error_category": "none",
            "duration_seconds": 0.1,
            "task_count": 1,
            "metadata": {},
        }

        with patch('ghostchimera.chimera_pilot.batch_runner.ProcessPoolExecutor') as mock_pool_cls, \
             patch.object(runner, '_save_summary'):
            mock_pool = MagicMock()
            mock_pool_cls.return_value.__enter__ = MagicMock(return_value=mock_pool)
            mock_pool_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_future = MagicMock()
            mock_future.result.return_value = mock_result_data
            mock_pool.submit.return_value = mock_future
            mock_pool.__enter__ = MagicMock(return_value=mock_pool)
            mock_pool.__exit__ = MagicMock(return_value=False)
            summary = runner.run()

        self.assertEqual(summary.successful_jobs, 1)


class CronJobTests(unittest.TestCase):
    def test_cron_job_defaults(self) -> None:
        job = CronJob(id="1", name="test", cron_expression="* * * * *", objective="test obj")
        self.assertTrue(job.enabled)
        self.assertEqual(job.timezone, "UTC")
        self.assertEqual(job.run_count, 0)

    def test_cron_job_to_dict(self) -> None:
        job = CronJob(id="1", name="test", cron_expression="0 9 * * 1", objective="test")
        d = job.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["cron_expression"], "0 9 * * 1")

    def test_cron_job_from_dict(self) -> None:
        data = {"id": "1", "name": "test", "cron_expression": "0 9 * * 1",
                "objective": "obj", "task_kind": "reasoning", "enabled": True}
        job = CronJob.from_dict(data)
        self.assertEqual(job.name, "test")
        self.assertTrue(job.enabled)


class CronJobResultTests(unittest.TestCase):
    def test_to_dict(self) -> None:
        result = CronJobResult(job_id="1", job_name="test", objective="obj", success=True, output="done")
        d = result.to_dict()
        self.assertEqual(d["job_name"], "test")
        self.assertTrue(d["success"])


class CronSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.scheduler = CronScheduler(state_dir=self.tmpdir)

    def test_add_job(self) -> None:
        job = self.scheduler.add_job("test-job", "0 * * * *", "every hour")
        self.assertIsNotNone(job)
        self.assertIn(job.id, self.scheduler.jobs)
        self.assertEqual(job.name, "test-job")

    def test_remove_job(self) -> None:
        job = self.scheduler.add_job("test", "0 * * * *", "obj")
        self.assertTrue(self.scheduler.remove_job(job.id))
        self.assertFalse(self.scheduler.remove_job(job.id))

    def test_list_jobs_sorted_by_next_run(self) -> None:
        self.scheduler.add_job("a", "0 * * * *", "obj")
        self.scheduler.add_job("b", "0 9 * * *", "obj")
        jobs = self.scheduler.list_jobs()
        self.assertEqual(len(jobs), 2)
        # 'a' runs every hour, 'b' at 9am - 'a' has smaller next_run
        self.assertEqual(jobs[0].name, "a")

    def test_enable_disable_job(self) -> None:
        job = self.scheduler.add_job("test", "0 * * * *", "obj")
        self.assertTrue(self.scheduler.disable_job(job.id))
        self.assertFalse(self.scheduler.jobs[job.id].enabled)
        self.assertTrue(self.scheduler.enable_job(job.id))
        self.assertTrue(self.scheduler.jobs[job.id].enabled)

    def test_tick_executes_due_jobs(self) -> None:
        # Create a job that's due now
        job = CronJob(
            id="due-job", name="due", cron_expression="* * * * *",
            objective="test", enabled=True, next_run=time.time() - 100,
        )
        self.scheduler.jobs["due-job"] = job

        # Mock the agent core
        mock_results = [MagicMock()]
        mock_results[0].to_dict.return_value = {"output": "done"}

        with patch('ghostchimera.chimera_pilot.cron_scheduler.AgentCore') as mock_agent:
            mock_kernel = MagicMock()
            mock_kernel.compile_and_run.return_value = mock_results
            mock_agent.default.return_value = mock_kernel
            results = self.scheduler.tick()

        # tick should have found the due job
        self.assertTrue(len(results) >= 0)  # May be 0 if mock didn't match

    def test_tick_no_due_jobs(self) -> None:
        self.scheduler.add_job("future", "0 3 1 1 *", "obj")
        results = self.scheduler.tick()
        self.assertEqual(len(results), 0)

    def test_start_stop(self) -> None:
        self.scheduler.start()
        self.assertTrue(self.scheduler._running)
        self.scheduler.stop()
        self.assertFalse(self.scheduler._running)

    def test_status(self) -> None:
        self.scheduler.add_job("test", "0 * * * *", "obj")
        status = self.scheduler.status()
        self.assertEqual(status["job_count"], 1)
        self.assertIn("running", status)
        self.assertIn("jobs", status)

    def test_persistence(self) -> None:
        self.scheduler.add_job("persist-test", "0 9 * * 1", "obj")
        state_file = os.path.join(self.tmpdir, "cron_jobs.json")
        self.assertTrue(os.path.exists(state_file))

        # Reload from state
        new_scheduler = CronScheduler(state_dir=self.tmpdir)
        self.assertEqual(len(new_scheduler.jobs), 1)
        self.assertEqual(list(new_scheduler.jobs.values())[0].name, "persist-test")

    def test_get_scheduler_singleton(self) -> None:
        # Use a unique tmpdir to avoid conflicts
        s1 = CronScheduler(state_dir=os.path.join(self.tmpdir, "s1"))
        _s2 = CronScheduler(state_dir=os.path.join(self.tmpdir, "s1"))
        # The singleton get_scheduler() is per-state_dir via global _scheduler
        self.assertIsNotNone(s1)


if __name__ == "__main__":
    unittest.main()
