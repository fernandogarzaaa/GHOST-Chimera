"""MultiLLM: run 2+ providers side by side in one call (stdlib only).

Where :class:`~ghostchimera.model_layer.router.ModelRouter` fails over
*sequentially*, ``MultiLLM`` fans out *simultaneously*: every configured
provider is asked at once and each answer (or error) is collected. Use it
for latency-critical paths, cross-model verification, and best-of-N
selection — with per-provider rate limits and cost recording applied to
every attempt.

Usage::

    from ghostchimera.model_layer.multi_llm import MultiLLM

    fabric = MultiLLM(["openai", "anthropic"])
    first = fabric.ask_first("Summarize this.", "Quarterly report ...")
    all_answers = fabric.ask_all("Summarize this.", "Quarterly report ...")
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

from .cost_monitor import BudgetExceeded, CostLedger, get_ledger
from .providers import BaseProvider, get_provider
from .rate_limit import RateLimitExceeded, get_limiter

logger = logging.getLogger(__name__)


class MultiLLM:
    """Query several providers simultaneously and combine the outcomes."""

    def __init__(
        self,
        provider_names: list[str],
        *,
        max_workers: int | None = None,
        ledger: CostLedger | None = None,
    ) -> None:
        self.provider_names: list[str] = list(provider_names)
        self.max_workers = max_workers or max(1, len(self.provider_names))
        self.ledger = ledger or get_ledger()
        self._providers: dict[str, BaseProvider | None] = {}
        for name in self.provider_names:
            self._providers[name] = get_provider(name)

    def _attempt(self, name: str, system_message: str, user_message: str) -> dict[str, Any]:
        """One provider attempt: rate-limit, budget-guard, call, record.

        The ledger guard serializes same-provider attempts so concurrent
        calls can never jointly overshoot a budget cap.
        """
        provider = self._providers.get(name)
        if provider is None:
            return {"name": name, "ok": False, "error": "unknown provider", "answer": ""}
        if not provider.available:
            return {"name": name, "ok": False, "error": "not available", "answer": ""}
        try:
            get_limiter(name).acquire()
        except RateLimitExceeded as exc:
            return {"name": name, "ok": False, "error": f"rate limited: {exc}", "answer": ""}
        try:
            with self.ledger.guard(name):
                answer = provider.chat(system_message, user_message)
                model = str(getattr(provider, "model", "") or "")
                cost = self.ledger.record(
                    name, model, input_text=f"{system_message}\n{user_message}", output_text=answer
                )
        except BudgetExceeded as exc:
            return {"name": name, "ok": False, "error": f"budget blocked: {exc}", "answer": ""}
        except Exception as exc:
            logger.warning("MultiLLM: provider '%s' failed – %s", name, exc)
            return {"name": name, "ok": False, "error": str(exc), "answer": ""}
        return {"name": name, "ok": True, "error": "", "answer": answer, "model": model, "cost_usd": cost}

    def ask_all(self, system_message: str, user_message: str) -> dict[str, dict[str, Any]]:
        """Ask every provider at once; return per-provider outcome dicts."""
        outcomes: dict[str, dict[str, Any]] = {}
        if not self.provider_names:
            return outcomes
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._attempt, name, system_message, user_message): name for name in self.provider_names
            }
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    outcomes[name] = future.result()
                except Exception as exc:  # pragma: no cover - defensive
                    outcomes[name] = {"name": name, "ok": False, "error": str(exc), "answer": ""}
        return outcomes

    def ask_first(self, system_message: str, user_message: str) -> dict[str, Any]:
        """Parallel fallback: return the first successful answer.

        Attempts run simultaneously; the first success to *complete* wins
        instead of waiting for every provider. Remaining attempts are
        cancelled where still pending. Raises ``RuntimeError`` only when
        every provider fails.
        """
        if not self.provider_names:
            raise RuntimeError("All providers failed: no providers configured")
        outcomes: dict[str, dict[str, Any]] = {}
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            futures = {
                pool.submit(self._attempt, name, system_message, user_message): name for name in self.provider_names
            }
            pending = set(futures)
            while pending:
                done, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    name = futures[future]
                    try:
                        outcomes[name] = future.result()
                    except Exception as exc:  # pragma: no cover - defensive
                        outcomes[name] = {"name": name, "ok": False, "error": str(exc), "answer": ""}
                    if outcomes[name].get("ok"):
                        outcome = dict(outcomes[name])
                        outcome["strategy"] = "parallel-first-success"
                        return outcome
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        errors = "; ".join(f"{n}: {o.get('error')}" for n, o in outcomes.items())
        raise RuntimeError(f"All providers failed: {errors}")

    def status(self) -> list[dict[str, Any]]:
        """Availability snapshot for every configured provider."""
        snapshot: list[dict[str, Any]] = []
        for name in self.provider_names:
            provider = self._providers.get(name)
            snapshot.append(
                {
                    "name": name,
                    "available": bool(provider is not None and provider.available),
                    "model": str(getattr(provider, "model", "") or "") if provider else "",
                    "spend_usd": self.ledger.spend(name),
                    "calls": self.ledger.calls(name),
                }
            )
        return snapshot


__all__ = ["MultiLLM"]
