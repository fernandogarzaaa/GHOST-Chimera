"""Optional llama.cpp/GGUF runtime adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .local_profiles import LocalModelProfile, get_local_model_profile


class LlamaCppRuntime:
    """Lazy wrapper around ``llama_cpp.Llama``."""

    def __init__(
        self,
        *,
        model_path: str,
        profile_name: str = "tiny",
        n_gpu_layers: int = 0,
    ) -> None:
        self.model_path = str(Path(model_path).expanduser()) if model_path else ""
        self.profile: LocalModelProfile = get_local_model_profile(profile_name)
        self.n_gpu_layers = int(n_gpu_layers)
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
        model = self._load_model()
        response = model.create_chat_completion(
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            temperature=0.0,
        )
        return self._extract_text(response)

    def _load_model(self):
        if self._model is None:
            from llama_cpp import Llama  # type: ignore

            self._model = Llama(
                model_path=self.model_path,
                n_ctx=self.profile.max_context_tokens,
                n_gpu_layers=self.n_gpu_layers,
                verbose=False,
            )
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
