"""Input schema validation for Chimera Pilot tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Tuple

from .task_ir import TaskKind


@dataclass
class _KindSchema:
    """Schema definition for a single TaskKind."""

    required_fields: List[str]
    optional_fields: List[str]
    field_types: dict  # field_name -> type
    value_constraints: dict  # field_name -> callable(value) -> bool


_KIND_SCHEMAS: dict[TaskKind, _KindSchema] = {
    TaskKind.PYTHON: _KindSchema(
        required_fields=["code"],
        optional_fields=["cwd", "args"],
        field_types={"code": str},
        value_constraints={"code": lambda v: isinstance(v, str) and len(v.strip()) > 0},
    ),
    TaskKind.TEST_RUN: _KindSchema(
        required_fields=["pattern", "start_dir"],
        optional_fields=["extra_args"],
        field_types={"pattern": str, "start_dir": str},
        value_constraints={
            "pattern": lambda v: isinstance(v, str) and all(c not in v for c in ("/", "\\", "..")),
            "start_dir": lambda v: isinstance(v, str),
        },
    ),
    TaskKind.QUANTUM_SIM: _KindSchema(
        required_fields=["circuit"],
        optional_fields=["qubits"],
        field_types={"circuit": str, "qubits": int},
        value_constraints={
            "circuit": lambda v: isinstance(v, str) and len(v.strip()) > 0,
            "qubits": lambda v: isinstance(v, int) and v >= 1,
        },
    ),
    TaskKind.WEB_RESEARCH: _KindSchema(
        required_fields=["query"],
        optional_fields=["max_results", "sites"],
        field_types={"query": str},
        value_constraints={
            "query": lambda v: isinstance(v, str) and len(v.strip()) > 0,
        },
    ),
    TaskKind.FILE_ANALYSIS: _KindSchema(
        required_fields=["path"],
        optional_fields=["line_range"],
        field_types={"path": str},
        value_constraints={
            "path": lambda v: isinstance(v, str) and len(v.strip()) > 0,
        },
    ),
    TaskKind.RAG_QUERY: _KindSchema(
        required_fields=["query"],
        optional_fields=["limit", "sources"],
        field_types={"query": str},
        value_constraints={
            "query": lambda v: isinstance(v, str) and len(v.strip()) > 0,
        },
    ),
    TaskKind.REASONING: _KindSchema(
        required_fields=["prompt"],
        optional_fields=[],
        field_types={"prompt": str},
        value_constraints={
            "prompt": lambda v: isinstance(v, str) and len(v.strip()) > 0,
        },
    ),
}


class PythonSchema:
    """Validate Python task inputs."""

    @staticmethod
    def validate(inputs: dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = _KindSchema(
            required_fields=["code"],
            optional_fields=[],
            field_types={"code": str},
            value_constraints={"code": lambda v: isinstance(v, str) and len(v.strip()) > 0},
        )
        return _validate_one(inputs, errors)


class TestRunSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = _KIND_SCHEMAS[TaskKind.TEST_RUN]
        return _validate_one(inputs, errors)


class QuantumSimSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = _KIND_SCHEMAS[TaskKind.QUANTUM_SIM]
        return _validate_one(inputs, errors)


class WebResearchSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = _KIND_SCHEMAS[TaskKind.WEB_RESEARCH]
        return _validate_one(inputs, errors)


class FileAnalysisSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = _KIND_SCHEMAS[TaskKind.FILE_ANALYSIS]
        return _validate_one(inputs, errors)


class RagQuerySchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = _KIND_SCHEMAS[TaskKind.RAG_QUERY]
        return _validate_one(inputs, errors)


class ReasoningSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = _KIND_SCHEMAS[TaskKind.REASONING]
        return _validate_one(inputs, errors)


_KIND_VALIDATORS = {
    TaskKind.PYTHON: PythonSchema.validate,
    TaskKind.TEST_RUN: TestRunSchema.validate,
    TaskKind.QUANTUM_SIM: QuantumSimSchema.validate,
    TaskKind.WEB_RESEARCH: WebResearchSchema.validate,
    TaskKind.FILE_ANALYSIS: FileAnalysisSchema.validate,
    TaskKind.RAG_QUERY: RagQuerySchema.validate,
    TaskKind.REASONING: ReasoningSchema.validate,
}


def _validate_one(
    inputs: dict[str, Any],
    schema: _KindSchema,
) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    for field in schema.required_fields:
        if field not in inputs or inputs[field] is None:
            errors.append(f"Missing required field: {field}")

    for field, expected_type in schema.field_types.items():
        if field in inputs and inputs[field] is not None and not isinstance(inputs[field], expected_type):
            errors.append(f"Field {field} must be {expected_type.__name__}, got {type(inputs[field]).__name__}")

    for field, constraint_fn in schema.value_constraints.items():
        if field in inputs and inputs[field] is not None:
            if not constraint_fn(inputs[field]):
                errors.append(f"Field {field} failed validation constraint")

    return (len(errors) == 0, errors)


def validate_task(
    task_kind: TaskKind,
    inputs: dict[str, Any],
) -> Tuple[bool, List[str]]:
    """Validate *inputs* for the given *task_kind*.

    Returns
    -------
    tuple[bool, list[str]]
        (is_valid, error_messages)
    """
    validator = _KIND_VALIDATORS.get(task_kind)
    if validator is None:
        return True, []
    return validator(inputs)
