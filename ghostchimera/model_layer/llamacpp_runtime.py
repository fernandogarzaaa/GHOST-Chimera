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

# ggml type enum values (stable across llama.cpp) used for KV-cache quantization.
# Mapping the friendly name to the int keeps this module import-free until load.
_GGML_KV_TYPES: dict[str, int] = {
    "f16": 1,
    "f32": 0,
    "q8_0": 8,
    "q5_1": 7,
    "q5_0": 6,
    "q4_1": 3,
    "q4_0": 2,
}


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
        kv_cache_type: str | None = None,
        n_ctx_override: int | None = None,
        speculative_lookahead: int = 0,
        default_temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        self.model_path = str(Path(model_path).expanduser()) if model_path else ""
        self.profile: LocalModelProfile = get_local_model_profile(profile_name)
        self.n_gpu_layers = int(n_gpu_layers)
        self.runtime_specialization = bool(runtime_specialization)
        self.specialization_cache_dir = specialization_cache_dir
        # KV-cache quantization: the single highest-impact knob for tight VRAM.
        # Falls back to the profile's recommendation when not explicitly set.
        self.kv_cache_type = self._normalize_kv_cache_type(
            kv_cache_type if kv_cache_type is not None else self.profile.recommended_kv_cache_type
        )
        self.n_ctx_override = int(n_ctx_override) if n_ctx_override else None
        # Prompt-lookup speculative decoding needs no second model — ideal on edge.
        self.speculative_lookahead = max(0, int(speculative_lookahead))
        self.default_temperature = float(
            default_temperature if default_temperature is not None else self.profile.recommended_temperature
        )
        # Thinking/output budget: reasoning models (e.g. Qwen3-Thinking) need room.
        self.max_output_tokens = int(max_output_tokens) if max_output_tokens else None
        self.environment: RuntimeEnvironment = detect_runtime_environment(
            n_gpu_layers=self.n_gpu_layers,
            architecture=gpu_architecture,
            sm_count=gpu_sm_count,
        )
        self.last_specialization_plan: RuntimeSpecializationPlan | None = None
        self._model: Any | None = None

    @staticmethod
    def _normalize_kv_cache_type(value: str | None) -> str | None:
        if not value:
            return None
        key = str(value).strip().lower()
        if key not in _GGML_KV_TYPES:
            raise ValueError(f"unsupported kv_cache_type {value!r}; choose from {sorted(_GGML_KV_TYPES)}")
        return key

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

    def chat(
        self,
        system_message: str,
        user_message: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        error = self.available_error()
        if error:
            raise RuntimeError(error)
        plan = self._plan_for_messages(system_message, user_message)
        model = self._load_model(plan)
        completion_kwargs: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            "temperature": self.default_temperature if temperature is None else float(temperature),
        }
        budget = max_tokens if max_tokens is not None else self.max_output_tokens
        if budget:
            completion_kwargs["max_tokens"] = int(budget)
        response = model.create_chat_completion(**completion_kwargs)
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

    def build_load_kwargs(self, plan: RuntimeSpecializationPlan | None = None) -> dict[str, Any]:
        """Assemble ``llama_cpp.Llama`` constructor kwargs (pure / testable).

        New tuning knobs are only emitted when explicitly configured, so the
        default kwargs remain identical to the original runtime.
        """

        kwargs: dict[str, Any] = {
            "model_path": self.model_path,
            "n_ctx": self.n_ctx_override or self.profile.max_context_tokens,
            "n_gpu_layers": self.n_gpu_layers,
            "verbose": False,
        }
        if plan is not None:
            kwargs["n_batch"] = plan.llama_cpp_n_batch
        if self.kv_cache_type is not None:
            ggml_type = _GGML_KV_TYPES[self.kv_cache_type]
            kwargs["type_k"] = ggml_type
            kwargs["type_v"] = ggml_type
        return kwargs

    def _make_draft_model(self) -> Any | None:
        """Construct a prompt-lookup speculative drafter when enabled and available."""

        if self.speculative_lookahead <= 0:
            return None
        try:
            from llama_cpp import LlamaPromptLookupDecoding  # type: ignore
        except Exception:
            return None
        return LlamaPromptLookupDecoding(num_pred_tokens=self.speculative_lookahead)

    def _load_model(self, plan: RuntimeSpecializationPlan | None = None):
        if self._model is None:
            from llama_cpp import Llama  # type: ignore

            kwargs = self.build_load_kwargs(plan)
            draft_model = self._make_draft_model()
            if draft_model is not None:
                kwargs["draft_model"] = draft_model
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
