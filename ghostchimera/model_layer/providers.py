"""
Provider registry for model backends.

Ghost Chimera supports multiple model backends behind a small provider
interface. Users select the provider with ``GHOSTCHIMERA_MODEL_PROVIDER`` or by
passing a provider name to ``ghostchimera.model_layer.llm.LLM``.

Credential injection (OpenClaw-style)
--------------------------------------
Providers accept an optional :class:`~ghostchimera.model_layer.auth_profiles.AuthProfile`
at construction time.  When no profile is supplied the provider falls back to
reading the relevant environment variables directly, preserving backward
compatibility.  The :class:`~ghostchimera.chimera_pilot.credential_pool.CredentialPool`
builds an ``AuthProfile`` from a ``CredentialEntry`` and passes it in, making
the pool the single authoritative credential source.
"""

from __future__ import annotations

import json
import os
import ssl
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from urllib import request as urllib_request

from ..logging_config import get_logger
from .llamacpp_runtime import LlamaCppRuntime
from .local_profiles import get_local_model_profile

if TYPE_CHECKING:
    from .auth_profiles import AuthProfile

logger = get_logger("providers")


class BaseProvider(ABC):
    """Abstract base class for model providers."""

    name: str = "base"
    available: bool = False

    @abstractmethod
    def chat(self, system_message: str, user_message: str) -> str:
        """Return a chat completion for the provided system and user messages."""

    def validate_config(self) -> list[str]:
        """Return a list of configuration error strings.

        An empty list means the provider is configured correctly.
        Subclasses override this to add provider-specific checks.
        """
        return []


class OpenAIProvider(BaseProvider):
    """Provider that connects to the OpenAI Chat Completion API."""

    name = "openai"

    def __init__(self, profile: AuthProfile | None = None) -> None:
        if profile is not None:
            self.api_key = profile.api_key or os.environ.get("OPENAI_API_KEY", "")
            self.model = profile.model or os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")
            self._base_url = profile.base_url or "https://api.openai.com/v1/chat/completions"
        else:
            self.api_key = os.environ.get("OPENAI_API_KEY", "")
            self.model = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")
            self._base_url = "https://api.openai.com/v1/chat/completions"
        self.available = bool(self.api_key)
        logger.debug("Provider %s initialized", self.name)

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.api_key:
            errors.append("OPENAI_API_KEY is not set")
        elif not self.api_key.startswith("sk-"):
            errors.append("OPENAI_API_KEY does not look like a valid OpenAI key (expected prefix 'sk-')")
        if not self.model:
            errors.append("OPENAI_MODEL must be non-empty")
        return errors

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
        req = urllib_request.Request(self._base_url, data=data, headers=headers, method="POST")
        with urllib_request.urlopen(req, context=context) as resp:
            if resp.status != 200:
                raise RuntimeError(f"OpenAI API returned HTTP {resp.status}")
            response_json = json.loads(resp.read().decode("utf-8"))
            choices = response_json.get("choices")
            if not choices:
                raise RuntimeError("OpenAI response missing choices")
            return choices[0]["message"]["content"].strip()


class AnthropicProvider(BaseProvider):
    """Provider that connects to the Anthropic Messages API.

    Supports Claude models via ``https://api.anthropic.com/v1/messages``.
    The API key is read from the ``ANTHROPIC_API_KEY`` environment variable or
    injected via an :class:`~ghostchimera.model_layer.auth_profiles.AuthProfile`.
    """

    name = "anthropic"
    _API_VERSION = "2023-06-01"
    _DEFAULT_MODEL = "claude-3-5-haiku-20241022"
    _DEFAULT_MAX_TOKENS = 1024

    def __init__(self, profile: AuthProfile | None = None) -> None:
        if profile is not None:
            self.api_key = profile.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            self.model = profile.model or os.environ.get("ANTHROPIC_MODEL", self._DEFAULT_MODEL)
            self._base_url = profile.base_url or "https://api.anthropic.com/v1/messages"
        else:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            self.model = os.environ.get("ANTHROPIC_MODEL", self._DEFAULT_MODEL)
            self._base_url = "https://api.anthropic.com/v1/messages"
        self.available = bool(self.api_key)
        logger.debug("Provider %s initialized", self.name)

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.api_key:
            errors.append("ANTHROPIC_API_KEY is not set")
        if not self.model:
            errors.append("ANTHROPIC_MODEL must be non-empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
        }

    def chat(self, system_message: str, user_message: str) -> str:
        if not self.available:
            raise RuntimeError("AnthropicProvider is not available; set ANTHROPIC_API_KEY in the environment")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self._API_VERSION,
        }
        body = {
            "model": self.model,
            "max_tokens": self._DEFAULT_MAX_TOKENS,
            "system": system_message,
            "messages": [
                {"role": "user", "content": user_message},
            ],
        }
        data = json.dumps(body).encode("utf-8")
        context = ssl.create_default_context()
        req = urllib_request.Request(self._base_url, data=data, headers=headers, method="POST")
        with urllib_request.urlopen(req, context=context) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Anthropic API returned HTTP {resp.status}")
            response_json = json.loads(resp.read().decode("utf-8"))
            content = response_json.get("content")
            if not content:
                raise RuntimeError("Anthropic response missing content")
            return content[0]["text"].strip()


