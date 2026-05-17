"""PolicyEnforcer: combines MaterialRegistry with PilotPolicy validation.

Provides the unified enforcement gate that runs MaterialRegistry checks
(policy patterns, attack pattern scanning, claim classification) alongside
the existing PilotPolicy binary allow/deny rules, returning a combined
enforcement result.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from ..chimera_pilot.policy import PilotPolicy
from ..chimera_pilot.task_ir import TaskSpec
from .material_policy import MaterialRegistry


@dataclass
class EnforcementResult:
    """Combined result from the PolicyEnforcer."""

    allowed: bool
    policy_id: str
    material_check: dict[str, Any] | None = None
    pilot_check: dict[str, Any] | None = None
    claims: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace_id: str = ""
    simulated: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_trace(self, step: str, detail: dict[str, Any]) -> None:
        self.trace.append({"step": step, "detail": detail})


class PolicyEnforcer:
    """Combines MaterialRegistry checks with PilotPolicy validation."""

    def __init__(
        self,
        registry: MaterialRegistry | None = None,
        default_policy: str = "strict_factual",
    ) -> None:
        self._registry = registry or MaterialRegistry()
        self._default_policy = default_policy

    def enforce(
        self,
        task: TaskSpec,
        policy: PilotPolicy | None = None,
        *,
        simulate: bool = False,
    ) -> EnforcementResult:
        """Run all policy checks and return combined result."""
        result = EnforcementResult(
            allowed=True,
            policy_id=self._default_policy,
            trace_id=f"policy-trace-{uuid.uuid4().hex[:10]}",
            simulated=simulate,
        )

        # MaterialRegistry checks
        text = f"{task.objective} {task.inputs}"
        material = self._registry.check_security(text, self._default_policy)
        result.material_check = material
        result.add_trace(
            "material_check", {"policy_id": self._default_policy, "matches": len(material["attack_matches"])}
        )

        # Warn on high-risk attack matches
        for match in material["attack_matches"]:
            result.add_warning(f"Attack pattern '{match['attack_id']}' matched (severity={match['severity']})")
            result.allowed = False

        # PilotPolicy validation (binary allow/deny)
        pilot_policy = policy or PilotPolicy()
        if simulate:
            try:
                pilot_policy.validate(task)
                result.pilot_check = {"status": "allowed", "simulated": True}
                result.add_trace("pilot_policy", {"status": "allowed", "simulated": True})
            except PermissionError as exc:
                result.pilot_check = {"status": "denied", "reason": str(exc), "simulated": True}
                result.allowed = False
                result.add_trace("pilot_policy", {"status": "denied", "simulated": True, "reason": str(exc)})
            result.add_warning("Simulation mode enabled: no execution side effects were performed")
        else:
            try:
                pilot_policy.validate(task)
                result.pilot_check = {"status": "allowed"}
                result.add_trace("pilot_policy", {"status": "allowed", "simulated": False})
            except PermissionError as exc:
                result.pilot_check = {"status": "denied", "reason": str(exc)}
                result.allowed = False
                result.add_trace("pilot_policy", {"status": "denied", "simulated": False, "reason": str(exc)})

        return result

    def classify_output(self, text: str) -> dict[str, Any]:
        """Classify an output string for claim extraction and risk analysis."""
        claims: list[dict[str, Any]] = []
        for kw in ("that", "is", "are", "has", "was"):
            if kw in text.lower():
                parts = [s.strip() for s in text.split(kw) if s.strip()]
                for part in parts:
                    if len(part) > 10:
                        claims.append(
                            {
                                "claim": part,
                                "type": self._registry.classify_claim(part),
                            }
                        )
                break

        return {
            "claims": claims,
            "attack_matches": self._registry.find_attack_matches(text),
        }

    def classify_claim(self, claim: str) -> str:
        """Delegate claim classification to the MaterialRegistry."""
        return self._registry.classify_claim(claim)

    def check_security(self, text: str, policy_id: str = "strict_factual") -> dict[str, Any]:
        """Delegate security check to the MaterialRegistry."""
        return self._registry.check_security(text, policy_id)
