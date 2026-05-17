"""Input schema validation for Chimera Pilot tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .desktop_policy import DESKTOP_ACTION_CLASSES
from .task_ir import TaskKind


@dataclass
class _KindSchema:
    """Schema definition for a single TaskKind."""

    required_fields: list[str]
    optional_fields: list[str]
    field_types: dict  # field_name -> type
    value_constraints: dict  # field_name -> callable(value) -> bool


def _is_desktop_plan(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for step in value:
        if not isinstance(step, dict):
            return False
        action = str(step.get("action", "")).strip().lower()
        if action not in {"click", "double_click", "right_click", "type", "hotkey", "move"}:
            return False
        keys = step.get("keys")
        if keys is not None and (not isinstance(keys, list) or not all(isinstance(item, str) for item in keys)):
            return False
    return True


def _is_target_descriptor(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    allowed = {"app", "window", "control", "text"}
    return all(k in allowed and isinstance(v, str) for k, v in value.items())


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
    TaskKind.DESKTOP_CONTROL: _KindSchema(
        required_fields=["action"],
        optional_fields=["target", "x", "y", "text", "keys", "action_class", "plan", "target_descriptor", "trace_id"],
        field_types={"action": str},
        value_constraints={
            "action": lambda v: (
                isinstance(v, str)
                and v.strip().lower()
                in {
                    "click",
                    "double_click",
                    "right_click",
                    "type",
                    "hotkey",
                    "move",
                    "plan",
                }
            ),
            "keys": lambda v: isinstance(v, list) and all(isinstance(item, str) for item in v),
            "action_class": lambda v: (
                isinstance(v, str) and v.strip().lower().replace("-", "_") in DESKTOP_ACTION_CLASSES
            ),
            "plan": _is_desktop_plan,
            "target_descriptor": _is_target_descriptor,
        },
    ),
    # ── Track 2: Gemini long-context ────────────────────────────────────────
    TaskKind.LONG_CONTEXT_DOC: _KindSchema(
        required_fields=["instruction"],
        optional_fields=["documents", "history", "max_output_tokens"],
        field_types={"instruction": str},
        value_constraints={
            "instruction": lambda v: isinstance(v, str) and len(v.strip()) > 0,
        },
    ),
    # ── Track 3: Simulation ──────────────────────────────────────────────────
    TaskKind.SIMULATION: _KindSchema(
        required_fields=["sim_mode"],
        optional_fields=[
            "robot",
            "environment",
            "waypoints",
            "states",
            "sensors",
            "policy",
            "episodes",
            "dt",
            "tick_rate_hz",
        ],
        field_types={"sim_mode": str},
        value_constraints={
            "sim_mode": lambda v: (
                isinstance(v, str) and v.strip().lower() in {"kinematics", "digital_twin", "policy_test"}
            ),
        },
    ),
    # ── Track 4: Analytics ──────────────────────────────────────────────────
    TaskKind.ANALYTICS_QUERY: _KindSchema(
        required_fields=["query"],
        optional_fields=["data", "columns"],
        field_types={"query": str},
        value_constraints={
            "query": lambda v: isinstance(v, str) and len(v.strip()) > 0,
        },
    ),
    TaskKind.DATA_PIPELINE: _KindSchema(
        required_fields=["data"],
        optional_fields=["schema", "pipeline"],
        field_types={},
        value_constraints={},
    ),
}


class PythonSchema:
    """Validate Python task inputs."""

    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        errors = _KindSchema(
            required_fields=["code"],
            optional_fields=[],
            field_types={"code": str},
            value_constraints={"code": lambda v: isinstance(v, str) and len(v.strip()) > 0},
        )
        return _validate_one(inputs, errors)


class TestRunSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        errors = _KIND_SCHEMAS[TaskKind.TEST_RUN]
        return _validate_one(inputs, errors)


class QuantumSimSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        errors = _KIND_SCHEMAS[TaskKind.QUANTUM_SIM]
        return _validate_one(inputs, errors)


class WebResearchSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        errors = _KIND_SCHEMAS[TaskKind.WEB_RESEARCH]
        return _validate_one(inputs, errors)


class FileAnalysisSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        errors = _KIND_SCHEMAS[TaskKind.FILE_ANALYSIS]
        return _validate_one(inputs, errors)


class RagQuerySchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        errors = _KIND_SCHEMAS[TaskKind.RAG_QUERY]
        return _validate_one(inputs, errors)


class ReasoningSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        errors = _KIND_SCHEMAS[TaskKind.REASONING]
        return _validate_one(inputs, errors)


class DesktopControlSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        errors = _KIND_SCHEMAS[TaskKind.DESKTOP_CONTROL]
        return _validate_one(inputs, errors)


class LongContextDocSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        return _validate_one(inputs, _KIND_SCHEMAS[TaskKind.LONG_CONTEXT_DOC])


class SimulationSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        return _validate_one(inputs, _KIND_SCHEMAS[TaskKind.SIMULATION])


class AnalyticsQuerySchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        return _validate_one(inputs, _KIND_SCHEMAS[TaskKind.ANALYTICS_QUERY])


class DataPipelineSchema:
    @staticmethod
    def validate(inputs: dict[str, Any]) -> tuple[bool, list[str]]:
        return _validate_one(inputs, _KIND_SCHEMAS[TaskKind.DATA_PIPELINE])


_KIND_VALIDATORS = {
    TaskKind.PYTHON: PythonSchema.validate,
    TaskKind.TEST_RUN: TestRunSchema.validate,
    TaskKind.QUANTUM_SIM: QuantumSimSchema.validate,
    TaskKind.WEB_RESEARCH: WebResearchSchema.validate,
    TaskKind.FILE_ANALYSIS: FileAnalysisSchema.validate,
    TaskKind.RAG_QUERY: RagQuerySchema.validate,
    TaskKind.REASONING: ReasoningSchema.validate,
    TaskKind.DESKTOP_CONTROL: DesktopControlSchema.validate,
    TaskKind.LONG_CONTEXT_DOC: LongContextDocSchema.validate,
    TaskKind.SIMULATION: SimulationSchema.validate,
    TaskKind.ANALYTICS_QUERY: AnalyticsQuerySchema.validate,
    TaskKind.DATA_PIPELINE: DataPipelineSchema.validate,
}


def _validate_one(
    inputs: dict[str, Any],
    schema: _KindSchema,
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    for field in schema.required_fields:
        if field not in inputs or inputs[field] is None:
            errors.append(f"Missing required field: {field}")

    for field, expected_type in schema.field_types.items():
        if field in inputs and inputs[field] is not None and not isinstance(inputs[field], expected_type):
            errors.append(f"Field {field} must be {expected_type.__name__}, got {type(inputs[field]).__name__}")

    for field, constraint_fn in schema.value_constraints.items():
        if field in inputs and inputs[field] is not None and not constraint_fn(inputs[field]):
            errors.append(f"Field {field} failed validation constraint")

    return (len(errors) == 0, errors)


def validate_task(
    task_kind: TaskKind,
    inputs: dict[str, Any],
) -> tuple[bool, list[str]]:
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