class MinimindProvider(BaseProvider):
    """Provider for local minimind-compatible runtimes."""

    name = "minimind"

    def __init__(self, profile: AuthProfile | None = None) -> None:
        profile_name = (
            (profile.model if profile and profile.model else None)
            or os.environ.get("MINIMIND_MODEL_PROFILE", "tiny")
        )
        self.profile = get_local_model_profile(profile_name)
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

    def validate_config(self) -> list[str]:
        if not self.available:
            return ["minimind package is not installed or no compatible runtime was found"]
        return []

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

    def __init__(self, profile: AuthProfile | None = None) -> None:
        model_path = (profile.base_url if profile and profile.base_url else None) or os.environ.get("LLAMACPP_MODEL_PATH", "")
        profile_name = (profile.model if profile and profile.model else None) or os.environ.get("LLAMACPP_MODEL_PROFILE", "tiny")
        self.runtime = LlamaCppRuntime(
            model_path=model_path,
            profile_name=profile_name,
            n_gpu_layers=int(os.environ.get("LLAMACPP_N_GPU_LAYERS", "0")),
        )
        self.available = self.runtime.available
        logger.debug("Provider %s initialized", self.name)

    def validate_config(self) -> list[str]:
        if not self.available:
            return ["llama-cpp-python is not installed or no model path was set (LLAMACPP_MODEL_PATH)"]
        return []

    def chat(self, system_message: str, user_message: str) -> str:
        return self.runtime.chat(system_message, user_message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
        }


PROVIDERS: dict[str, type[BaseProvider]] = {
    AnthropicProvider.name: AnthropicProvider,
    LlamaCppProvider.name: LlamaCppProvider,
    OpenAIProvider.name: OpenAIProvider,
    MinimindProvider.name: MinimindProvider,
}

# Split registry by provider type — enables typed lookup for media providers
TEXT_PROVIDERS: dict[str, type[BaseProvider]] = {
    AnthropicProvider.name: AnthropicProvider,
    LlamaCppProvider.name: LlamaCppProvider,
    OpenAIProvider.name: OpenAIProvider,
    MinimindProvider.name: MinimindProvider,
}


def get_provider(name: str, profile: AuthProfile | None = None) -> BaseProvider | None:
    """Instantiate and return a provider by name, or None if unknown.

    Parameters
    ----------
    name:
        Provider name, e.g. ``"openai"`` or ``"anthropic"``.
    profile:
        Optional :class:`~ghostchimera.model_layer.auth_profiles.AuthProfile`
        to inject credentials at construction time.  When ``None`` the provider
        falls back to environment variables.
    """
    cls = PROVIDERS.get(name)
    if cls is None:
        return None
    try:
        return cls(profile)
    except TypeError:
        return cls()


def register_text_provider(name: str, cls: type[BaseProvider]) -> None:
    """Register a custom text provider class at runtime.

    Parameters
    ----------
    name:
        Provider identifier (e.g. ``"my_llm"``).
    cls:
        Provider class — must subclass :class:`BaseProvider`.
    """
    PROVIDERS[name] = cls
    TEXT_PROVIDERS[name] = cls
    logger.debug("Registered text provider '%s'", name)
