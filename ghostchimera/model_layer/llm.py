"""
LLM Wrapper
===========

Provides a unified interface over different model providers.  The concrete
providers are implemented in :mod:`ghostchimera.model_layer.providers`.

Selecting a provider
--------------------

By default the provider is selected based on the environment variable
``GHOSTCHIMERA_MODEL_PROVIDER``.  If not set it defaults to ``openai``.  A
provider name can also be passed explicitly when constructing :class:`LLM`.

If a provider is not available (for example because its dependencies are not
installed or required environment variables are missing) an exception will be
raised when attempting to call :meth:`chat`.  Callers can check the
``available`` attribute before calling.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ..logging_config import get_logger
from .providers import PROVIDERS, BaseProvider, get_provider

if TYPE_CHECKING:
    from .auth_profiles import AuthProfile

logger = get_logger("llm")


class LLM:
    """Unified interface to multiple model providers."""

    def __init__(self, provider: str | None = None, profile: AuthProfile | None = None) -> None:
        # Determine provider name either from argument or environment
        provider_name = provider or os.environ.get("GHOSTCHIMERA_MODEL_PROVIDER", "openai")
        logger.info("LLM initialized with provider: %s", provider_name)
        if provider_name not in PROVIDERS:
            raise ValueError(f"Unknown provider '{provider_name}'. Available providers: {', '.join(PROVIDERS.keys())}")
        self.provider_name = provider_name
        self.provider: BaseProvider = get_provider(provider_name, profile)
        self.available: bool = self.provider.available

        # Surface per-provider config issues as warnings so callers learn early
        # rather than failing silently at chat time.
        config_errors = self.provider.validate_config()
        for error in config_errors:
            logger.warning("Provider %s config issue: %s", provider_name, error)

    def chat(self, system_message: str, user_message: str) -> str:
        """Delegate a chat request to the underlying provider."""
        logger.debug("Delegating chat to provider %s", self.provider_name)
        return self.provider.chat(system_message, user_message)
