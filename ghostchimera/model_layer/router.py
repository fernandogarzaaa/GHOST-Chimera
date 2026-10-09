"""Model provider router with fallback chain support."""

from __future__ import annotations

import logging
import time

from .cost_monitor import BudgetExceeded, CostLedger, get_ledger
from .providers import BaseProvider, get_provider
from .rate_limit import RateLimitExceeded, get_limiter

logger = logging.getLogger(__name__)


class ModelRouter:
    """Manages an ordered fallback chain of model providers.

    Providers are tried in the order specified at construction time.
    ``select()`` returns the first available provider.
    ``route()`` tries each provider in order and returns the first successful result.

    Every attempt passes through the provider's rate limiter (unlimited
    unless ``GHOSTCHIMERA_RL_*`` env vars configure one) and every success
    is recorded on the cost ledger (zero-cost unless catalog-priced).
    """

    def __init__(self, provider_names: list[str], *, ledger: CostLedger | None = None) -> None:
        self.provider_names: list[str] = list(provider_names)
        self.ledger = ledger or get_ledger()
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
                get_limiter(name).acquire()
            except RateLimitExceeded as exc:
                errors.append(f"{name}: rate limited ({exc})")
                logger.warning("Router: provider '%s' rate limited", name)
                continue
            try:
                with self.ledger.guard(name):
                    started = time.time()
                    result = provider.chat(system_message, user_message)
                    model = str(getattr(provider, "model", "") or "")
                    self.ledger.record(
                        name,
                        model,
                        input_text=f"{system_message}\n{user_message}",
                        output_text=result,
                        latency_s=round(time.time() - started, 3),
                    )
                logger.info("Router: selected provider '%s'", name)
                return result
            except BudgetExceeded as exc:
                errors.append(f"{name}: budget blocked ({exc})")
                logger.warning("Router: provider '%s' over budget", name)
                continue
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
