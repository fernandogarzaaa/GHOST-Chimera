"""Media provider interfaces for Ghost Chimera.

Mirrors OpenClaw's media-provider registrar surface:
    - ``registerImageGenerationProvider``
    - ``registerSpeechProvider``
    - ``registerWebSearchProvider``
    - ``registerWebFetchProvider``
    - ``registerMediaUnderstandingProvider``
    - ``documentExtractors``

Each abstract base class follows the same :class:`AuthProfile` injection
pattern as :class:`~ghostchimera.model_layer.providers.BaseProvider`:
pass an :class:`~ghostchimera.model_layer.auth_profiles.AuthProfile` at
construction time, or fall back to environment variables.

Usage::

    from ghostchimera.model_layer.media_providers import (
        ImageGenerationProvider,
        SpeechProvider,
        WebSearchProvider,
        WebFetchProvider,
        MediaUnderstandingProvider,
        DocumentExtractor,
        MEDIA_PROVIDERS,
        get_media_provider,
    )

    search = get_media_provider("web_search", "openai_search")
    results = search.search("latest AI research", max_results=5)
"""

from __future__ import annotations

import inspect
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..logging_config import get_logger

if TYPE_CHECKING:
    from .auth_profiles import AuthProfile

logger = get_logger("media_providers")


# ---------------------------------------------------------------------------
# Shared result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageResult:
    """Result returned by an :class:`ImageGenerationProvider`."""

    url: str = ""
    base64_data: str = ""
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.url or self.base64_data)


@dataclass(frozen=True)
class SpeechResult:
    """Result returned by a :class:`SpeechProvider`."""

    audio_data: bytes = b""
    mime_type: str = "audio/mpeg"
    duration_seconds: float = 0.0
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.audio_data)


@dataclass(frozen=True)
class WebSearchResult:
    """A single hit from a :class:`WebSearchProvider`."""

    title: str = ""
    url: str = ""
    snippet: str = ""
    score: float = 0.0
    published_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebFetchResult:
    """Result returned by a :class:`WebFetchProvider`."""

    url: str = ""
    content: str = ""
    mime_type: str = "text/plain"
    status_code: int = 0
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


@dataclass(frozen=True)
class MediaUnderstandingResult:
    """Result returned by a :class:`MediaUnderstandingProvider`."""

    description: str = ""
    tags: list[str] = field(default_factory=list)
    objects: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentExtractionResult:
    """Result returned by a :class:`DocumentExtractor`."""

    text: str = ""
    pages: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    provider: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text)


# ---------------------------------------------------------------------------
# Abstract base classes
# ---------------------------------------------------------------------------


class ImageGenerationProvider(ABC):
    """Abstract base for image-generation providers.

    Mirrors OpenClaw's ``registerImageGenerationProvider`` contract.
    """

    name: str = "base_image"
    available: bool = False

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        n: int = 1,
        style: str = "natural",
    ) -> list[ImageResult]:
        """Generate images from a text prompt."""

    def validate_config(self) -> list[str]:
        """Return configuration errors. Empty list means OK."""
        return []


class SpeechProvider(ABC):
    """Abstract base for text-to-speech providers.

    Mirrors OpenClaw's ``registerSpeechProvider`` contract.
    """

    name: str = "base_speech"
    available: bool = False

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        voice: str = "alloy",
        speed: float = 1.0,
        format: str = "mp3",
    ) -> SpeechResult:
        """Convert text to speech audio."""

    def validate_config(self) -> list[str]:
        return []


class WebSearchProvider(ABC):
    """Abstract base for web-search providers.

    Mirrors OpenClaw's ``registerWebSearchProvider`` contract.
    """

    name: str = "base_web_search"
    available: bool = False

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        sites: list[str] | None = None,
        language: str = "en",
    ) -> list[WebSearchResult]:
        """Run a web search and return ranked results."""

    def validate_config(self) -> list[str]:
        return []


class WebFetchProvider(ABC):
    """Abstract base for web-content-fetch providers.

    Mirrors OpenClaw's ``registerWebFetchProvider`` contract.
    """

    name: str = "base_web_fetch"
    available: bool = False

    @abstractmethod
    def fetch(self, url: str, *, timeout_seconds: float = 15.0) -> WebFetchResult:
        """Fetch the content at *url* and return it."""

    def validate_config(self) -> list[str]:
        return []


class MediaUnderstandingProvider(ABC):
    """Abstract base for vision / media-understanding providers.

    Mirrors OpenClaw's ``registerMediaUnderstandingProvider`` contract.
    """

    name: str = "base_media_understanding"
    available: bool = False

    @abstractmethod
    def describe(
        self,
        image_data: bytes | str,
        *,
        mime_type: str = "image/jpeg",
        detail: str = "auto",
    ) -> MediaUnderstandingResult:
        """Describe the contents of an image.

        Parameters
        ----------
        image_data:
            Raw bytes or a base64-encoded string.
        mime_type:
            MIME type of the image.
        detail:
            Level of detail: ``"auto"``, ``"low"``, or ``"high"``.
        """

    def validate_config(self) -> list[str]:
        return []


