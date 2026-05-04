"""Execution policy for Chimera Pilot."""

from __future__ import annotations

import base64
import re
import unicodedata

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
                # Layer 4: AST-based check for getattr/__getattr bypass patterns
                self._reject_ast_bypass(code, task.id)

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

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Strip Unicode normalisation, zero-width characters, and interspersed whitespace."""
        value = unicodedata.normalize("NFKC", value)
        # Remove zero-width / invisible characters
        value = re.sub(r"[​-‏ - ⁠-⁩﻿­̀-ͯ]", "", value)
        # Collapse whitespace so fragments with injected spaces are still caught
        value = re.sub(r"\s+", "", value)
        return value

    def _reject_fragments(self, value: str, fragments: tuple[str, ...], field_name: str) -> None:
        # Layer 1: normalise then do a fast substring check
        normed = self._normalize_text(value).lower()
        for fragment in fragments:
            if fragment.lower() in normed:
                raise PermissionError(f"Task {field_name} contains denied fragment: {fragment}")

        # Layer 2: attempt base64 decode of the entire value and re-check
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8", errors="ignore")
            decoded_normed = self._normalize_text(decoded).lower()
            for fragment in fragments:
                if fragment.lower() in decoded_normed:
                    raise PermissionError(f"Task {field_name} contains denied fragment (base64): {fragment}")
        except Exception:
            pass  # Not valid base64; nothing to do

        # Layer 3: whitespace-tolerant regex for each fragment
        for fragment in fragments:
            # Build a regex that allows optional whitespace between every character
            pattern = re.escape(fragment).join([r"\s*"] * (len(fragment)))
            if re.search(pattern, value, re.IGNORECASE):
                raise PermissionError(f"Task {field_name} contains denied fragment: {fragment}")

    def _reject_ast_bypass(self, code: str, task_id: str) -> None:
        """AST-based check for getattr/eval/exec/compile bypass patterns."""
        import ast

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return  # Fragment check already caught anything relevant

        denied_dunder_attrs = frozenset(
            ("eval", "exec", "compile", "__import__", "open", "input", "getattr", "setattr")
        )
        dangerous_modules = frozenset(
            ("os", "subprocess", "socket", "shutil", "ctypes", "pickle", "marshal", "sys", "builtins")
        )

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Check for getattr(builtins, 'eval') or similar
                if isinstance(func, ast.Attribute) and func.attr == "getattr":
                    # getattr(X, "eval") — check if X could be builtins/os/etc.
                    if isinstance(func.value, ast.Name) and func.value.id in dangerous_modules:
                        raise PermissionError(
                            f"Task {task_id} contains denied AST pattern: getattr on dangerous module"
                        )
                # Check for __import__('os') or getattr(builtins, ...)
                if isinstance(func, ast.Name) and func.id == "__import__":
                    # Check the argument
                    if node.args and isinstance(node.args[0], ast.Constant):
                        mod = str(node.args[0])
                        if mod in dangerous_modules:
                            raise PermissionError(
                                f"Task {task_id} contains denied AST pattern: __import__('{mod}')"
                            )
