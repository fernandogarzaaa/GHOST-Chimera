"""Model provider router with fallback chain support."""

from __future__ import annotations

import logging

from .providers import BaseProvider, get_provider

logger = logging.getLogger(__name__)


class ModelRouter:
    """Manages an ordered fallback chain of model providers.

    Providers are tried in the order specified at construction time.
    ``select()`` returns the first available provider.
    ``route()`` tries each provider in order and returns the first successful result.
    """

    def __init__(self, provider_names: list[str]) -> None:
        self.provider_names: list[str] = list(provider_names)
        self._providers: dict[str, BaseProvider | None] = {}
        for name in self.provider_names:
            self._providers[name] = get_provider(name)

    # -- public API ----------------------------------------------------------

    def select(self) -> BaseProvider:
        """Return the first available provider in the chain.

        Raises ``RuntimeError`` when no provider is available.
        """
        for name in self.provider_names:
            provider = self._providers.get(name)
            if provider is not None and provider.available:
                return provider
        raise RuntimeError(f"No available provider in chain: {self.provider_names}")

    def route(self, system_message: str, user_message: str) -> str:
        """Try each provider in order; return the first successful response.

        On failure each provider is tried in sequence, errors are logged,
        and ``RuntimeError`` is raised only when all providers fail.
        """
        errors: list[str] = []
        for name in self.provider_names:
            provider = self._providers.get(name)
            if provider is None:
                errors.append(f"{name}: unknown provider")
                logger.warning("Router: provider '%s' is not registered", name)
                continue
            if not provider.available:
                errors.append(f"{name}: not available")
                logger.warning("Router: provider '%s' not available", name)
                continue
            try:
                result = provider.chat(system_message, user_message)
                logger.info("Router: selected provider '%s'", name)
                return result
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                logger.warning("Router: provider '%s' failed – %s", name, exc)

        raise RuntimeError("All providers failed:\n" + "\n".join(f"  - {e}" for e in errors))

    def get_fallback_chain(self) -> list[dict]:
        """Return the status of every provider in the fallback chain."""
        chain: list[dict] = []
        for name in self.provider_names:
            provider = self._providers.get(name)
            if provider is None:
                chain.append({"name": name, "available": False, "error": "unknown provider"})
                continue
            chain.append({"name": name, "available": provider.available})
        return chain
