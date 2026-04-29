"""Result verification hooks for Chimera Pilot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .backends.base import ExecutionResult
from .task_ir import TaskSpec


class ResultVerifier:
    """Validate backend output against task constraints."""

    def verify(self, task: TaskSpec, result: ExecutionResult) -> tuple[bool, str | None]:
        if task.constraints.get("require_ok", True) and not result.ok:
            return False, result.error or "backend reported failure"

        if task.constraints.get("expect_json"):
            try:
                if isinstance(result.output, str):
                    json.loads(result.output)
                else:
                    json.dumps(result.output)
            except (TypeError, ValueError) as exc:
                return False, f"output is not valid JSON: {exc}"

        expected_path = task.constraints.get("expect_file_exists")
        if expected_path:
            candidate = Path(str(expected_path)).expanduser()
            if not candidate.exists():
                return False, f"expected file does not exist: {candidate}"

        required_keys = task.constraints.get("expect_output_keys")
        if required_keys:
            if not isinstance(result.output, dict):
                return False, "output is not a dictionary"
            missing = [key for key in required_keys if key not in result.output]
            if missing:
                return False, f"output missing keys: {', '.join(map(str, missing))}"

        return True, None
