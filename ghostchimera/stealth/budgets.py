"""Cost and attention budgets: sliding-window spend governors.

The evaluator caps intervention frequency and context assembly caps tokens
per package, but nothing meters cumulative cost or how often Ghost surfaces
things to the user. Budgets fill that: named, windowed allowances in
caller-defined units (tokens, surfaces, calls) with atomic check-and-spend
for gating and record-only metering for observation. Safety-critical flows
(approvals) meter without gating; volume flows (proposal creation) gate.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

PROPOSAL_BUDGET = "proposals"
ATTENTION_BUDGET = "attention_surfaces"
COST_BUDGET = "cost_units"

DEFAULT_BUDGETS = {
    PROPOSAL_BUDGET: {"limit": 30.0, "window_s": 3600.0, "unit": "proposals/hour"},
    ATTENTION_BUDGET: {"limit": 10.0, "window_s": 3600.0, "unit": "surfaces/hour"},
    COST_BUDGET: {"limit": 100000.0, "window_s": 3600.0, "unit": "units/hour"},
}


@dataclass
class Budget:
    """One named allowance over a sliding window."""

    name: str
    limit: float = 0.0
    window_s: float = 3600.0
    unit: str = ""
    _spends: deque[tuple[float, float]] = field(default_factory=deque)

    def _prune(self, now: float) -> None:
        window = max(0.0, self.window_s)
        while self._spends and self._spends[0][0] <= now - window:
            self._spends.popleft()

    def spent(self, now: float | None = None) -> float:
        """Total recorded inside the window."""

        moment = now if now is not None else time.time()
        self._prune(moment)
        return sum(amount for _, amount in self._spends)

    def remaining(self, now: float | None = None) -> float:
        return max(0.0, self.limit - self.spent(now))

    def check(self, amount: float = 1.0, *, now: float | None = None) -> bool:
        """True when amount fits without recording."""

        moment = now if now is not None else time.time()
        return amount >= 0 and self.spent(moment) + amount <= self.limit

    def record(self, amount: float = 1.0, *, now: float | None = None) -> float:
        """Meter-only bookkeeping; always records, returns window total."""

        moment = now if now is not None else time.time()
        if amount > 0:
            self._spends.append((moment, amount))
        self._prune(moment)
        return sum(entry[1] for entry in self._spends)

    def spend(self, amount: float = 1.0, *, now: float | None = None) -> bool:
        """Atomic gate: record only when amount fits."""

        moment = now if now is not None else time.time()
        if not self.check(amount, now=moment):
            return False
        self._spends.append((moment, amount))
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "limit": self.limit,
            "window_s": self.window_s,
            "unit": self.unit,
            "spends": [[when, amount] for when, amount in self._spends],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Budget:
        data = data if isinstance(data, dict) else {}
        budget = cls(
            name=str(data.get("name", "unnamed")),
            limit=max(0.0, float(data.get("limit", 0.0) or 0.0)),
            window_s=max(0.0, float(data.get("window_s", 3600.0) or 0.0)),
            unit=str(data.get("unit", "")),
        )
        for entry in data.get("spends", []) or []:
            try:
                when, amount = float(entry[0]), float(entry[1])
            except (IndexError, TypeError, ValueError):
                continue
            if amount > 0:
                budget._spends.append((when, amount))
        return budget


class BudgetTracker:
    """Registry of named budgets with gating and metering helpers."""

    def __init__(self, defaults: bool = True) -> None:
        self._budgets: dict[str, Budget] = {}
        if defaults:
            for name, spec in DEFAULT_BUDGETS.items():
                self.define(name, spec["limit"], window_s=spec["window_s"], unit=spec["unit"])

    def define(self, name: str, limit: float, *, window_s: float = 3600.0, unit: str = "") -> Budget:
        budget = Budget(name=name, limit=max(0.0, limit), window_s=max(0.0, window_s), unit=unit)
        self._budgets[name] = budget
        return budget

    def get(self, name: str) -> Budget | None:
        return self._budgets.get(name)

    def check(self, name: str, amount: float = 1.0, *, now: float | None = None) -> bool:
        budget = self._budgets.get(name)
        if budget is None:
            return True
        return budget.check(amount, now=now)

    def record(self, name: str, amount: float = 1.0, *, now: float | None = None) -> float:
        budget = self._budgets.get(name)
        if budget is None:
            return 0.0
        return budget.record(amount, now=now)

    def spend(self, name: str, amount: float = 1.0, *, now: float | None = None) -> bool:
        """Gate on the budget; unknown budgets allow (fail-open, metered nowhere)."""

        budget = self._budgets.get(name)
        if budget is None:
            return True
        return budget.spend(amount, now=now)

    def sweep(self, now: float | None = None) -> None:
        moment = now if now is not None else time.time()
        for budget in self._budgets.values():
            budget._prune(moment)

    def __len__(self) -> int:
        return len(self._budgets)

    def to_dict(self) -> dict[str, Any]:
        return {"budgets": [budget.to_dict() for budget in self._budgets.values()]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BudgetTracker:
        tracker = cls(defaults=False)
        for raw in (data or {}).get("budgets", []) or []:
            budget = Budget.from_dict(raw)
            tracker._budgets[budget.name] = budget
        return tracker


__all__ = [
    "ATTENTION_BUDGET",
    "COST_BUDGET",
    "DEFAULT_BUDGETS",
    "PROPOSAL_BUDGET",
    "Budget",
    "BudgetTracker",
]
