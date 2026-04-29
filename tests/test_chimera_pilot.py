from __future__ import annotations

import json
import unittest

from ghostchimera.chimera_pilot import ChimeraPilotKernel, ChimeraScheduler, ResourceRegistry, TaskKind, TaskSpec
from ghostchimera.chimera_pilot.backends import BackendHealth, DeterministicBackend, PythonRuntimeBackend
from ghostchimera.chimera_pilot.calibration import CalibrationStore, ChimeraCalibrator
from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
from ghostchimera.chimera_pilot.executor import ChimeraPilotExecutor
from ghostchimera.chimera_pilot.policy import PilotPolicy


class ChimeraPilotTests(unittest.TestCase):
    def test_scheduler_selects_highest_reliability_backend(self) -> None:
        weak = DeterministicBackend("weak", reliability=0.40, latency_ms=1)
        strong = DeterministicBackend("strong", reliability=0.95, latency_ms=1)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="decide")

        decision = ChimeraScheduler([weak, strong]).select_backend(task)

        self.assertEqual(decision.backend.id, "strong")
        self.assertGreater(decision.score, 0)

    def test_unavailable_backend_is_skipped(self) -> None:
        class UnavailableBackend(DeterministicBackend):
            def probe(self) -> BackendHealth:
                return BackendHealth(available=False, reliability=0.0, latency_ms=999)

            def estimate(self, task: TaskSpec) -> BackendHealth:
                return self.probe()

        unavailable = UnavailableBackend("unavailable")
        available = DeterministicBackend("available")
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="decide")

        decision = ChimeraScheduler([unavailable, available]).select_backend(task)

        self.assertEqual(decision.backend.id, "available")

    def test_privacy_sensitive_task_prefers_offline_backend(self) -> None:
        offline = DeterministicBackend("offline", reliability=0.80, supports_offline=True)
        network = DeterministicBackend("network", reliability=0.90, supports_offline=False)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="private plan", privacy_level="sensitive")

        decision = ChimeraScheduler([network, offline]).select_backend(task)

        self.assertEqual(decision.backend.id, "offline")
        self.assertIn("offline_privacy_bonus", decision.reasons)

    def test_executor_falls_back_after_backend_failure(self) -> None:
        failing = DeterministicBackend("failing", fail=True, reliability=1.0)
        succeeding = DeterministicBackend("succeeding", output="done", reliability=0.9)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute")
        executor = ChimeraPilotExecutor(ChimeraScheduler([failing, succeeding]))

        execution = executor.execute(task)

        self.assertTrue(execution.ok)
        self.assertEqual(execution.result.backend_id, "succeeding")
        self.assertEqual(len(execution.attempts), 2)

    def test_calibration_updates_reliability(self) -> None:
        backend = DeterministicBackend("calibrated", reliability=0.75)
        store = CalibrationStore()
        calibrator = ChimeraCalibrator([backend], store)

        calibrator.run_once()

        self.assertIn("calibrated", store.records)
        self.assertGreater(store.reliability("calibrated"), 0.0)

    def test_compiler_detects_python_and_quantum_tasks(self) -> None:
        compiler = RuleBasedTaskCompiler()

        python_task = compiler.compile("python: print('hello')")[0]
        quantum_task = compiler.compile("simulate a 4-qubit GHZ quantum circuit")[0]

        self.assertEqual(python_task.kind, TaskKind.PYTHON)
        self.assertEqual(python_task.inputs["code"], "print('hello')")
        self.assertEqual(quantum_task.kind, TaskKind.QUANTUM_SIM)
        self.assertEqual(quantum_task.inputs["qubits"], 4)

    def test_python_runtime_backend_executes_real_python_code(self) -> None:
        task = TaskSpec.create(kind=TaskKind.PYTHON, objective="python", inputs={"code": "print(2 + 3)"})
        result = PythonRuntimeBackend().execute(task)

        self.assertTrue(result.ok)
        self.assertEqual(result.output.strip(), "5")

    def test_kernel_status_and_compile_are_json_serializable(self) -> None:
        registry = ResourceRegistry()
        registry.register(DeterministicBackend())
        kernel = ChimeraPilotKernel(registry=registry)

        status = kernel.status()
        compiled = kernel.compile("retrieve memory about project")

        json.dumps(status)
        self.assertEqual(compiled[0].kind, TaskKind.RAG_QUERY)

    def test_policy_rejects_network_when_disabled(self) -> None:
        task = TaskSpec.create(kind=TaskKind.WEB_RESEARCH, objective="research latest models", requires_network=True)

        with self.assertRaises(PermissionError):
            PilotPolicy(allow_network=False).validate(task)



class ChimeraPilotReleaseHardeningTests(unittest.TestCase):
    def test_kernel_rejects_python_execution_by_default(self) -> None:
        kernel = ChimeraPilotKernel.default(include_deterministic_backend=True)

        with self.assertRaises(PermissionError):
            kernel.run("python: print(2 + 3)")

    def test_kernel_can_opt_in_to_python_execution(self) -> None:
        kernel = ChimeraPilotKernel.default(allow_python_execution=True)

        execution = kernel.run("python: print(2 + 3)")[0]

        self.assertTrue(execution.ok)
        self.assertEqual(str(execution.result.output).strip(), "5")

    def test_python_runtime_rejects_unsafe_python_calls(self) -> None:
        task = TaskSpec.create(kind=TaskKind.PYTHON, objective="python", inputs={"code": "open('/etc/passwd').read()"})

        result = PythonRuntimeBackend().execute(task)

        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error or "")

    def test_policy_rejects_unsafe_python_fragment(self) -> None:
        task = TaskSpec.create(kind=TaskKind.PYTHON, objective="python", inputs={"code": "import subprocess\nsubprocess.run(['echo', 'x'])"})

        with self.assertRaises(PermissionError):
            PilotPolicy(allow_python_execution=True).validate(task)


if __name__ == "__main__":
    unittest.main()
