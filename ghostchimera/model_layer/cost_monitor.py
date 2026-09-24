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

import contextlib
import json
import threading
import time
from collections.abc import Iterator
from datetime import UTC
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


def _today() -> str:
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y-%m-%d")


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
    """Thread-safe spend ledger with per-provider budgets and persistence.

    Beyond spend: per-call token counts (provider-reported when passed,
    else char/4 estimates), per-provider latency samples (bounded, for
    p50/p95), and per-day rollups — the backing store for the Console
    Usage tab (token meter, daily consumption, cost USD).
    """

    _LATENCY_SAMPLES = 200

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spend: dict[str, float] = {}
        self._calls: dict[str, int] = {}
        self._budgets: dict[str, float] = {}
        self._by_model: dict[str, float] = {}
        self._tokens_in: dict[str, int] = {}
        self._tokens_out: dict[str, int] = {}
        self._latency_s: dict[str, list[float]] = {}
        self._daily: dict[str, dict[str, dict[str, float]]] = {}
        self._provider_locks: dict[str, threading.Lock] = {}

    def _serial(self, provider: str) -> threading.Lock:
        """Per-provider lock so same-provider attempts serialize."""
        with self._lock:
            lock = self._provider_locks.get(provider)
            if lock is None:
                lock = threading.Lock()
                self._provider_locks[provider] = lock
            return lock

    @contextlib.contextmanager
    def guard(self, provider: str) -> Iterator[CostLedger]:
        """Serialize check-call-record for one provider.

        Holds the provider's lock across the whole attempt and budget-checks
        on entry, so concurrent attempts can never jointly overshoot a cap.
        Different providers proceed in parallel; wrap the provider call AND
        its ``record()`` inside.
        """
        with self._serial(provider):
            self.check(provider)
            yield self

    def record(
        self,
        provider: str,
        model: str,
        *,
        input_text: str = "",
        output_text: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_s: float | None = None,
    ) -> float:
        """Record a call and return its catalog-priced cost in USD.

        Explicit token counts take precedence over text estimates and are
        clamped to zero. Nonnegative ``latency_s`` values contribute to the
        provider's most recent 200 latency samples; daily totals use UTC.
        """
        in_tokens = max(0, input_tokens if input_tokens is not None else estimate_tokens(input_text))
        out_tokens = max(0, output_tokens if output_tokens is not None else estimate_tokens(output_text))
        price_in, price_out = price_usd_per_1k(provider, model)
        cost = (in_tokens / 1000.0) * price_in + (out_tokens / 1000.0) * price_out
        day = _today()
        with self._lock:
            self._spend[provider] = self._spend.get(provider, 0.0) + cost
            self._calls[provider] = self._calls.get(provider, 0) + 1
            self._by_model[f"{provider}/{model}"] = self._by_model.get(f"{provider}/{model}", 0.0) + cost
            self._tokens_in[provider] = self._tokens_in.get(provider, 0) + in_tokens
            self._tokens_out[provider] = self._tokens_out.get(provider, 0) + out_tokens
            if latency_s is not None and latency_s >= 0:
                samples = self._latency_s.setdefault(provider, [])
                samples.append(float(latency_s))
                del samples[: max(0, len(samples) - self._LATENCY_SAMPLES)]
            day_entry = self._daily.setdefault(day, {}).setdefault(
                provider, {"spend": 0.0, "calls": 0, "in": 0, "out": 0}
            )
            day_entry["spend"] += cost
            day_entry["calls"] += 1
            day_entry["in"] += in_tokens
            day_entry["out"] += out_tokens
        return cost

    @staticmethod
    def _percentile(samples: list[float], pct: float) -> float:
        if not samples:
            return 0.0
        ordered = sorted(samples)
        index = min(len(ordered) - 1, max(0, int(pct / 100.0 * len(ordered))))
        return ordered[index]

    def latency_stats(self, provider: str) -> dict[str, float]:
        """Return sample count, p50, p95, and maximum latency in seconds.

        Only the most recent 200 nonnegative samples count. With no samples,
        all values are zero.
        """
        with self._lock:
            samples = list(self._latency_s.get(provider, []))
        return {
            "calls": float(len(samples)),
            "p50_s": self._percentile(samples, 50),
            "p95_s": self._percentile(samples, 95),
            "max_s": max(samples) if samples else 0.0,
        }

    def daily_summary(self, day: str = "") -> dict[str, Any]:
        """Return provider and overall spend, call, and token totals for a UTC day.

        An empty ``day`` selects today. Token totals use ``in`` and ``out``
        keys; an unrecorded day returns zero totals and no providers.
        """
        day = day or _today()
        with self._lock:
            providers = dict(self._daily.get(day, {}))
        totals = {"spend": 0.0, "calls": 0, "in": 0, "out": 0}
        for stats in providers.values():
            for key in totals:
                totals[key] += stats.get(key, 0)
        return {"day": day, "providers": providers, "totals": totals}

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

    def tokens(self, provider: str) -> dict[str, int]:
        """Return cumulative input and output token counts for a provider."""
        with self._lock:
            return {
                "in": self._tokens_in.get(provider, 0),
                "out": self._tokens_out.get(provider, 0),
            }

    def to_dict(self) -> dict[str, Any]:
        """Snapshot cumulative spend, calls, budgets, tokens, and latency stats.

        The returned mapping omits daily rollups and raw latency samples.
        """
        with self._lock:
            latency = {
                provider: {
                    "calls": float(len(samples)),
                    "p50_s": self._percentile(samples, 50),
                    "p95_s": self._percentile(samples, 95),
                    "max_s": max(samples) if samples else 0.0,
                }
                for provider, samples in self._latency_s.items()
            }
            return {
                "spend_usd": dict(self._spend),
                "calls": dict(self._calls),
                "budgets_usd": dict(self._budgets),
                "by_model_usd": dict(self._by_model),
                "tokens_in": dict(self._tokens_in),
                "tokens_out": dict(self._tokens_out),
                "latency_s": latency,
                "total_usd": sum(self._spend.values()),
                "recorded_at": time.time(),
            }

    def save(self, path: str | Path) -> Path:
        """Persist the ledger as JSON (state dir friendly)."""
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        with self._lock:
            payload["daily"] = {day: dict(providers) for day, providers in self._daily.items()}
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> CostLedger:
        """Load a ledger, or return an empty one for a missing or invalid JSON file.

        Older files without token and daily sections remain readable. Latency
        samples are not restored from the saved summary statistics.
        """
        ledger = cls()
        try:
            data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ledger
        if not isinstance(data, dict):
            return ledger
        with ledger._lock:
            for key, value in cls._float_section(data.get("spend_usd")).items():
                ledger._spend[str(key)] = value
            calls = data.get("calls")
            if isinstance(calls, dict):
                for key, value in calls.items():
                    try:
                        ledger._calls[str(key)] = int(value)
                    except (TypeError, ValueError):
                        continue
            for key, value in cls._float_section(data.get("budgets_usd")).items():
                ledger._budgets[str(key)] = value
            for key, value in cls._float_section(data.get("by_model_usd")).items():
                ledger._by_model[str(key)] = value
            for section_name, target in (("tokens_in", ledger._tokens_in), ("tokens_out", ledger._tokens_out)):
                section = data.get(section_name)
                if isinstance(section, dict):
                    for key, value in section.items():
                        try:
                            target[str(key)] = int(value)
                        except (TypeError, ValueError):
                            continue
            daily = data.get("daily")
            if isinstance(daily, dict):
                for day, providers in list(daily.items())[-30:]:
                    if not isinstance(providers, dict):
                        continue
                    cleaned = {}
                    for provider, stats in providers.items():
                        if not isinstance(stats, dict):
                            continue
                        cleaned[str(provider)] = {
                            key: float(stats.get(key, 0) or 0) for key in ("spend", "calls", "in", "out")
                        }
                    ledger._daily[str(day)] = cleaned
        return ledger

    @staticmethod
    def _float_section(section: Any) -> dict[str, float]:
        """Safely coerce a persisted mapping to str->float, skipping junk."""
        if not isinstance(section, dict):
            return {}
        cleaned: dict[str, float] = {}
        for key, value in section.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
                continue
            cleaned[str(key)] = number
        return cleaned


_ledger = CostLedger()


def get_ledger() -> CostLedger:
    """Process-wide ledger (safe default: records in memory, $0 unless priced)."""
    return _ledger


__all__ = ["BudgetExceeded", "CostLedger", "estimate_tokens", "get_ledger", "price_usd_per_1k"]
