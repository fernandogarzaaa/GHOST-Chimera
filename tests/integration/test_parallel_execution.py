"""Integration tests comparing parallel vs sequential execution."""

import unittest

from ghostchimera.chimera_pilot.backends.deterministic import DeterministicBackend
from ghostchimera.chimera_pilot.scheduler import ChimeraScheduler
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
from ghostchimera.chimera_pilot.executor import ChimeraPilotExecutor
from ghostchimera.chimera_pilot.executor_parallel import execute_tasks_parallel
from ghostchimera.chimera_pilot.calibration_async import calibrate_backends_parallel
from ghostchimera.chimera_pilot.calibration import ChimeraCalibrator, CalibrationStore


class TestParallelExecutionIntegration(unittest.TestCase):
    def test_parallel_matches_sequential(self):
        task1 = TaskSpec.create(kind=TaskKind.REASONING, objective="determine answer", inputs={"prompt": "2+2"})
        task2 = TaskSpec.create(kind=TaskKind.REASONING, objective="determine answer", inputs={"prompt": "3+3"})
        backend = DeterministicBackend("integration", output=lambda t: f"ok:{t.objective}")
        scheduler = ChimeraScheduler([backend])

        # Sequential
        seq_executor = ChimeraPilotExecutor(scheduler)
        seq_results = [seq_executor.execute(t) for t in [task1, task2]]

        # Parallel
        par_results = execute_tasks_parallel([task1, task2], scheduler, max_workers=2)

        self.assertEqual(len(par_results.results), len(seq_results))
        for par, seq in zip(par_results.results, seq_results):
            self.assertEqual(par.result.output, seq.result.output)
            self.assertEqual(par.ok, seq.ok)

    def test_parallel_calibrate_matches_sequential(self):
        backend1 = DeterministicBackend("cal1", reliability=0.9)
        backend2 = DeterministicBackend("cal2", reliability=0.8)
        store_seq = CalibrationStore()
        store_par = CalibrationStore()

        calibrator = ChimeraCalibrator([backend1, backend2], store_seq)
        seq_health = calibrator.run_once()

        par_health = calibrate_backends_parallel([backend1, backend2], store_par)

        for bid in seq_health:
            self.assertIn(bid, par_health)
            self.assertEqual(seq_health[bid].reliability, par_health[bid].reliability)
            self.assertEqual(seq_health[bid].available, par_health[bid].available)

    def test_parallel_multi_task_matches_sequential(self):
        tasks = [
            TaskSpec.create(kind=TaskKind.REASONING, objective=f"task-{i}")
            for i in range(5)
        ]
        backend = DeterministicBackend("multi", output="done")
        scheduler = ChimeraScheduler([backend])

        seq_executor = ChimeraPilotExecutor(scheduler)
        seq_results = [seq_executor.execute(t) for t in tasks]

        par_results = execute_tasks_parallel(tasks, scheduler, max_workers=4)

        self.assertEqual(len(par_results.results), len(seq_results))
        self.assertEqual(par_results.successes, len(seq_results))
