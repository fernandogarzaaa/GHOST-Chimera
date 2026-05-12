"""Abstract base class for Ghost Chimera model providers.

Separated from ``providers.py`` to avoid circular imports — both
``providers.py`` and ``openai_compatible_providers.py`` import from here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


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


__all__ = ["BaseProvider"]
