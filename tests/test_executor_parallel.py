"""Tests for parallel executor and async executor components."""

import unittest

from ghostchimera.chimera_pilot.backends.deterministic import DeterministicBackend
from ghostchimera.chimera_pilot.calibration import CalibrationStore
from ghostchimera.chimera_pilot.calibration_async import calibrate_backends_parallel
from ghostchimera.chimera_pilot.executor_parallel import execute_tasks_parallel
from ghostchimera.chimera_pilot.scheduler import ChimeraScheduler
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec


class TestExecuteTasksParallel(unittest.TestCase):
    def test_parallel_executes_all_tasks(self):
        task1 = TaskSpec.create(kind=TaskKind.REASONING, objective="task1", inputs={"prompt": "task1"})
        task2 = TaskSpec.create(kind=TaskKind.REASONING, objective="task2", inputs={"prompt": "task2"})
        backend = DeterministicBackend("test", output="done")
        scheduler = ChimeraScheduler([backend])

        result = execute_tasks_parallel([task1, task2], scheduler, max_workers=2)

        self.assertEqual(len(result.results), 2)
        self.assertEqual(result.successes, 2)
        self.assertEqual(result.failures, 0)

    def test_parallel_with_single_task(self):
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="solo", inputs={"prompt": "solo"})
        backend = DeterministicBackend("solo", output="done")
        scheduler = ChimeraScheduler([backend])

        result = execute_tasks_parallel([task], scheduler, max_workers=4)
        self.assertEqual(len(result.results), 1)
        self.assertTrue(result.results[0].ok)

    def test_parallel_empty(self):
        result = execute_tasks_parallel([], ChimeraScheduler([]))
        self.assertEqual(result.successes, 0)
        self.assertEqual(result.failures, 0)

    def test_parallel_to_dict(self):
        task1 = TaskSpec.create(kind=TaskKind.REASONING, objective="t1", inputs={"prompt": "t1"})
        backend = DeterministicBackend("d", output="ok")
        scheduler = ChimeraScheduler([backend])
        result = execute_tasks_parallel([task1], scheduler, max_workers=1)
        d = result.to_dict()
        self.assertIn("results", d)
        self.assertIn("successes", d)
        self.assertIn("total_time_seconds", d)


class TestCalibrateBackendsParallel(unittest.TestCase):
    def test_calibrate_all(self):
        backend = DeterministicBackend("cal", reliability=0.95)
        store = CalibrationStore()
        health = calibrate_backends_parallel([backend], store)
        self.assertIn("cal", health)
        self.assertTrue(health["cal"].available)
        self.assertEqual(health["cal"].reliability, 0.95)

    def test_calibrate_multiple_backends(self):
        b1 = DeterministicBackend("cal1", reliability=0.9)
        b2 = DeterministicBackend("cal2", reliability=0.8)
        store = CalibrationStore()
        health = calibrate_backends_parallel([b1, b2], store)
        self.assertIn("cal1", health)
        self.assertIn("cal2", health)
        self.assertTrue(health["cal1"].available)
        self.assertTrue(health["cal2"].available)
