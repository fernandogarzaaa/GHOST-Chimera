"""Tests for test-time compute in the model provider backend."""

from __future__ import annotations

import itertools

from ghostchimera.chimera_pilot.backends.model_provider import ModelProviderBackend
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec


class _FakeProvider:
    def __init__(self, answers):
        self._it = itertools.cycle(answers)
        self.calls = 0
        self.model = "fake-model"
        self.available = True

    def validate_config(self):
        return []

    def chat(self, system, prompt):
        self.calls += 1
        return next(self._it)


def _backend(answers) -> ModelProviderBackend:
    backend = ModelProviderBackend(provider_name="local")
    backend.provider = _FakeProvider(answers)
    return backend


def test_single_shot_when_no_test_time_constraint():
    backend = _backend(["only answer"])
    task = TaskSpec.create(kind=TaskKind.REASONING, objective="q", inputs={"prompt": "q"})
    result = backend.execute(task)
    assert result.ok
    assert result.output == "only answer"
    assert backend.provider.calls == 1
    assert "test_time_samples" not in result.metrics


def test_test_time_samples_selects_majority():
    backend = _backend(["42", "42", "7", "42", "7"])
    task = TaskSpec.create(
        kind=TaskKind.REASONING,
        objective="q",
        inputs={"prompt": "q"},
        constraints={"test_time_samples": 5},
    )
    result = backend.execute(task)
    assert result.ok
    assert result.output == "42"
    assert backend.provider.calls == 5
    assert result.metrics["test_time_samples"] == 5
    assert result.metrics["strategy"] == "self_consistency"
    assert result.metrics["vote_share"] == 0.6
