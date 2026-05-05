"""Deterministic backend scheduler for Chimera Pilot."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from ..safety_layer.material_policy import MaterialRegistry
from .backends.base import BackendHealth, ChimeraBackend
from .task_ir import TaskSpec


@dataclass(frozen=True)
class ScheduleDecision:
    backend: ChimeraBackend
    score: float
    reasons: list[str]
    health: BackendHealth
    breakdown: dict[str, float]


class ChimeraScheduler:
    """Select the best backend for a task using transparent weighted scoring."""

    def __init__(self, backends: list[ChimeraBackend],
                 policy_registry: MaterialRegistry | None = None) -> None:
        self.backends = list(backends)
        self._registry = policy_registry
        self._adaptation_enabled = True
        self._weights: dict[str, float] = {
            "reliability": 0.35,
            "latency_budget": 0.20,
            "latency_default": 0.10,
            "cost_budget_fit": 0.20,
            "cost_budget_penalty": -0.40,
            "cost_default": 0.10,
            "privacy_offline_bonus": 0.20,
            "privacy_network_penalty": -0.30,
            "context_fit": 0.10,
            "gpu_match": 0.10,
            "network_match": 0.05,
        }

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    @property
    def adaptation_enabled(self) -> bool:
        return self._adaptation_enabled

    def set_adaptation_enabled(self, enabled: bool) -> None:
        self._adaptation_enabled = bool(enabled)

    def set_weights(self, updates: dict[str, float]) -> None:
        """Update scheduler weights for adaptive calibration experiments."""
        for key, value in updates.items():
            if key in self._weights:
                self._weights[key] = float(value)

    def adapt_from_outcome(self, *, backend_id: str, success: bool, latency_ms: float | None = None) -> None:
        """Very small bounded online adaptation hook for orchestration experiments."""
        if not self._adaptation_enabled:
            return
        delta = 0.01 if success else -0.01
        self._weights["reliability"] = max(0.1, min(0.7, self._weights["reliability"] + delta))
        if latency_ms is not None and latency_ms > 1000:
            self._weights["latency_default"] = max(0.02, self._weights["latency_default"] - 0.005)
        elif latency_ms is not None:
            self._weights["latency_default"] = min(0.2, self._weights["latency_default"] + 0.002)

    def save_weights(self, path: str) -> str:
        """Persist scheduler weights to JSON file and return serialized payload."""
        payload = json.dumps({"weights": self._weights}, indent=2)
        Path(path).write_text(payload, encoding="utf-8")
        return payload

    def load_weights(self, path: str) -> dict[str, float]:
        """Load scheduler weights from JSON file and return active weights."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        loaded = data.get("weights", {})
        self.set_weights({k: float(v) for k, v in loaded.items() if isinstance(v, (int, float))})
        return self.weights

    def rank_backends(self, task: TaskSpec) -> list[ScheduleDecision]:
        decisions: list[ScheduleDecision] = []
        for backend in self.backends:
            if not backend.can_run(task):
                continue

            health = backend.estimate(task)
            if not health.available:
                continue

            score, reasons, breakdown = self._score(task, backend, health)
            decisions.append(
                ScheduleDecision(backend=backend, score=score, reasons=reasons, health=health, breakdown=breakdown)
            )

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
                    adjusted.append(
                        ScheduleDecision(
                            backend=d.backend,
                            score=d.score - 1.0,
                            reasons=d.reasons + ["low_reliability"],
                            health=d.health,
                            breakdown=dict(d.breakdown),
                        )
                    )
                else:
                    adjusted.append(d)
            return adjusted

        return decisions

    def select_backend(self, task: TaskSpec) -> ScheduleDecision:
        ranked = self.rank_backends(task)
        if not ranked:
            raise RuntimeError(f"No available backend can run task {task.id}: {task.kind.value}")
        return ranked[0]

    def select_strategy(
        self,
        task: TaskSpec,
        *,
        historical_success_rate: float | None = None,
        uncertainty: float | None = None,
    ) -> str:
        """Choose orchestration strategy: single, fallback_chain, parallel, or moa."""
        if task.requires_network and task.privacy_level in {"sensitive", "secret"}:
            return "fallback_chain"
        if uncertainty is not None and uncertainty >= 0.6:
            return "moa"
        if historical_success_rate is not None and historical_success_rate < 0.5:
            return "parallel"
        if len(self.backends) >= 3 and task.kind.value in {"reasoning", "rag_query"}:
            return "fallback_chain"
        return "single"

    def _score(
        self, task: TaskSpec, backend: ChimeraBackend, health: BackendHealth
    ) -> tuple[float, list[str], dict[str, float]]:
        score = 0.0
        reasons: list[str] = []
        breakdown: dict[str, float] = {}

        reliability = max(0.0, min(1.0, health.reliability))
        reliability_component = reliability * self._weights["reliability"]
        score += reliability_component
        breakdown["reliability"] = reliability_component
        reasons.append(f"reliability={reliability:.2f}")

        if task.max_latency_ms:
            latency_fit = max(0.0, 1.0 - (health.latency_ms / max(1, task.max_latency_ms)))
            latency_component = latency_fit * self._weights["latency_budget"]
            score += latency_component
            breakdown["latency"] = latency_component
            reasons.append(f"latency_fit={latency_fit:.2f}")
        else:
            latency_score = 1.0 / max(1.0, health.latency_ms / 250.0)
            latency_score = min(1.0, latency_score)
            latency_component = latency_score * self._weights["latency_default"]
            score += latency_component
            breakdown["latency"] = latency_component
            reasons.append(f"latency_score={latency_score:.2f}")

        if task.max_cost_usd is not None:
            if health.estimated_cost_usd <= task.max_cost_usd:
                score += self._weights["cost_budget_fit"]
                breakdown["cost"] = self._weights["cost_budget_fit"]
                reasons.append("cost_within_budget")
            else:
                score += self._weights["cost_budget_penalty"]
                breakdown["cost"] = self._weights["cost_budget_penalty"]
                reasons.append("cost_over_budget")
        else:
            cost_score = 1.0 if health.estimated_cost_usd == 0 else max(0.0, 1.0 - health.estimated_cost_usd)
            cost_component = cost_score * self._weights["cost_default"]
            score += cost_component
            breakdown["cost"] = cost_component
            reasons.append(f"cost_score={cost_score:.2f}")

        if task.privacy_level in {"private", "sensitive", "secret"}:
            if backend.capabilities.supports_offline:
                score += self._weights["privacy_offline_bonus"]
                breakdown["privacy"] = breakdown.get("privacy", 0.0) + self._weights["privacy_offline_bonus"]
                reasons.append("offline_privacy_bonus")
            else:
                score += self._weights["privacy_network_penalty"]
                breakdown["privacy"] = breakdown.get("privacy", 0.0) + self._weights["privacy_network_penalty"]
                reasons.append("network_privacy_penalty")

        required_context = task.constraints.get("required_context_tokens")
        max_context = backend.capabilities.max_context_tokens
        if required_context is not None and max_context:
            try:
                context_fit = min(1.0, max_context / max(1, int(required_context)))
                context_component = context_fit * self._weights["context_fit"]
                score += context_component
                breakdown["context"] = context_component
                reasons.append(f"context_fit={context_fit:.2f}")
            except (TypeError, ValueError):
                reasons.append("context_fit=unknown")

        if task.requires_gpu and backend.capabilities.supports_gpu:
            score += self._weights["gpu_match"]
            breakdown["gpu"] = self._weights["gpu_match"]
            reasons.append("gpu_match")

        if task.requires_network and backend.capabilities.supports_network:
            score += self._weights["network_match"]
            breakdown["network"] = self._weights["network_match"]
            reasons.append("network_match")

        return score, reasons, breakdown
