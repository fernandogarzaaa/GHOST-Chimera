"""Optional llama.cpp backend for local reasoning."""

from __future__ import annotations

from ...logging_config import get_logger
from ...model_layer.llamacpp_runtime import LlamaCppRuntime
from ...model_layer.local_profiles import get_local_model_profile
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult

logger = get_logger("llamacpp")


class LlamaCppBackend:
    """Run reasoning tasks through a local GGUF model when configured."""

    id = "llamacpp.local"
    name = "llama.cpp Local GGUF Runtime"
    _description = "Local GGUF model backend via llama.cpp"

    def __init__(
        self,
        *,
        model_path: str,
        profile_name: str = "tiny",
        n_gpu_layers: int = 0,
    ) -> None:
        self.profile = get_local_model_profile(profile_name)
        logger.debug("Provider %s initialized", self.name)
        self.runtime = LlamaCppRuntime(
            model_path=model_path,
            profile_name=profile_name,
            n_gpu_layers=n_gpu_layers,
        )
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.REASONING},
            supports_offline=True,
            supports_streaming=False,
            supports_gpu=n_gpu_layers > 0,
            supports_network=False,
            max_context_tokens=self.profile.max_context_tokens,
            metadata=self.profile.to_dict(),
        )

    def probe(self) -> BackendHealth:
        error = self.runtime.available_error()
        if error:
            return BackendHealth(
                available=False,
                reliability=0.0,
                latency_ms=999_999,
                estimated_cost_usd=0.0,
                last_error=error,
            )
        return BackendHealth(available=True, reliability=0.85, latency_ms=250, estimated_cost_usd=0.0)

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        return self.probe()

    def execute(self, task: TaskSpec) -> ExecutionResult:
        try:
            output = self.runtime.chat(
                "You are Ghost Chimera running locally. Answer concisely.",
                str(task.inputs.get("prompt") or task.objective),
            )
        except Exception as exc:
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output="",
                error=str(exc),
                metrics={"profile": self.profile.name},
            )
        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=True,
            output=output,
            metrics={"profile": self.profile.name, "runtime": "llama_cpp"},
        )


