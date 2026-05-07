"""Unit tests for cron scheduler."""

import tempfile
import time
import unittest

from ghostchimera.chimera_pilot.cron_scheduler import CronJob, CronJobResult, CronScheduler


class CronJobTests(unittest.TestCase):
    def test_creation_defaults(self):
        job = CronJob(id="test-1", name="test", cron_expression="*/5 * * * *", objective="do stuff")
        self.assertTrue(job.enabled)
        self.assertEqual(job.timezone, "UTC")
        self.assertEqual(job.run_count, 0)

    def test_update_next_run(self):
        job = CronJob(id="test-1", name="test", cron_expression="0 0 * * *", objective="midnight")
        job.update_next_run()
        self.assertGreater(job.next_run, time.time())

    def test_to_dict_round_trip(self):
        job = CronJob(id="test-1", name="test", cron_expression="*/5 * * * *", objective="run")
        d = job.to_dict()
        self.assertEqual(d["id"], "test-1")
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["task_kind"], "reasoning")
        self.assertEqual(d["enabled"], True)
        job2 = CronJob.from_dict(d)
        self.assertEqual(job2.id, job.id)
        self.assertEqual(job2.name, job.name)
        self.assertEqual(job2.cron_expression, job.cron_expression)
        self.assertEqual(job2.objective, job.objective)
        self.assertEqual(job2.enabled, job.enabled)

    def test_from_dict_falls_back_defaults(self):
        d = {"id": "x", "name": "x", "cron_expression": "0 * * * *", "objective": "x"}
        job = CronJob.from_dict(d)
        self.assertTrue(job.enabled)
        self.assertEqual(job.timezone, "UTC")


class CronSchedulerTests(unittest.TestCase):
    def setUp(self):
        """
        Create a temporary state directory and instantiate a CronScheduler configured for tests.
        
        Initializes a TemporaryDirectory assigned to self.tmp and constructs self.scheduler as a CronScheduler using that directory as its state_dir with poll_interval set to 1.
        """
        self.tmp = tempfile.TemporaryDirectory(prefix="ghostchimera-cron-test-")
        self.scheduler = CronScheduler(state_dir=self.tmp.name, poll_interval=1)

    def tearDown(self):
        self.scheduler.stop()
        self.tmp.cleanup()

    def test_add_job(self):
        job = self.scheduler.add_job("test", "*/1 * * * *", "run")
        self.assertIsNotNone(job.id)
        self.assertEqual(job.name, "test")
        self.assertEqual(job.objective, "run")
        self.assertTrue(job.enabled)
        self.assertGreater(job.next_run, 0)

    def test_add_job_disabled(self):
        job = self.scheduler.add_job("test", "*/1 * * * *", "run", enabled=False)
        self.assertFalse(job.enabled)

    def test_list_jobs(self):
        self.scheduler.add_job("a", "*/1 * * * *", "run a")
        self.scheduler.add_job("b", "0 * * * *", "run b")
        jobs = self.scheduler.list_jobs()
        self.assertEqual(len(jobs), 2)
        # Should be sorted by next_run
        self.assertLessEqual(jobs[0].next_run, jobs[1].next_run)

    def test_remove_job(self):
        job = self.scheduler.add_job("test", "*/1 * * * *", "run")
        self.assertTrue(self.scheduler.remove_job(job.id))
        self.assertEqual(len(self.scheduler.list_jobs()), 0)

    def test_remove_nonexistent_job(self):
        self.assertFalse(self.scheduler.remove_job("nonexistent"))

    def test_enable_job(self):
        job = self.scheduler.add_job("test", "*/1 * * * *", "run", enabled=False)
        self.assertTrue(self.scheduler.enable_job(job.id))
        self.assertTrue(job.enabled)

    def test_disable_job(self):
        job = self.scheduler.add_job("test", "*/1 * * * *", "run")
        self.assertTrue(self.scheduler.disable_job(job.id))
        self.assertFalse(job.enabled)

    def test_tick_no_due_jobs(self):
        # Jobs added with far-future next_run won't be due
        self.scheduler.add_job("tomorrow", "0 0 1 1 *", "never")
        results = self.scheduler.tick()
        self.assertEqual(len(results), 0)

    def test_status(self):
        self.scheduler.add_job("test", "*/1 * * * *", "run")
        status = self.scheduler.status()
        self.assertFalse(status["running"])
        self.assertEqual(status["job_count"], 1)

    def test_probe_health(self):
        self.scheduler.add_job("test", "*/1 * * * *", "run")
        self.scheduler.start()
        health = self.scheduler.probe()
        self.assertTrue(health.ok)
        self.assertEqual(health.state, "running")
        self.scheduler.stop()

    def test_poll_interval_stored(self):
        sched = CronScheduler(state_dir=self.tmp.name, poll_interval=30)
        self.assertEqual(sched.poll_interval, 30)

    def test_invalid_cron_expression_fallback(self):
        job = self.scheduler.add_job("bad", "not-a-cron", "run")
        # Should not crash; falls back to tomorrow
        self.assertGreater(job.next_run, time.time())


class CronJobResultTests(unittest.TestCase):
    def test_creation_defaults(self):
        r = CronJobResult(job_id="1", job_name="test", objective="run", success=True)
        self.assertEqual(r.output, "")
        self.assertIsNone(r.error)
        self.assertGreater(r.run_at, 0)

    def test_to_dict(self):
        r = CronJobResult(job_id="1", job_name="test", objective="run", success=True, output="done")
        d = r.to_dict()
        self.assertEqual(d["job_id"], "1")
        self.assertEqual(d["success"], True)
        self.assertEqual(d["output"], "done")


if __name__ == "__main__":
    unittest.main()
