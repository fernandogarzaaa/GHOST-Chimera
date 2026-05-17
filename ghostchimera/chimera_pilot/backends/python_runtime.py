"""Python runtime backend for local execution and test runs."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ...logging_config import get_logger
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult

logger = get_logger("python_runtime")


class PythonRuntimeBackend:
    """Execute local Python snippets and unittest discovery commands.

    This backend is intentionally opt-in at the policy layer.  When used, it
    runs with bytecode disabled, a minimal environment, a bounded timeout, and a
    temporary working directory unless a caller provides an allowed cwd.
    """

    id = "python.local"
    name = "Local Python Runtime"

    _description = "Sandboxed local Python execution backend"
    _DEFAULT_SAFE_IMPORTS = frozenset(
        {
            "collections",
            "datetime",
            "decimal",
            "fractions",
            "functools",
            "itertools",
            "json",
            "math",
            "re",
            "statistics",
            "string",
            "typing",
        }
    )

    def __init__(
        self,
        *,
        default_timeout_seconds: int = 10,
        cwd: str | None = None,
        allowed_roots: list[str] | None = None,
        allow_imports: bool = False,
        safe_imports: set[str] | None = None,
    ) -> None:
        self.default_timeout_seconds = max(1, min(default_timeout_seconds, 60))
        self.cwd = Path(cwd).expanduser().resolve() if cwd else None
        self.allowed_roots = [Path(path).expanduser().resolve() for path in (allowed_roots or [])]
        if self.cwd and not self.allowed_roots:
            self.allowed_roots = [self.cwd]
        self.allow_imports = allow_imports
        self.safe_imports = safe_imports or set(self._DEFAULT_SAFE_IMPORTS)
        logger.debug("Provider %s initialized", self.name)
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.PYTHON, TaskKind.TEST_RUN},
            supports_offline=True,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=False,
            max_context_tokens=None,
        )

    def probe(self) -> BackendHealth:
        return BackendHealth(available=True, reliability=0.90, latency_ms=75, estimated_cost_usd=0.0)

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        timeout_ms = self._timeout_seconds(task) * 1000
        return BackendHealth(available=True, reliability=0.90, latency_ms=min(timeout_ms, 1000), estimated_cost_usd=0.0)

    def execute(self, task: TaskSpec) -> ExecutionResult:
        if task.kind == TaskKind.PYTHON:
            return self._execute_python(task)
        if task.kind == TaskKind.TEST_RUN:
            return self._execute_unittest(task)
        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=False,
            output="",
            error=f"Unsupported task kind: {task.kind.value}",
        )

    def _execute_python(self, task: TaskSpec) -> ExecutionResult:
        code = str(task.inputs.get("code", ""))
        if not code.strip():
            return ExecutionResult(self.id, task.id, False, "", error="Missing Python code")
        safety_error = self._validate_python_code(code, task)
        if safety_error:
            return ExecutionResult(self.id, task.id, False, "", error=safety_error)
        return self._run(task, [sys.executable, "-B", "-I", "-c", code])

    def _execute_unittest(self, task: TaskSpec) -> ExecutionResult:
        pattern = str(task.inputs.get("pattern", "test_*.py"))
        start_dir = str(task.inputs.get("start_dir", "tests"))
        if any(part in pattern for part in ("/", "\\", "..")):
            return ExecutionResult(self.id, task.id, False, "", error="Unsafe unittest pattern")
        return self._run(task, [sys.executable, "-B", "-m", "unittest", "discover", "-s", start_dir, "-p", pattern])

    def _run(self, task: TaskSpec, command: list[str]) -> ExecutionResult:
        timeout = self._timeout_seconds(task)
        cwd, temp_dir = self._resolve_cwd(task)
        if isinstance(cwd, str):
            return ExecutionResult(self.id, task.id, False, "", error=cwd)

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout if isinstance(exc.stdout, str) else ""
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output=output,
                error=f"Timed out after {timeout} seconds",
                metrics={"timeout_seconds": timeout, "command": self._redacted_command(command), "cwd": str(cwd)},
            )
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=completed.returncode == 0,
            output=completed.stdout,
            error=None if completed.returncode == 0 else f"Process exited with code {completed.returncode}",
            metrics={"returncode": completed.returncode, "command": self._redacted_command(command), "cwd": str(cwd)},
        )

    def _timeout_seconds(self, task: TaskSpec) -> int:
        raw = int(task.constraints.get("timeout_seconds", self.default_timeout_seconds))
        return max(1, min(raw, 60))

    def _resolve_cwd(self, task: TaskSpec) -> tuple[Path | str, tempfile.TemporaryDirectory[str] | None]:
        cwd_value = task.inputs.get("cwd") or task.constraints.get("cwd")
        if cwd_value:
            cwd = Path(str(cwd_value)).expanduser().resolve()
        elif self.cwd:
            cwd = self.cwd
        else:
            temp_dir = tempfile.TemporaryDirectory(prefix="ghostchimera-python-")
            return Path(temp_dir.name), temp_dir

        if not cwd.exists() or not cwd.is_dir():
            return f"Working directory does not exist: {cwd}", None
        if self.allowed_roots:
            _under_root = any(
                str(cwd) == str(root) or str(cwd).startswith(str(root) + "/") for root in self.allowed_roots
            )
            if not _under_root:
                return f"Working directory is outside allowed roots: {cwd}", None
        return cwd, None

    def _validate_python_code(self, code: str, task: TaskSpec) -> str | None:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return f"Invalid Python syntax: {exc}"

        allow_imports = bool(task.constraints.get("allow_imports", self.allow_imports))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name.split(".", 1)[0] for alias in getattr(node, "names", [])]
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module.split(".", 1)[0])
                if not allow_imports:
                    unsafe = [name for name in names if name not in self.safe_imports]
                    if unsafe:
                        return f"Import is not allowed in sandboxed Python: {', '.join(sorted(set(unsafe)))}"
            if isinstance(node, ast.Call):
                name = self._call_name(node.func)
                if name in {"eval", "exec", "compile", "__import__", "open", "input"}:
                    return f"Call is not allowed in sandboxed Python: {name}"
                if name.startswith(("os.", "subprocess.", "socket.", "shutil.")):
                    return f"Call is not allowed in sandboxed Python: {name}"
        return None

    def _call_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = self._call_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return ""

    def _redacted_command(self, command: list[str]) -> list[str]:
        if len(command) >= 4 and command[-2] == "-c":
            return [*command[:-1], "<python-code>"]
        return list(command)
