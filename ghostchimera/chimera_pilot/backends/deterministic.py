"""Deterministic backend used for tests and offline smoke checks."""

from __future__ import annotations

import ast
import operator as op
import os
import re
from typing import Any

from ...logging_config import get_logger
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult

logger = get_logger("deterministic")

# Machine-readable error code when the deterministic backend cannot fulfill a task.
UNFULFILLED_ERROR = "deterministic_unfulfilled"

# Patterns for tasks the deterministic backend can actually execute.
_LIST_FILES_RE = re.compile(
    r"list(?: the)? files in (?:the )?(.+?)(?: directory)?\.?$",
    re.IGNORECASE,
)
_ARITHMETIC_RE = re.compile(
    r"(?:what is|calculate|compute|evaluate)\s+([0-9+\-*/().\s]+)\??$",
    re.IGNORECASE,
)

# Safe operators for arithmetic evaluation.
_SAFE_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}


def _safe_eval_arithmetic(expr: str) -> float:
    """Evaluate a simple arithmetic expression safely. Raises ValueError on unsafe input."""

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPERATORS:
            return _SAFE_OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPERATORS:
            return _SAFE_OPERATORS[type(node.op)](_eval(node.operand))
        raise ValueError(f"Unsafe expression: {expr!r}")

    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid arithmetic: {expr!r}") from exc
    return _eval(tree)


class DeterministicBackend:
    """A real backend with deterministic, configured behavior.

    This is intentionally simple and explicit.  It is useful for tests,
    scheduler smoke checks, and CI environments where no model provider or
    quantum simulator is available.

    When ``fulfill`` is True, the backend attempts to actually execute
    deterministic tasks it understands (file listing, simple arithmetic)
    instead of returning the placeholder output.  If it cannot fulfill the
    task, it returns ``ok=False`` with a machine-readable
    ``deterministic_unfulfilled`` error rather than false success.  The
    default ``fulfill=False`` preserves the legacy placeholder behavior for
    existing tests.
    """

    id = "deterministic.local"
    name = "Deterministic Local Backend"
    _description = "Deterministic local backend for tests and smoke checks"
    _check_fn = None

    def __init__(
        self,
        backend_id: str = "deterministic.local",
        *,
        kinds: set[TaskKind] | None = None,
        output: Any = "ok",
        fail: bool = False,
        reliability: float = 1.0,
        latency_ms: int = 1,
        supports_offline: bool = True,
        estimated_cost_usd: float = 0.0,
        fulfill: bool = False,
    ) -> None:
        self.id = backend_id
        self._health = BackendHealth(
            available=True,
            reliability=reliability,
            latency_ms=latency_ms,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.capabilities = BackendCapabilities(
            kinds=kinds or {TaskKind.REASONING, TaskKind.TOOL_CALL, TaskKind.RAG_QUERY},
            supports_offline=supports_offline,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=not supports_offline,
            max_context_tokens=4096,
        )
        logger.debug("Provider %s initialized", self.name)
        self._output = output
        self._fail = fail
        self._fulfill = fulfill
        self._using_default_output = output == "ok" and not callable(output)

    def probe(self) -> BackendHealth:
        return self._health

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        return self._health

    def _try_fulfill(self, task: TaskSpec) -> tuple[bool, Any, str]:
        """Attempt to actually execute a deterministic task.

        Returns (fulfilled, output, error).  When fulfilled is False, output
        is empty and error is a machine-readable reason.
        """
        objective = (task.objective or "").strip()
        if not objective:
            return False, "", f"{UNFULFILLED_ERROR}: empty objective"

        # File listing: "list the files in <dir>"
        match = _LIST_FILES_RE.match(objective)
        if match:
            dir_path = match.group(1).strip().strip("'\"")
            try:
                entries = sorted(os.listdir(dir_path))
            except FileNotFoundError:
                return False, "", f"{UNFULFILLED_ERROR}: directory not found: {dir_path}"
            except NotADirectoryError:
                return False, "", f"{UNFULFILLED_ERROR}: not a directory: {dir_path}"
            except OSError as exc:
                return False, "", f"{UNFULFILLED_ERROR}: cannot list directory: {exc}"
            return True, "\n".join(entries), ""

        # Simple arithmetic: "what is 2 + 3"
        match = _ARITHMETIC_RE.match(objective)
        if match:
            expr = match.group(1).strip()
            try:
                result = _safe_eval_arithmetic(expr)
            except ValueError as exc:
                return False, "", f"{UNFULFILLED_ERROR}: {exc}"
            # Format integers without decimal point
            output = str(int(result)) if result.is_integer() else str(result)
            return True, output, ""

        return (
            False,
            "",
            f"{UNFULFILLED_ERROR}: no LLM provider configured; deterministic backend cannot fulfill: {objective[:100]}",
        )

    def execute(self, task: TaskSpec) -> ExecutionResult:
        if self._fail:
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output="",
                error="deterministic failure",
                metrics={"deterministic": True},
            )
        if self._fulfill and self._using_default_output:
            fulfilled, output, error = self._try_fulfill(task)
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=fulfilled,
                output=output if fulfilled else "",
                error=error if not fulfilled else "",
                metrics={"deterministic": True, "fulfilled": fulfilled},
            )
        output = self._output(task) if callable(self._output) else self._output
        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=True,
            output=output,
            metrics={"deterministic": True},
        )
