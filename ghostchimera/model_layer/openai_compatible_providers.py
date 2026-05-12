"""Extended model provider implementations for Ghost Chimera.

This module contains providers beyond the core OpenAI / Anthropic / Gemini trio,
reverse-engineered from the OpenClaw provider directory and adapted to match the
Ghost Chimera :class:`~ghostchimera.model_layer.providers.BaseProvider` contract.

All providers:
- Accept an optional :class:`~ghostchimera.model_layer.auth_profiles.AuthProfile`
  at construction time and fall back to environment variables.
- Use only the Python standard-library ``urllib`` package — no extra dependencies.
- Expose ``chat(system, user) → str``, ``validate_config() → list[str]``,
  and ``to_dict() → dict``.

Provider overview
-----------------
OpenAI-compatible (same HTTP request shape as OpenAI, different base URL + key):

    GroqProvider       — https://api.groq.com/openai/v1/chat/completions
    XAIProvider        — https://api.x.ai/v1/chat/completions  (xAI / Grok)
    MistralProvider    — https://api.mistral.ai/v1/chat/completions
    DeepSeekProvider   — https://api.deepseek.com/v1/chat/completions
    TogetherProvider   — https://api.together.xyz/v1/chat/completions
    OpenRouterProvider — https://openrouter.ai/api/v1/chat/completions
    OllamaProvider     — http://localhost:11434/v1/chat/completions  (local, no key)

Custom API:

    CohereProvider     — https://api.cohere.com/v2/chat  (Cohere v2 format)
"""

from __future__ import annotations

import json
import os
import ssl
from typing import TYPE_CHECKING, Any
from urllib import request as urllib_request

from ..logging_config import get_logger
from .base_provider import BaseProvider

if TYPE_CHECKING:
    from .auth_profiles import AuthProfile

logger = get_logger("openai_compatible_providers")


