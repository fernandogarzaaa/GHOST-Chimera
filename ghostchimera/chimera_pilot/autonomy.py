"""User-adjustable autonomy profiles for Chimera Pilot.

The profiles here tune budgets and execution posture. They do not grant
permissions by themselves; network, Python, shell, file, and desktop execution
still require the existing policy opt-ins and production guardrails.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AutonomyProfile:
    """Runtime contract for how much initiative Ghost Chimera may take."""

    name: str
    description: str
    max_tool_rounds: int
    max_parallel_tasks: int
    max_background_jobs: int
    default_max_cost_usd: float
    local_model_profile: str
    allow_scheduler_adaptation: bool
    allow_parallel_execution: bool
    allow_background_jobs: bool
    allow_self_training: bool
    require_approval_for_high_impact: bool
    strategy_ceiling: str
    positioning: str = "capability profile, not AGI or consciousness"

    def to_dict(self) -> dict[str, str | int | float | bool]:
        return asdict(self)

    def cap_strategy(self, strategy: str) -> str:
        """Return the strongest permitted scheduler strategy for this profile."""

        strategy = (strategy or "single").strip().lower()
        order = {
            "single": 0,
            "fallback_chain": 1,
            "parallel": 2,
            "moa": 3,
        }
        ceiling = order.get(self.strategy_ceiling, 0)
        requested = order.get(strategy, 0)
        if requested <= ceiling:
            return strategy
        for candidate, rank in sorted(order.items(), key=lambda item: item[1], reverse=True):
            if rank <= ceiling:
                return candidate
        return "single"


_PROFILES: dict[str, AutonomyProfile] = {
    "assist": AutonomyProfile(
        name="assist",
        description="Read-mostly assistant mode with narrow budgets and single-backend execution.",
        max_tool_rounds=6,
        max_parallel_tasks=1,
        max_background_jobs=0,
        default_max_cost_usd=0.0,
        local_model_profile="tiny",
        allow_scheduler_adaptation=False,
        allow_parallel_execution=False,
        allow_background_jobs=False,
        allow_self_training=False,
        require_approval_for_high_impact=True,
        strategy_ceiling="single",
    ),
    "supervised": AutonomyProfile(
        name="supervised",
        description="Default beta posture with fallback routing, bounded loops, and approval for high-impact actions.",
        max_tool_rounds=12,
        max_parallel_tasks=1,
        max_background_jobs=0,
        default_max_cost_usd=0.0,
        local_model_profile="balanced",
        allow_scheduler_adaptation=True,
        allow_parallel_execution=False,
        allow_background_jobs=False,
        allow_self_training=False,
        require_approval_for_high_impact=True,
        strategy_ceiling="fallback_chain",
    ),
    "autonomous": AutonomyProfile(
        name="autonomous",
        description="Operator-enabled mode for larger tool loops, parallel task groups, and background job surfaces.",
        max_tool_rounds=20,
        max_parallel_tasks=4,
        max_background_jobs=3,
        default_max_cost_usd=0.0,
        local_model_profile="stronger",
        allow_scheduler_adaptation=True,
        allow_parallel_execution=True,
        allow_background_jobs=True,
        allow_self_training=False,
        require_approval_for_high_impact=True,
        strategy_ceiling="parallel",
    ),
    "generalist": AutonomyProfile(
        name="generalist",
        description="Highest local-first beta profile: broad routing, MoA-style strategy selection, and preview-only self-improvement hooks.",
        max_tool_rounds=28,
        max_parallel_tasks=6,
        max_background_jobs=5,
        default_max_cost_usd=0.0,
        local_model_profile="stronger",
        allow_scheduler_adaptation=True,
        allow_parallel_execution=True,
        allow_background_jobs=True,
        allow_self_training=False,
        require_approval_for_high_impact=True,
        strategy_ceiling="moa",
    ),
}

_ALIASES = {
    "manual": "assist",
    "default": "supervised",
    "safe": "supervised",
    "auto": "autonomous",
    "agi": "generalist",
    "sgi": "generalist",
    "superior-general-intelligence": "generalist",
    "superior_general_intelligence": "generalist",
}


def get_autonomy_profile(name: str) -> AutonomyProfile:
    key = (name or "supervised").strip().lower()
    key = _ALIASES.get(key, key)
    try:
        return _PROFILES[key]
    except KeyError as exc:
        available = ", ".join(sorted(_PROFILES))
        raise ValueError(f"Unknown autonomy profile '{name}'. Available profiles: {available}") from exc


def get_autonomy_profile_from_env() -> AutonomyProfile:
    return get_autonomy_profile(os.environ.get("GHOSTCHIMERA_AUTONOMY_LEVEL", "supervised"))


def list_autonomy_profiles() -> list[AutonomyProfile]:
    return [_PROFILES[name] for name in sorted(_PROFILES)]


__all__ = [
    "AutonomyProfile",
    "get_autonomy_profile",
    "get_autonomy_profile_from_env",
    "list_autonomy_profiles",
]