class DocumentExtractor(ABC):
    """Abstract base for document-extraction providers.

    Mirrors OpenClaw's ``documentExtractors`` contract.
    """

    name: str = "base_document_extractor"
    supported_mime_types: list[str] = []

    @abstractmethod
    def extract(self, data: bytes, *, mime_type: str = "application/pdf") -> DocumentExtractionResult:
        """Extract text and metadata from raw document bytes."""

    def validate_config(self) -> list[str]:
        return []


# ---------------------------------------------------------------------------
# Built-in stdlib implementations (no external dependencies)
# ---------------------------------------------------------------------------


class StdlibWebFetchProvider(WebFetchProvider):
    """Simple stdlib-only web fetch using ``urllib``."""

    name = "stdlib_web_fetch"

    def __init__(self, profile: AuthProfile | None = None) -> None:  # noqa: ARG002
        self.available = True

    def fetch(self, url: str, *, timeout_seconds: float = 15.0) -> WebFetchResult:
        import ssl
        import urllib.request

        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(url, context=ctx, timeout=timeout_seconds) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                return WebFetchResult(
                    url=url,
                    content=content,
                    mime_type=resp.headers.get_content_type() or "text/html",
                    status_code=resp.status,
                    provider=self.name,
                )
        except Exception as exc:
            return WebFetchResult(url=url, content="", status_code=0, provider=self.name,
                                  metadata={"error": str(exc)})


class OpenAIImageProvider(ImageGenerationProvider):
    """Image generation via OpenAI DALL-E."""

    name = "openai_image"

    def __init__(self, profile: AuthProfile | None = None) -> None:
        if profile is not None:
            self.api_key = profile.api_key or os.environ.get("OPENAI_API_KEY", "")
            self.model = profile.model or os.environ.get("OPENAI_IMAGE_MODEL", "dall-e-3")
        else:
            self.api_key = os.environ.get("OPENAI_API_KEY", "")
            self.model = os.environ.get("OPENAI_IMAGE_MODEL", "dall-e-3")
        self.available = bool(self.api_key)

    def validate_config(self) -> list[str]:
        if not self.api_key:
            return ["OPENAI_API_KEY is not set"]
        return []

    def generate(self, prompt: str, *, width: int = 1024, height: int = 1024,
                 n: int = 1, style: str = "natural") -> list[ImageResult]:
        import json
        import ssl
        import urllib.request

        if not self.available:
            raise RuntimeError("OpenAIImageProvider is not available; set OPENAI_API_KEY")

        size = f"{width}x{height}"
        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "n": n,
            "size": size,
            "style": style,
            "response_format": "url",
        }).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = "https://api.openai.com/v1/images/generations"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            return [
                ImageResult(url=item.get("url", ""), provider=self.name,
                            width=width, height=height)
                for item in data.get("data", [])
            ]


class OpenAISpeechProvider(SpeechProvider):
    """TTS via OpenAI ``/v1/audio/speech``."""

    name = "openai_speech"

    def __init__(self, profile: AuthProfile | None = None) -> None:
        if profile is not None:
            self.api_key = profile.api_key or os.environ.get("OPENAI_API_KEY", "")
            self.model = profile.model or os.environ.get("OPENAI_TTS_MODEL", "tts-1")
        else:
            self.api_key = os.environ.get("OPENAI_API_KEY", "")
            self.model = os.environ.get("OPENAI_TTS_MODEL", "tts-1")
        self.available = bool(self.api_key)

    def validate_config(self) -> list[str]:
        if not self.api_key:
            return ["OPENAI_API_KEY is not set"]
        return []

    def synthesize(self, text: str, *, voice: str = "alloy",
                   speed: float = 1.0, format: str = "mp3") -> SpeechResult:
        import json
        import ssl
        import urllib.request

        if not self.available:
            raise RuntimeError("OpenAISpeechProvider is not available; set OPENAI_API_KEY")

        body = json.dumps({
            "model": self.model,
            "input": text,
            "voice": voice,
            "speed": speed,
            "response_format": format,
        }).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = "https://api.openai.com/v1/audio/speech"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx) as resp:
            audio = resp.read()
            return SpeechResult(audio_data=audio,
                                mime_type=f"audio/{format}",
                                provider=self.name)


