"""Chimera Pilot backend that routes reasoning through the active model provider."""

from __future__ import annotations

import os
from typing import Any

from ...logging_config import get_logger
from ...model_layer.providers import BaseProvider, get_provider
from ...model_layer.test_time_compute import self_consistency
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult

logger = get_logger("model_provider_backend")

_LOCAL_PROVIDER_NAMES = {"llamacpp", "ollama", "lmstudio", "minimind", "local"}


class ModelProviderBackend:
    """Run reasoning tasks through Ghost Chimera's configured model provider."""

    name = "Ghost Model Provider"
    _description = "Configured LLM provider backend for live operator runs"

    def __init__(self, provider_name: str | None = None, *, profile: Any | None = None) -> None:
        self.provider_name = (provider_name or os.environ.get("GHOSTCHIMERA_MODEL_PROVIDER") or "openai").strip().lower()
        self.provider: BaseProvider | None = get_provider(self.provider_name, profile=profile)
        model = getattr(self.provider, "model", "") if self.provider is not None else ""
        self.model = str(model or os.environ.get("GHOSTCHIMERA_MODEL", "") or "default")
        self.id = f"{self.provider_name}.{self.model}".replace("/", "-")
        supports_network = self.provider_name not in _LOCAL_PROVIDER_NAMES
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.REASONING, TaskKind.LONG_CONTEXT_DOC, TaskKind.RAG_QUERY},
            supports_offline=not supports_network,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=supports_network,
            max_context_tokens=128_000,
            metadata={"provider": self.provider_name, "model": self.model},
        )

    def probe(self) -> BackendHealth:
        if self.provider is None:
            return BackendHealth(
                available=False,
                reliability=0.0,
                latency_ms=0,
                last_error=f"Unknown provider: {self.provider_name}",
            )
        errors = self.provider.validate_config()
        available = bool(self.provider.available) and not errors
        return BackendHealth(
            available=available,
            reliability=0.96 if available else 0.0,
            latency_ms=900 if self.capabilities.supports_network else 350,
            estimated_cost_usd=0.0,
            last_error="; ".join(errors) if errors else None,
            metadata={"provider": self.provider_name, "model": self.model},
        )

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task) and self.probe().available

    def estimate(self, task: TaskSpec) -> BackendHealth:
        return self.probe()

    def execute(self, task: TaskSpec) -> ExecutionResult:
        health = self.probe()
        if self.provider is None or not health.available:
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output="",
                error=health.last_error or "Model provider is unavailable.",
                metrics={"provider": self.provider_name, "model": self.model},
            )
        system = str(
            task.inputs.get("system")
            or "You are Ghost Chimera's live operator model. Answer the objective with clear, human-readable output. "
            "Report what you can and cannot do; do not pretend work happened."
        )
        prompt = str(task.inputs.get("prompt") or task.inputs.get("query") or task.objective)
        samples = max(1, int(task.constraints.get("test_time_samples", 1)))
        metrics: dict[str, Any] = {"provider": self.provider_name, "model": self.model, "kind": task.kind.value}
        try:
            if samples > 1:
                # Test-time compute: sample N candidates and take the majority
                # answer (self-consistency). A small local model that "thinks
                # longer" this way can beat a single-pass larger model.
                result = self_consistency(lambda p: self.provider.chat(system, p), prompt, n=samples)
                output = result.answer
                metrics.update(
                    test_time_samples=samples,
                    strategy=result.strategy,
                    vote_share=round(result.vote_share, 4),
                )
            else:
                output = self.provider.chat(system, prompt)
        except Exception as exc:
            logger.warning("Model provider backend failed: %s", exc)
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output="",
                error=str(exc),
                metrics={"provider": self.provider_name, "model": self.model},
            )
        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=True,
            output=output,
            metrics=metrics,
        )


__all__ = ["ModelProviderBackend"]
