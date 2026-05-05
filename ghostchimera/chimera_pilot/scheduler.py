"""Deterministic backend scheduler for Chimera Pilot."""

from __future__ import annotations

from dataclasses import dataclass

from ..safety_layer.material_policy import MaterialRegistry
from .backends.base import BackendHealth, ChimeraBackend
from .task_ir import TaskSpec


@dataclass(frozen=True)
class ScheduleDecision:
    backend: ChimeraBackend
    score: float
    reasons: list[str]
    health: BackendHealth


class ChimeraScheduler:
    """Select the best backend for a task using transparent weighted scoring."""

    def __init__(self, backends: list[ChimeraBackend],
                 policy_registry: MaterialRegistry | None = None) -> None:
        self.backends = list(backends)
        self._registry = policy_registry

    def rank_backends(self, task: TaskSpec) -> list[ScheduleDecision]:
        decisions: list[ScheduleDecision] = []
        for backend in self.backends:
            if not backend.can_run(task):
                continue

            health = backend.estimate(task)
            if not health.available:
                continue

            score, reasons = self._score(task, backend, health)
            decisions.append(ScheduleDecision(backend=backend, score=score, reasons=reasons, health=health))

        decisions.sort(key=lambda item: (-item.score, item.backend.id))

        # Apply policy constraints from MaterialRegistry
        if self._registry:
            decisions = self._apply_policy_constraints(task, decisions)

        return decisions

    def _apply_policy_constraints(self, task: TaskSpec,
                                  decisions: list[ScheduleDecision]) -> list[ScheduleDecision]:
        """Filter/re-score backends based on MaterialRegistry policy patterns."""
        policy_id = task.constraints.get("policy_pattern", "strict_factual")
        pattern = self._registry.get_pattern(policy_id)
        if not pattern:
            return decisions

        constraints = pattern.get("constraints", {})
        min_confidence = constraints.get("min_confidence", 0.0)

        # mcp_security: deny network backends (token_theft / scope_creep risk)
        if "mcp_security" in policy_id:
            return [d for d in decisions if not d.backend.capabilities.supports_network]

        # medical_cautious: require high-confidence backends only
        if "medical_cautious" in policy_id:
            adjusted: list[ScheduleDecision] = []
            for d in decisions:
                if d.health.reliability < min_confidence:
                    adjusted.append(ScheduleDecision(backend=d.backend, score=d.score - 1.0,
                                                     reasons=d.reasons + ["low_reliability"], health=d.health))
                else:
                    adjusted.append(d)
            return adjusted

        return decisions

    def select_backend(self, task: TaskSpec) -> ScheduleDecision:
        ranked = self.rank_backends(task)
        if not ranked:
            raise RuntimeError(f"No available backend can run task {task.id}: {task.kind.value}")
        return ranked[0]

    def _score(self, task: TaskSpec, backend: ChimeraBackend, health: BackendHealth) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        reliability = max(0.0, min(1.0, health.reliability))
        score += reliability * 0.35
        reasons.append(f"reliability={reliability:.2f}")

        if task.max_latency_ms:
            latency_fit = max(0.0, 1.0 - (health.latency_ms / max(1, task.max_latency_ms)))
            score += latency_fit * 0.20
            reasons.append(f"latency_fit={latency_fit:.2f}")
        else:
            latency_score = 1.0 / max(1.0, health.latency_ms / 250.0)
            latency_score = min(1.0, latency_score)
            score += latency_score * 0.10
            reasons.append(f"latency_score={latency_score:.2f}")

        if task.max_cost_usd is not None:
            if health.estimated_cost_usd <= task.max_cost_usd:
                score += 0.20
                reasons.append("cost_within_budget")
            else:
                score -= 0.40
                reasons.append("cost_over_budget")
        else:
            cost_score = 1.0 if health.estimated_cost_usd == 0 else max(0.0, 1.0 - health.estimated_cost_usd)
            score += cost_score * 0.10
            reasons.append(f"cost_score={cost_score:.2f}")

        if task.privacy_level in {"private", "sensitive", "secret"}:
            if backend.capabilities.supports_offline:
                score += 0.20
                reasons.append("offline_privacy_bonus")
            else:
                score -= 0.30
                reasons.append("network_privacy_penalty")

        required_context = task.constraints.get("required_context_tokens")
        max_context = backend.capabilities.max_context_tokens
        if required_context is not None and max_context:
            try:
                context_fit = min(1.0, max_context / max(1, int(required_context)))
                score += context_fit * 0.10
                reasons.append(f"context_fit={context_fit:.2f}")
            except (TypeError, ValueError):
                reasons.append("context_fit=unknown")

        if task.requires_gpu and backend.capabilities.supports_gpu:
            score += 0.10
            reasons.append("gpu_match")

        if task.requires_network and backend.capabilities.supports_network:
            score += 0.05
            reasons.append("network_match")

        return score, reasons