class OpenAIVisionProvider(MediaUnderstandingProvider):
    """Vision understanding via OpenAI GPT-4o vision."""

    name = "openai_vision"

    def __init__(self, profile: AuthProfile | None = None) -> None:
        if profile is not None:
            self.api_key = profile.api_key or os.environ.get("OPENAI_API_KEY", "")
            self.model = profile.model or os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")
        else:
            self.api_key = os.environ.get("OPENAI_API_KEY", "")
            self.model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")
        self.available = bool(self.api_key)

    def validate_config(self) -> list[str]:
        if not self.api_key:
            return ["OPENAI_API_KEY is not set"]
        return []

    def describe(self, image_data: bytes | str, *, mime_type: str = "image/jpeg",
                 detail: str = "auto") -> MediaUnderstandingResult:
        import base64
        import json
        import ssl
        import urllib.request

        if not self.available:
            raise RuntimeError("OpenAIVisionProvider is not available; set OPENAI_API_KEY")

        b64 = base64.b64encode(image_data).decode() if isinstance(image_data, bytes) else image_data

        body = json.dumps({
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime_type};base64,{b64}", "detail": detail}},
                    {"type": "text", "text": "Describe this image in detail."},
                ],
            }],
            "max_tokens": 512,
        }).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = "https://api.openai.com/v1/chat/completions"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            text = data["choices"][0]["message"]["content"].strip()
            return MediaUnderstandingResult(description=text, provider=self.name, confidence=0.9)


# ---------------------------------------------------------------------------
# MEDIA_PROVIDERS registry — split by provider_type
# ---------------------------------------------------------------------------

MEDIA_PROVIDERS: dict[str, dict[str, type]] = {
    "image_generation": {
        OpenAIImageProvider.name: OpenAIImageProvider,
    },
    "speech": {
        OpenAISpeechProvider.name: OpenAISpeechProvider,
    },
    "web_search": {},  # No built-in web search — external plugins register here
    "web_fetch": {
        StdlibWebFetchProvider.name: StdlibWebFetchProvider,
    },
    "media_understanding": {
        OpenAIVisionProvider.name: OpenAIVisionProvider,
    },
    "document_extractor": {},  # External plugins register here
}


def register_media_provider(provider_type: str, name: str, cls: type) -> None:
    """Register a media provider class.

    Parameters
    ----------
    provider_type:
        One of the keys in :data:`MEDIA_PROVIDERS`.
    name:
        Provider identifier.
    cls:
        Provider class (must subclass the appropriate ABC).
    """
    if provider_type not in MEDIA_PROVIDERS:
        MEDIA_PROVIDERS[provider_type] = {}
    MEDIA_PROVIDERS[provider_type][name] = cls
    logger.debug("Registered media provider %s/%s", provider_type, name)


def get_media_provider(
    provider_type: str,
    name: str,
    profile: AuthProfile | None = None,
) -> Any | None:
    """Instantiate a media provider by type and name.

    Parameters
    ----------
    provider_type:
        Category, e.g. ``"image_generation"`` or ``"speech"``.
    name:
        Provider identifier, e.g. ``"openai_image"``.
    profile:
        Optional :class:`~ghostchimera.model_layer.auth_profiles.AuthProfile`
        for credential injection.

    Returns
    -------
    An instantiated provider or ``None`` if unknown.
    """
    cls = MEDIA_PROVIDERS.get(provider_type, {}).get(name)
    if cls is None:
        return None
    # Check whether the provider's __init__ accepts a 'profile' parameter so that
    # a TypeError inside cls(profile) (e.g. missing required args in a custom provider)
    # is not silently swallowed by a broad except clause.
    try:
        sig = inspect.signature(cls.__init__)
        accepts_profile = "profile" in sig.parameters
    except (ValueError, TypeError):
        # Signature is not inspectable (e.g. C-extension type); log and fall back
        # to attempting profile injection so that well-formed providers still work.
        logger.debug(
            "Cannot inspect signature of %s.__init__; assuming profile injection is supported",
            cls.__name__,
        )
        accepts_profile = True
    try:
        return cls(profile) if accepts_profile else cls()
    except Exception as exc:
        logger.warning("Failed to instantiate media provider %s/%s: %s", provider_type, name, exc)
        return None


__all__ = [
    "ImageGenerationProvider",
    "SpeechProvider",
    "WebSearchProvider",
    "WebFetchProvider",
    "MediaUnderstandingProvider",
    "DocumentExtractor",
    "ImageResult",
    "SpeechResult",
    "WebSearchResult",
    "WebFetchResult",
    "MediaUnderstandingResult",
    "DocumentExtractionResult",
    "OpenAIImageProvider",
    "OpenAISpeechProvider",
    "OpenAIVisionProvider",
    "StdlibWebFetchProvider",
    "MEDIA_PROVIDERS",
    "register_media_provider",
    "get_media_provider",
]
