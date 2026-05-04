"""Integration tests for safety features."""

from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
from ghostchimera.chimera_pilot.schema import validate_task
from ghostchimera.safety_layer.rate_limiter import RateLimiter


def test_path_containment():
    """Path containment check should restrict operations to allowed roots."""
    from ghostchimera.safety_layer.gating import _path_is_under_root
    from pathlib import Path
    root = Path("/tmp").resolve()
    child = Path("/tmp/test.txt").resolve()
    assert _path_is_under_root(root, child)
    parent = Path("/etc/passwd").resolve()
    assert not _path_is_under_root(root, parent)


def test_schema_validates_correct_inputs():
    """Schema validation should accept valid Python task inputs."""
    spec = TaskSpec.create(
        kind=TaskKind.PYTHON,
        objective="test code",
        inputs={"code": "print('hello')"},
        privacy_level="private",
    )
    valid, errors = validate_task(spec.kind, spec.inputs)
    assert valid


def test_schema_rejects_invalid_inputs():
    """Schema validation should reject invalid task inputs."""
    spec = TaskSpec.create(
        kind=TaskKind.PYTHON,
        objective="test code",
        inputs={},  # Missing required 'code' field
        privacy_level="private",
    )
    valid, errors = validate_task(spec.kind, spec.inputs)
    assert not valid
    assert len(errors) > 0


def test_rate_limiter_blocks_excess():
    """Rate limiter should block requests after burst is exhausted."""
    limiter = RateLimiter(rate=10.0, burst=2)
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is False
