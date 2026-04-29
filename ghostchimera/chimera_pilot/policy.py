"""Execution policy for Chimera Pilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .task_ir import TaskKind, TaskSpec


@dataclass(frozen=True)
class PilotPolicy:
    """Safety and resource policy checked before execution.

    The public-release default is conservative: network access and local code
    execution are both disabled unless a caller opts in explicitly.  This keeps
    Ghost Chimera useful for scheduling, compilation, calibration, and dry-run
    workflows while avoiding surprising execution of untrusted local code.
    """

    allow_network: bool = False
    allow_python_execution: bool = False
    allow_quantum_simulation: bool = True
    default_max_cost_usd: float = 0.0
    max_python_timeout_seconds: int = 30
    denied_objective_fragments: tuple[str, ...] = field(
        default_factory=lambda: (
            "rm -rf /",
            ":(){ :|:& };:",
            "curl | sh",
            "wget | sh",
        )
    )
    denied_python_fragments: tuple[str, ...] = field(
        default_factory=lambda: (
            "os.system",
            "subprocess",
            "shutil.rmtree",
            "socket.",
            "urllib.request",
            "requests.",
            "eval(",
            "exec(",
            "__import__",
            "open('/etc/",
            'open("/etc/',
        )
    )

    def validate(self, task: TaskSpec) -> None:
        self._reject_fragments(task.objective, self.denied_objective_fragments, "objective")

        if task.requires_network and not self.allow_network:
            raise PermissionError("Task requires network access, but network execution is disabled by policy")

        if task.kind in {TaskKind.PYTHON, TaskKind.TEST_RUN}:
            if not self.allow_python_execution:
                raise PermissionError("Local Python/test execution is disabled by policy")
            timeout = int(task.constraints.get("timeout_seconds", self.max_python_timeout_seconds))
            if timeout > self.max_python_timeout_seconds:
                raise PermissionError(
                    f"Python timeout {timeout}s exceeds policy maximum of {self.max_python_timeout_seconds}s"
                )
            code = str(task.inputs.get("code", ""))
            if code:
                self._reject_fragments(code, self.denied_python_fragments, "Python code")

        if task.kind == TaskKind.QUANTUM_SIM and not self.allow_quantum_simulation:
            raise PermissionError("Quantum simulation is disabled by policy")

        max_cost = task.max_cost_usd
        if max_cost is None:
            max_cost = self.default_max_cost_usd
        if max_cost < 0:
            raise PermissionError("Negative task cost budgets are not valid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_network": self.allow_network,
            "allow_python_execution": self.allow_python_execution,
            "allow_quantum_simulation": self.allow_quantum_simulation,
            "default_max_cost_usd": self.default_max_cost_usd,
            "max_python_timeout_seconds": self.max_python_timeout_seconds,
        }

    def _reject_fragments(self, value: str, fragments: tuple[str, ...], field_name: str) -> None:
        lower_value = value.lower()
        for fragment in fragments:
            if fragment.lower() in lower_value:
                raise PermissionError(f"Task {field_name} contains denied fragment: {fragment}")
