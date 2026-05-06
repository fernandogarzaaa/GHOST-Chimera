"""Optional llama.cpp/GGUF runtime adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .local_profiles import LocalModelProfile, get_local_model_profile
from .runtime_specialization import (
    RuntimeEnvironment,
    RuntimeSpecializationPlan,
    detect_runtime_environment,
    plan_runtime_specialization,
    workload_from_messages,
)


class LlamaCppRuntime:
    """Lazy wrapper around ``llama_cpp.Llama``."""

    def __init__(
        self,
        *,
        model_path: str,
        profile_name: str = "tiny",
        n_gpu_layers: int = 0,
        runtime_specialization: bool = True,
        specialization_cache_dir: str | None = None,
        gpu_architecture: str | None = None,
        gpu_sm_count: int | None = None,
    ) -> None:
        self.model_path = str(Path(model_path).expanduser()) if model_path else ""
        self.profile: LocalModelProfile = get_local_model_profile(profile_name)
        self.n_gpu_layers = int(n_gpu_layers)
        self.runtime_specialization = bool(runtime_specialization)
        self.specialization_cache_dir = specialization_cache_dir
        self.environment: RuntimeEnvironment = detect_runtime_environment(
            n_gpu_layers=self.n_gpu_layers,
            architecture=gpu_architecture,
            sm_count=gpu_sm_count,
        )
        self.last_specialization_plan: RuntimeSpecializationPlan | None = None
        self._model: Any | None = None

    def available_error(self) -> str | None:
        if not self.model_path:
            return "llama.cpp model path is required"
        if not Path(self.model_path).exists():
            return f"llama.cpp model path does not exist: {self.model_path}"
        try:
            import llama_cpp  # type: ignore  # noqa: F401
        except Exception as exc:
            return f"llama_cpp is not installed: {exc}"
        return None

    @property
    def available(self) -> bool:
        return self.available_error() is None

    def chat(self, system_message: str, user_message: str) -> str:
        error = self.available_error()
        if error:
            raise RuntimeError(error)
        plan = self._plan_for_messages(system_message, user_message)
        model = self._load_model(plan)
        response = model.create_chat_completion(
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            temperature=0.0,
        )
        return self._extract_text(response)

    def _plan_for_messages(self, system_message: str, user_message: str) -> RuntimeSpecializationPlan | None:
        if not self.runtime_specialization:
            self.last_specialization_plan = None
            return None
        workload = workload_from_messages(
            system_message=system_message,
            user_message=user_message,
            dtype=self.profile.quantization,
        )
        self.last_specialization_plan = plan_runtime_specialization(
            profile=self.profile,
            workload=workload,
            environment=self.environment,
            cache_dir=self.specialization_cache_dir,
        )
        return self.last_specialization_plan

    def _load_model(self, plan: RuntimeSpecializationPlan | None = None):
        if self._model is None:
            from llama_cpp import Llama  # type: ignore

            kwargs: dict[str, Any] = {
                "model_path": self.model_path,
                "n_ctx": self.profile.max_context_tokens,
                "n_gpu_layers": self.n_gpu_layers,
                "verbose": False,
            }
            if plan is not None:
                kwargs["n_batch"] = plan.llama_cpp_n_batch
            self._model = Llama(**kwargs)
        return self._model

    def _extract_text(self, response: Any) -> str:
        choices = response.get("choices") if isinstance(response, dict) else None
        if not choices:
            raise RuntimeError("llama.cpp response missing choices")
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise RuntimeError("llama.cpp response missing message content")
        return str(content)