# ---------------------------------------------------------------------------
# Generic OpenAI-compatible base
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(BaseProvider):
    """Generic base for providers that expose an OpenAI-compatible Chat API.

    Subclasses override :attr:`name`, :attr:`_DEFAULT_BASE_URL`,
    :attr:`_DEFAULT_MODEL`, :attr:`_KEY_ENV_VAR`, and :attr:`_MODEL_ENV_VAR`.
    They may also override :meth:`_build_headers` to inject extra headers.
    """

    name: str = "openai_compat"
    _DEFAULT_BASE_URL: str = ""
    _DEFAULT_MODEL: str = ""
    _KEY_ENV_VAR: str = ""
    _MODEL_ENV_VAR: str = ""

    def __init__(self, profile: AuthProfile | None = None) -> None:
        if profile is not None:
            self.api_key: str = profile.api_key or os.environ.get(self._KEY_ENV_VAR, "")
            self.model: str = profile.model or os.environ.get(self._MODEL_ENV_VAR, self._DEFAULT_MODEL)
            self._base_url: str = profile.base_url or self._DEFAULT_BASE_URL
        else:
            self.api_key = os.environ.get(self._KEY_ENV_VAR, "")
            self.model = os.environ.get(self._MODEL_ENV_VAR, self._DEFAULT_MODEL)
            self._base_url = self._DEFAULT_BASE_URL
        self.available = bool(self.api_key)
        logger.debug("Provider %s model=%s initialized", self.name, self.model)

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.api_key:
            errors.append(f"{self._KEY_ENV_VAR} is not set")
        if not self.model:
            errors.append(f"{self._MODEL_ENV_VAR} must be non-empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
        }

    def _build_headers(self) -> dict[str, str]:
        """Return HTTP headers for this provider.  Subclasses may extend."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def chat(self, system_message: str, user_message: str) -> str:
        if not self.available:
            raise RuntimeError(
                f"{self.__class__.__name__} is not available; set {self._KEY_ENV_VAR} in the environment"
            )
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.0,
        }
        data = json.dumps(body).encode("utf-8")
        context = ssl.create_default_context()
        req = urllib_request.Request(
            self._base_url,
            data=data,
            headers=self._build_headers(),
            method="POST",
        )
        with urllib_request.urlopen(req, context=context) as resp:
            if resp.status != 200:
                raise RuntimeError(f"{self.name} API returned HTTP {resp.status}")
            response_json = json.loads(resp.read().decode("utf-8"))
        choices = response_json.get("choices")
        if not choices:
            raise RuntimeError(f"{self.name} response missing choices")
        return choices[0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Tier-1 OpenAI-compatible providers
# ---------------------------------------------------------------------------


class GroqProvider(OpenAICompatibleProvider):
    """Provider for Groq LPU inference.

    Groq exposes an OpenAI-compatible endpoint with extremely low latency.
    Set ``GROQ_API_KEY`` (from https://console.groq.com) and optionally
    ``GROQ_MODEL`` in the environment, or inject an
    :class:`~ghostchimera.model_layer.auth_profiles.AuthProfile`.

    Supported models (examples)::

        llama-3.3-70b-versatile   # default — high quality, fast
        llama-3.1-8b-instant      # fastest, smaller
        mixtral-8x7b-32768        # Mixtral via Groq
        gemma2-9b-it              # Google Gemma 2 9B via Groq
    """

    name = "groq"
    _DEFAULT_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
    _DEFAULT_MODEL = "llama-3.3-70b-versatile"
    _KEY_ENV_VAR = "GROQ_API_KEY"
    _MODEL_ENV_VAR = "GROQ_MODEL"


class XAIProvider(OpenAICompatibleProvider):
    """Provider for xAI (Grok) models.

    xAI exposes an OpenAI-compatible endpoint for the Grok model family.
    Set ``XAI_API_KEY`` (from https://console.x.ai) and optionally
    ``XAI_MODEL`` in the environment.

    Supported models (examples)::

        grok-3-mini               # default — fast, cost-effective
        grok-3                    # flagship Grok 3
        grok-2-1212               # previous generation
    """

    name = "xai"
    _DEFAULT_BASE_URL = "https://api.x.ai/v1/chat/completions"
    _DEFAULT_MODEL = "grok-3-mini"
    _KEY_ENV_VAR = "XAI_API_KEY"
    _MODEL_ENV_VAR = "XAI_MODEL"


class MistralProvider(OpenAICompatibleProvider):
    """Provider for Mistral AI models.

    Mistral exposes an OpenAI-compatible chat completions endpoint.
    Set ``MISTRAL_API_KEY`` (from https://console.mistral.ai) and optionally
    ``MISTRAL_MODEL`` in the environment.

    Supported models (examples)::

        mistral-small-latest      # default — fast, cheap
        mistral-large-latest      # largest, highest quality
        mixtral-8x7b-instruct     # open-weight Mixtral
        codestral-latest          # code-specialised
    """

    name = "mistral"
    _DEFAULT_BASE_URL = "https://api.mistral.ai/v1/chat/completions"
    _DEFAULT_MODEL = "mistral-small-latest"
    _KEY_ENV_VAR = "MISTRAL_API_KEY"
    _MODEL_ENV_VAR = "MISTRAL_MODEL"


class DeepSeekProvider(OpenAICompatibleProvider):
    """Provider for DeepSeek models.

    DeepSeek exposes an OpenAI-compatible API at a highly competitive price.
    Set ``DEEPSEEK_API_KEY`` (from https://platform.deepseek.com) and optionally
    ``DEEPSEEK_MODEL`` in the environment.

    Supported models (examples)::

        deepseek-chat             # default — fast general assistant
        deepseek-reasoner         # chain-of-thought reasoning (DeepSeek-R1)
    """

    name = "deepseek"
    _DEFAULT_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
    _DEFAULT_MODEL = "deepseek-chat"
    _KEY_ENV_VAR = "DEEPSEEK_API_KEY"
    _MODEL_ENV_VAR = "DEEPSEEK_MODEL"


class TogetherProvider(OpenAICompatibleProvider):
    """Provider for Together AI hosted open-source models.

    Together AI exposes an OpenAI-compatible endpoint for hundreds of
    open-weight models.  Set ``TOGETHER_API_KEY`` (from
    https://api.together.xyz) and optionally ``TOGETHER_MODEL``.

    Supported models (examples)::

        meta-llama/Llama-3-70b-chat-hf     # default — Llama 3 70B chat
        meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo
        mistralai/Mixtral-8x7B-Instruct-v0.1
        Qwen/Qwen2.5-72B-Instruct-Turbo
    """

    name = "together"
    _DEFAULT_BASE_URL = "https://api.together.xyz/v1/chat/completions"
    _DEFAULT_MODEL = "meta-llama/Llama-3-70b-chat-hf"
    _KEY_ENV_VAR = "TOGETHER_API_KEY"
    _MODEL_ENV_VAR = "TOGETHER_MODEL"


class OpenRouterProvider(OpenAICompatibleProvider):
    """Provider for OpenRouter — a gateway to 100+ models from many providers.

    OpenRouter routes requests to the best available model backend.
    Set ``OPENROUTER_API_KEY`` (from https://openrouter.ai) and optionally
    ``OPENROUTER_MODEL`` in the environment.

    OpenRouter requires two additional headers (``HTTP-Referer`` and
    ``X-Title``) to attribute usage to the calling application.

    Supported models (examples — any OpenRouter model slug works)::

        openai/gpt-4o-mini           # default
        anthropic/claude-3-5-haiku
        google/gemini-flash-1.5
        meta-llama/llama-3.3-70b-instruct
        mistralai/mistral-large
    """

    name = "openrouter"
    _DEFAULT_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
    _DEFAULT_MODEL = "openai/gpt-4o-mini"
    _KEY_ENV_VAR = "OPENROUTER_API_KEY"
    _MODEL_ENV_VAR = "OPENROUTER_MODEL"

    # Ghost Chimera identity headers sent to OpenRouter for usage attribution.
    _REFERER = "https://github.com/fernandogarzaaa/GHOST-Chimera"
    _TITLE = "Ghost Chimera"

    def _build_headers(self) -> dict[str, str]:
        headers = super()._build_headers()
        headers["HTTP-Referer"] = self._REFERER
        headers["X-Title"] = self._TITLE
        return headers


# ---------------------------------------------------------------------------
# Tier-2: Local Ollama provider (no API key)
# ---------------------------------------------------------------------------


class OllamaProvider(BaseProvider):
    """Provider for locally-running Ollama inference server.

    Ollama (https://ollama.ai) runs large language models locally and exposes
    an OpenAI-compatible ``/v1/chat/completions`` endpoint starting from
    v0.1.24.  No API key is required.

    Configuration
    -------------
    ``OLLAMA_BASE_URL`` — base URL of the Ollama server
        (default ``http://localhost:11434``).
    ``OLLAMA_MODEL`` — model tag to use (default ``llama3.2``).

    Install a model first::

        ollama pull llama3.2

    Supported models (any ``ollama pull <tag>`` model works)::

        llama3.2          # default — Meta Llama 3.2 3B
        llama3.1:70b
        mistral
        gemma3:12b
        deepseek-r1:7b
        qwen2.5:72b
    """

    name = "ollama"
    _DEFAULT_BASE_URL = "http://localhost:11434"
    _DEFAULT_MODEL = "llama3.2"

    def __init__(self, profile: AuthProfile | None = None) -> None:
        if profile is not None:
            base = profile.base_url or os.environ.get("OLLAMA_BASE_URL", self._DEFAULT_BASE_URL)
            self.model: str = profile.model or os.environ.get("OLLAMA_MODEL", self._DEFAULT_MODEL)
        else:
            base = os.environ.get("OLLAMA_BASE_URL", self._DEFAULT_BASE_URL)
            self.model = os.environ.get("OLLAMA_MODEL", self._DEFAULT_MODEL)
        # Normalise trailing slash
        self._base_url: str = base.rstrip("/")
        self._chat_url: str = f"{self._base_url}/v1/chat/completions"
        # Ollama is local — mark available by default because no API key is
        # needed.  ``available=True`` here means "no credential barrier", not
        # "server is currently reachable".  Use ``validate_config()`` to get a
        # reachability note before chat time.
        self.available = True
        logger.debug("Provider %s model=%s base=%s initialized", self.name, self.model, self._base_url)

    def validate_config(self) -> list[str]:
        notes: list[str] = []
        if not self.model:
            notes.append("OLLAMA_MODEL must be non-empty")
        # Lightweight reachability check — does not pull a model.
        try:
            context = ssl.create_default_context()
            tags_url = f"{self._base_url}/api/tags"
            req = urllib_request.Request(tags_url, method="GET")
            with urllib_request.urlopen(req, context=context, timeout=2):
                pass
        except Exception as exc:
            notes.append(
                f"Ollama server at {self._base_url} appears unreachable ({exc}). "
                "Start Ollama with `ollama serve` and pull a model with `ollama pull <model>`."
            )
        return notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
            "base_url": self._base_url,
        }

    def chat(self, system_message: str, user_message: str) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.0,
        }
        data = json.dumps(body).encode("utf-8")
        context = ssl.create_default_context()
        req = urllib_request.Request(
            self._chat_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, context=context) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Ollama API returned HTTP {resp.status}")
                response_json = json.loads(resp.read().decode("utf-8"))
        except OSError as exc:
            raise RuntimeError(
                f"OllamaProvider could not reach {self._chat_url}. "
                "Ensure Ollama is running (`ollama serve`) and the model is pulled."
            ) from exc
        choices = response_json.get("choices")
        if not choices:
            raise RuntimeError("Ollama response missing choices")
        return choices[0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Tier-3: Cohere provider (non-OpenAI API format)
# ---------------------------------------------------------------------------


class CohereProvider(BaseProvider):
    """Provider for Cohere language models.

    Cohere's v2 Chat API shares the ``messages`` list shape with OpenAI but
    uses a different response envelope.  Set ``COHERE_API_KEY`` (from
    https://dashboard.cohere.com) and optionally ``COHERE_MODEL``.

    API reference: https://docs.cohere.com/reference/chat

    Supported models (examples)::

        command-r-plus            # default — most capable
        command-r                 # balanced speed/quality
        command-light             # fastest, cheapest
    """

    name = "cohere"
    _API_URL = "https://api.cohere.com/v2/chat"
    _DEFAULT_MODEL = "command-r-plus"

    def __init__(self, profile: AuthProfile | None = None) -> None:
        if profile is not None:
            self.api_key: str = profile.api_key or os.environ.get("COHERE_API_KEY", "")
            self.model: str = profile.model or os.environ.get("COHERE_MODEL", self._DEFAULT_MODEL)
        else:
            self.api_key = os.environ.get("COHERE_API_KEY", "")
            self.model = os.environ.get("COHERE_MODEL", self._DEFAULT_MODEL)
        self.available = bool(self.api_key)
        logger.debug("Provider %s model=%s initialized", self.name, self.model)

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.api_key:
            errors.append("COHERE_API_KEY is not set")
        if not self.model:
            errors.append("COHERE_MODEL must be non-empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
        }

    def chat(self, system_message: str, user_message: str) -> str:
        if not self.available:
            raise RuntimeError("CohereProvider is not available; set COHERE_API_KEY in the environment")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
        }
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        context = ssl.create_default_context()
        req = urllib_request.Request(self._API_URL, data=data, headers=headers, method="POST")
        with urllib_request.urlopen(req, context=context) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Cohere API returned HTTP {resp.status}")
            response_json = json.loads(resp.read().decode("utf-8"))
        # Cohere v2 response: {"message": {"content": [{"type": "text", "text": "..."}]}}
        message = response_json.get("message", {})
        content = message.get("content", [])
        if not content:
            raise RuntimeError("Cohere response missing content")
        return content[0].get("text", "").strip()


__all__ = [
    "OpenAICompatibleProvider",
    "GroqProvider",
    "XAIProvider",
    "MistralProvider",
    "DeepSeekProvider",
    "TogetherProvider",
    "OpenRouterProvider",
    "OllamaProvider",
    "CohereProvider",
]
