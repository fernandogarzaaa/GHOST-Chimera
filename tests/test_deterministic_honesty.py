"""Tests for deterministic backend honest fulfillment."""

from __future__ import annotations

import pytest

from ghostchimera.chimera_pilot.backends.deterministic import (
    UNFULFILLED_ERROR,
    DeterministicBackend,
    _safe_eval_arithmetic,
)
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec


def _task(objective: str) -> TaskSpec:
    return TaskSpec.create(kind=TaskKind.REASONING, objective=objective)


def test_legacy_placeholder_behavior_unchanged() -> None:
    """Default fulfill=False preserves the legacy 'ok' placeholder for existing tests."""
    backend = DeterministicBackend()
    result = backend.execute(_task("do anything"))
    assert result.ok is True
    assert result.output == "ok"
    assert result.metrics == {"deterministic": True}


def test_fulfill_disabled_with_custom_output() -> None:
    backend = DeterministicBackend(output="custom")
    result = backend.execute(_task("do anything"))
    assert result.ok is True
    assert result.output == "custom"


def test_init_health_and_capabilities() -> None:
    backend = DeterministicBackend()
    health = backend.probe()
    assert health.available is True
    assert health.reliability == 1.0
    assert health.latency_ms == 1
    assert health.estimated_cost_usd == 0.0
    caps = backend.capabilities
    assert caps.supports_offline is True
    assert caps.supports_streaming is False
    assert caps.supports_gpu is False
    assert TaskKind.REASONING in caps.kinds


def test_fulfill_metrics_on_success() -> None:
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task("what is 1 + 1"))
    assert result.ok is True
    assert result.metrics == {"deterministic": True, "fulfilled": True}
    assert result.error == ""


def test_fulfill_metrics_on_failure() -> None:
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task("write a poem"))
    assert result.ok is False
    assert result.metrics == {"deterministic": True, "fulfilled": False}
    assert result.output == ""


def test_fail_flag_metrics() -> None:
    backend = DeterministicBackend(fail=True)
    result = backend.execute(_task("anything"))
    assert result.ok is False
    assert result.metrics == {"deterministic": True}


def test_fulfill_file_listing(tmp_path) -> None:
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task(f"list the files in {tmp_path}"))
    assert result.ok is True
    assert result.output == "a.txt\nb.txt"
    assert result.metrics["fulfilled"] is True


def test_fulfill_file_listing_missing_dir() -> None:
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task("list the files in /nonexistent-dir-xyz-123"))
    assert result.ok is False
    assert UNFULFILLED_ERROR in result.error
    assert "not found" in result.error


def test_fulfill_file_listing_not_a_dir(tmp_path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("x")
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task(f"list the files in {f}"))
    assert result.ok is False
    assert UNFULFILLED_ERROR in result.error


def test_fulfill_arithmetic() -> None:
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task("what is 2 + 3 * 4"))
    assert result.ok is True
    assert result.output == "14"


def test_fulfill_arithmetic_float() -> None:
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task("calculate 7 / 2"))
    assert result.ok is True
    assert result.output == "3.5"


def test_fulfill_arithmetic_parens() -> None:
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task("compute (2 + 3) * 4"))
    assert result.ok is True
    assert result.output == "20"


def test_fulfill_arithmetic_invalid_expression() -> None:
    """Expression matching the regex but failing safe eval is honestly rejected."""
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task("what is ("))
    assert result.ok is False
    assert UNFULFILLED_ERROR in result.error


def test_fulfill_list_oserror() -> None:
    """OSError (e.g. permission denied) during listing is honestly reported."""
    from unittest.mock import patch

    backend = DeterministicBackend(fulfill=True)
    with patch("os.listdir", side_effect=OSError("permission denied")):
        result = backend.execute(_task("list the files in /some/dir"))
    assert result.ok is False
    assert UNFULFILLED_ERROR in result.error
    assert "cannot list directory" in result.error


def test_fulfill_unfulfillable_is_honest() -> None:
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task("write a poem about the ocean"))
    assert result.ok is False
    assert result.output == ""
    assert result.error.startswith(UNFULFILLED_ERROR)
    assert "no LLM provider configured" in result.error
    assert result.metrics["fulfilled"] is False


def test_fulfill_empty_objective() -> None:
    backend = DeterministicBackend(fulfill=True)
    result = backend.execute(_task("   "))
    assert result.ok is False
    assert UNFULFILLED_ERROR in result.error


def test_fulfill_respects_fail_flag() -> None:
    backend = DeterministicBackend(fulfill=True, fail=True)
    result = backend.execute(_task("what is 1 + 1"))
    assert result.ok is False
    assert result.error == "deterministic failure"


def test_fulfill_custom_output_not_overridden() -> None:
    """When a custom output is configured, fulfill mode does not interfere."""
    backend = DeterministicBackend(fulfill=True, output="custom")
    result = backend.execute(_task("what is 1 + 1"))
    assert result.ok is True
    assert result.output == "custom"


def test_safe_eval_arithmetic_basic() -> None:
    assert _safe_eval_arithmetic("2 + 3") == 5.0
    assert _safe_eval_arithmetic("10 - 4") == 6.0
    assert _safe_eval_arithmetic("3 * 7") == 21.0
    assert _safe_eval_arithmetic("8 / 2") == 4.0
    assert _safe_eval_arithmetic("2 ** 3") == 8.0
    assert _safe_eval_arithmetic("-5") == -5.0


def test_safe_eval_arithmetic_rejects_unsafe() -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        _safe_eval_arithmetic("__import__('os').system('x')")
    with pytest.raises(ValueError, match="Unsafe"):
        _safe_eval_arithmetic("[1, 2, 3]")
    with pytest.raises(ValueError, match="Invalid arithmetic"):
        _safe_eval_arithmetic("2 +")


def test_kernel_default_passes_fulfill_flag() -> None:
    from ghostchimera.chimera_pilot import ChimeraPilotKernel

    kernel = ChimeraPilotKernel.default(
        include_deterministic_backend=True,
        deterministic_fulfill=True,
        include_model_provider_backend=False,
    )
    backends = kernel.registry.list()
    det = [b for b in backends if b.id == "deterministic.local"]
    assert len(det) == 1
    assert det[0]._fulfill is True


def test_kernel_default_fulfill_defaults_false() -> None:
    from ghostchimera.chimera_pilot import ChimeraPilotKernel

    kernel = ChimeraPilotKernel.default(
        include_deterministic_backend=True,
        include_model_provider_backend=False,
    )
    backends = kernel.registry.list()
    det = [b for b in backends if b.id == "deterministic.local"]
    assert len(det) == 1
    assert det[0]._fulfill is False
