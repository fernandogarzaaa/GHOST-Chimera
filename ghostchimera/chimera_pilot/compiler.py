"""Rule-based compiler from high-level objectives into Chimera Pilot tasks."""

from __future__ import annotations

import re

from .schema import validate_task
from .task_ir import TaskKind, TaskSpec


class RuleBasedTaskCompiler:
    """Small deterministic compiler for common Ghost Chimera objectives."""

    def compile(self, objective: str) -> list[TaskSpec]:
        text = objective.strip()
        if not text:
            raise ValueError("Objective cannot be empty")

        lower = text.lower()

        python_code = self._extract_prefixed_payload(text, prefixes=("python:", "run python:", "execute python:"))
        if python_code is not None:
            spec = TaskSpec.create(
                kind=TaskKind.PYTHON,
                objective=text,
                inputs={"code": python_code},
                privacy_level="private",
                max_cost_usd=0.0,
                max_latency_ms=10_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if lower.startswith("run tests") or lower.startswith("test ") or "run unittest" in lower:
            spec = TaskSpec.create(
                kind=TaskKind.TEST_RUN,
                objective=text,
                inputs=self._compile_test_inputs(text),
                privacy_level="private",
                max_cost_usd=0.0,
                max_latency_ms=60_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if any(token in lower for token in ("quantum", "qasm", "qubit", "ghz")):
            spec = TaskSpec.create(
                kind=TaskKind.QUANTUM_SIM,
                objective=text,
                inputs={"circuit": "ghz" if "ghz" in lower else "default", "qubits": self._extract_qubit_count(lower)},
                privacy_level="normal",
                max_cost_usd=0.0,
                max_latency_ms=10_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if lower.startswith("research ") or lower.startswith("search web ") or "latest" in lower:
            spec = TaskSpec.create(
                kind=TaskKind.WEB_RESEARCH,
                objective=text,
                inputs={"query": text},
                requires_network=True,
                privacy_level="normal",
                max_latency_ms=30_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if lower.startswith("analyze file") or lower.startswith("inspect file"):
            spec = TaskSpec.create(
                kind=TaskKind.FILE_ANALYSIS,
                objective=text,
                inputs={"path": text.split(maxsplit=2)[-1] if len(text.split(maxsplit=2)) == 3 else ""},
                privacy_level="private",
                max_cost_usd=0.0,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if "rag" in lower or "retrieve" in lower:
            spec = TaskSpec.create(
                kind=TaskKind.RAG_QUERY,
                objective=text,
                inputs={"query": text},
                privacy_level="normal",
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        spec = TaskSpec.create(
            kind=TaskKind.REASONING,
            objective=text,
            inputs={"prompt": text},
            privacy_level="normal",
        )
        validate_task(spec.kind, spec.inputs)
        return [spec]

    def _extract_prefixed_payload(self, text: str, prefixes: tuple[str, ...]) -> str | None:
        stripped = text.strip()
        lower = stripped.lower()
        for prefix in prefixes:
            if lower.startswith(prefix):
                return stripped[len(prefix) :].strip()
        return None

    def _extract_qubit_count(self, lower: str) -> int:
        match = re.search(r"(\d+)\s*-?\s*qubit", lower)
        if not match:
            return 3
        return max(2, int(match.group(1)))

    def _compile_test_inputs(self, text: str) -> dict[str, str]:
        match = re.search(r"pattern\s*=\s*([^\s]+)", text)
        if match:
            return {"pattern": match.group(1)}
        return {"pattern": "test_*.py"}
