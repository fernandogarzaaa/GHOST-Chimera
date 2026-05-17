"""Optional pyqpanda3 quantum simulator backend.

This module imports pyqpanda3 lazily.  Ghost Chimera does not require a
physical quantum computer or Origin Pilot installation to load this backend.
"""

from __future__ import annotations

from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult


class PyQPanda3Backend:
    """Run small local quantum simulations through pyqpanda3 when installed."""

    id = "originq.pyqpanda3.local"
    name = "pyqpanda3 Local Quantum Simulator"
    _description = "Quantum simulation via PyQPanda3"
    _check_fn = None  # set at class-definition time below

    @classmethod
    def is_available(cls) -> bool:
        try:
            import pyqpanda3  # noqa: F401
        except ImportError:
            return False
        return True

    _check_fn = is_available

    def __init__(self) -> None:
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.QUANTUM_SIM},
            supports_offline=True,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=False,
            max_context_tokens=None,
        )

    @staticmethod
    def is_available() -> bool:
        try:
            import pyqpanda3.core  # type: ignore  # noqa: F401
        except Exception:
            return False
        return True

    def probe(self) -> BackendHealth:
        if not self.is_available():
            return BackendHealth(
                available=False,
                reliability=0.0,
                latency_ms=999_999,
                estimated_cost_usd=0.0,
                last_error="pyqpanda3 is not installed",
            )
        return BackendHealth(available=True, reliability=0.90, latency_ms=100, estimated_cost_usd=0.0)

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        return self.probe()

    def execute(self, task: TaskSpec) -> ExecutionResult:
        if not self.is_available():
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output="",
                error="pyqpanda3 is not installed",
            )

        circuit = str(task.inputs.get("circuit", "ghz")).lower()
        if circuit != "ghz":
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output="",
                error=f"Unsupported quantum circuit template: {circuit}",
            )
        qubits = max(2, int(task.inputs.get("qubits", 3)))
        shots = max(1, int(task.inputs.get("shots", 1000)))
        return self._run_ghz(task, qubits=qubits, shots=shots)

    def _run_ghz(self, task: TaskSpec, *, qubits: int, shots: int) -> ExecutionResult:
        try:
            from pyqpanda3.core import CNOT, CPUQVM, H, QCircuit, QProg, measure  # type: ignore

            circuit = QCircuit()
            circuit << H(0)
            for index in range(qubits - 1):
                circuit << CNOT(index, index + 1)

            program = QProg()
            program << circuit
            for index in range(qubits):
                program << measure(index, index)

            qvm = CPUQVM()
            qvm.run(program, shots)
            counts = qvm.result().get_counts()
        except Exception as exc:
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output="",
                error=str(exc),
                metrics={"qubits": qubits, "shots": shots},
            )

        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=True,
            output={"counts": dict(counts), "qubits": qubits, "shots": shots},
            metrics={"qubits": qubits, "shots": shots},
        )
