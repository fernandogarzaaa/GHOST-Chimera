"""Cost monitoring: per-provider spend ledger with budgets (stdlib only).

Token counts are provider-reported when available, otherwise estimated at
~4 characters per token. Prices come from
:mod:`ghostchimera.model_layer.model_catalog` (0.0 when unknown, so free
and unlisted models simply record zero spend).

Usage::

    from ghostchimera.model_layer.cost_monitor import CostLedger

    ledger = CostLedger()
    ledger.record("openai", "gpt-4o-mini", input_text=system + user, output_text=reply)
    ledger.set_budget("openai", 5.0)   # USD cap
    ledger.check("openai")             # raises BudgetExceeded past the cap
    ledger.save(state_dir / "model_costs.json")
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from .model_catalog import get_catalog_entry


class BudgetExceeded(RuntimeError):
    """Raised when recorded spend passes a configured budget cap."""


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token); floor of 1 for non-empty text."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def price_usd_per_1k(provider: str, model: str) -> tuple[float, float]:
    """(input, output) USD price per 1k tokens; (0.0, 0.0) when unknown."""
    try:
        entry = get_catalog_entry(provider, model)
    except Exception:
        return (0.0, 0.0)
    if entry is None:
        return (0.0, 0.0)
    return (float(entry.input_cost_usd_per_1k), float(entry.output_cost_usd_per_1k))


class CostLedger:
    """Thread-safe spend ledger with per-provider budgets and persistence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spend: dict[str, float] = {}
        self._calls: dict[str, int] = {}
        self._budgets: dict[str, float] = {}
        self._by_model: dict[str, float] = {}

    def record(
        self,
        provider: str,
        model: str,
        *,
        input_text: str = "",
        output_text: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> float:
        """Record one call; return its estimated USD cost."""
        in_tokens = input_tokens if input_tokens is not None else estimate_tokens(input_text)
        out_tokens = output_tokens if output_tokens is not None else estimate_tokens(output_text)
        price_in, price_out = price_usd_per_1k(provider, model)
        cost = (max(0, in_tokens) / 1000.0) * price_in + (max(0, out_tokens) / 1000.0) * price_out
        with self._lock:
            self._spend[provider] = self._spend.get(provider, 0.0) + cost
            self._calls[provider] = self._calls.get(provider, 0) + 1
            self._by_model[f"{provider}/{model}"] = self._by_model.get(f"{provider}/{model}", 0.0) + cost
        return cost

    def spend(self, provider: str) -> float:
        with self._lock:
            return self._spend.get(provider, 0.0)

    def total_spend(self) -> float:
        with self._lock:
            return sum(self._spend.values())

    def calls(self, provider: str) -> int:
        with self._lock:
            return self._calls.get(provider, 0)

    def set_budget(self, provider: str, usd: float) -> None:
        """Cap spend for *provider*; non-positive values remove the cap."""
        with self._lock:
            if usd and usd > 0:
                self._budgets[provider] = float(usd)
            else:
                self._budgets.pop(provider, None)

    def check(self, provider: str) -> None:
        """Raise :class:`BudgetExceeded` when *provider* is past its cap."""
        with self._lock:
            cap = self._budgets.get(provider)
            spent = self._spend.get(provider, 0.0)
        if cap is not None and spent > cap:
            raise BudgetExceeded(f"Provider {provider!r} spent ${spent:.4f} past budget ${cap:.4f}")

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "spend_usd": dict(self._spend),
                "calls": dict(self._calls),
                "budgets_usd": dict(self._budgets),
                "by_model_usd": dict(self._by_model),
                "total_usd": sum(self._spend.values()),
                "recorded_at": time.time(),
            }

    def save(self, path: str | Path) -> Path:
        """Persist the ledger as JSON (state dir friendly)."""
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> CostLedger:
        """Load a persisted ledger; missing/corrupt files yield an empty one."""
        ledger = cls()
        try:
            data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ledger
        if not isinstance(data, dict):
            return ledger
        with ledger._lock:
            for key, value in dict(data.get("spend_usd", {})).items():
                ledger._spend[str(key)] = float(value)
            for key, value in dict(data.get("calls", {})).items():
                ledger._calls[str(key)] = int(value)
            for key, value in dict(data.get("budgets_usd", {})).items():
                ledger._budgets[str(key)] = float(value)
            for key, value in dict(data.get("by_model_usd", {})).items():
                ledger._by_model[str(key)] = float(value)
        return ledger


_ledger = CostLedger()


def get_ledger() -> CostLedger:
    """Process-wide ledger (safe default: records in memory, $0 unless priced)."""
    return _ledger


__all__ = ["BudgetExceeded", "CostLedger", "estimate_tokens", "get_ledger", "price_usd_per_1k"]
