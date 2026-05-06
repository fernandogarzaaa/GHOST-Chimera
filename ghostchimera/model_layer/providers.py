"""
Provider registry for model backends.

Ghost Chimera supports multiple model backends behind a small provider
interface. Users select the provider with ``GHOSTCHIMERA_MODEL_PROVIDER`` or by
passing a provider name to ``ghostchimera.model_layer.llm.LLM``.
"""

from __future__ import annotations

import json
import os
import ssl
from abc import ABC, abstractmethod
from typing import Any
from urllib import request as urllib_request

from ..logging_config import get_logger
from .llamacpp_runtime import LlamaCppRuntime
from .local_profiles import get_local_model_profile

logger = get_logger("providers")


class BaseProvider(ABC):
    """Abstract base class for model providers."""

    name: str = "base"
    available: bool = False

    @abstractmethod
    def chat(self, system_message: str, user_message: str) -> str:
        """Return a chat completion for the provided system and user messages."""


class OpenAIProvider(BaseProvider):
    """Provider that connects to the OpenAI Chat Completion API."""

    name = "openai"

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")
        self.available = bool(self.api_key)
        logger.debug("Provider %s initialized", self.name)

    @staticmethod
    def _sanitize_key(key: str) -> str:
        """Return a masked version of the key to prevent accidental leakage."""
        if not key or len(key) <= 4:
            return "***"
        return key[:4] + "****"

    def to_dict(self) -> dict[str, Any]:
        """Return provider config without exposing the API key."""
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
        }

    def chat(self, system_message: str, user_message: str) -> str:
        if not self.available:
            raise RuntimeError("OpenAIProvider is not available; set OPENAI_API_KEY in the environment")
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.0,
        }
        data = json.dumps(body).encode("utf-8")
        context = ssl.create_default_context()
        req = urllib_request.Request(url, data=data, headers=headers, method="POST")
        with urllib_request.urlopen(req, context=context) as resp:
            if resp.status != 200:
                raise RuntimeError(f"OpenAI API returned HTTP {resp.status}")
            response_json = json.loads(resp.read().decode("utf-8"))
            choices = response_json.get("choices")
            if not choices:
                raise RuntimeError("OpenAI response missing choices")
            return choices[0]["message"]["content"].strip()


class MinimindProvider(BaseProvider):
    """Provider for local minimind-compatible runtimes."""

    name = "minimind"

    def __init__(self) -> None:
        self.profile = get_local_model_profile(os.environ.get("MINIMIND_MODEL_PROFILE", "tiny"))
        try:
            import minimind  # type: ignore

            self.mm = minimind
            self.runtime = self._load_runtime(minimind)
            self.available = self.runtime is not None
        except Exception:
            self.mm = None
            self.runtime = None
            self.available = False
        logger.debug("Provider %s initialized", self.name)

    def chat(self, system_message: str, user_message: str) -> str:
        if not self.available:
            raise RuntimeError("MinimindProvider is not available; minimind is not installed or no runtime loaded")
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
        if hasattr(self.runtime, "chat"):
            return self.runtime.chat(messages, max_context_tokens=self.profile.max_context_tokens)
        if hasattr(self.runtime, "llm_chat"):
            return self.runtime.llm_chat(system_message, user_message)
        raise RuntimeError("Minimind runtime is loaded but no supported chat interface was found")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "profile": self.profile.name,
        }

    def _load_runtime(self, minimind_module: Any) -> Any:
        profile = self.profile.to_dict()
        if hasattr(minimind_module, "load_model"):
            return minimind_module.load_model(profile)
        if hasattr(minimind_module, "create_chat_model"):
            return minimind_module.create_chat_model(profile)
        if hasattr(minimind_module, "llm_chat"):
            return minimind_module
        return None


class LlamaCppProvider(BaseProvider):
    """Provider for optional llama.cpp/GGUF local inference."""

    name = "llamacpp"

    def __init__(self) -> None:
        self.runtime = LlamaCppRuntime(
            model_path=os.environ.get("LLAMACPP_MODEL_PATH", ""),
            profile_name=os.environ.get("LLAMACPP_MODEL_PROFILE", "tiny"),
            n_gpu_layers=int(os.environ.get("LLAMACPP_N_GPU_LAYERS", "0")),
        )
        self.available = self.runtime.available
        logger.debug("Provider %s initialized", self.name)

    def chat(self, system_message: str, user_message: str) -> str:
        return self.runtime.chat(system_message, user_message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
        }


PROVIDERS: dict[str, type[BaseProvider]] = {
    LlamaCppProvider.name: LlamaCppProvider,
    OpenAIProvider.name: OpenAIProvider,
    MinimindProvider.name: MinimindProvider,
}


def get_provider(name: str) -> BaseProvider | None:
    """Instantiate and return a provider by name, or None if unknown."""

    cls = PROVIDERS.get(name)
    if cls is None:
        return None
    return cls()
