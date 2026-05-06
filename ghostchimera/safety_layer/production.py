"""Production-readiness guardrails for high-impact execution."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_TRUTHY = {"1", "true", "yes", "on"}
_PRODUCTION_MODES = {"production", "prod", "enterprise"}
_ISOLATION_VALUES = {"container", "vm", "service-account", "service_account", "sandboxed"}


@dataclass(frozen=True)
class ProductionGuardrails:
    """Runtime declarations required before production high-impact execution."""

    deployment_mode: str = "development"
    external_isolation: str = ""
    security_reviewed: bool = False
    human_approval_required: bool = False
    trusted_inputs_only: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ProductionGuardrails:
        env = environ or os.environ
        mode = (env.get("GHOSTCHIMERA_DEPLOYMENT_MODE") or env.get("GHOSTCHIMERA_ENV") or "development").strip()
        return cls(
            deployment_mode=mode.lower() or "development",
            external_isolation=env.get("GHOSTCHIMERA_EXTERNAL_ISOLATION", "").strip().lower(),
            security_reviewed=_truthy(env.get("GHOSTCHIMERA_SECURITY_REVIEWED")),
            human_approval_required=_truthy(env.get("GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED")),
            trusted_inputs_only=not _truthy(env.get("GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS")),
        )

    @property
    def is_production(self) -> bool:
        return self.deployment_mode in _PRODUCTION_MODES

    @property
    def has_external_isolation(self) -> bool:
        return self.external_isolation in _ISOLATION_VALUES

    @property
    def ready(self) -> bool:
        if not self.is_production:
            return True
        return (
            self.has_external_isolation
            and self.security_reviewed
            and self.human_approval_required
            and self.trusted_inputs_only
        )

    def requirement_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "external_isolation",
                "ok": self.has_external_isolation,
                "detail": self.external_isolation or "not declared",
                "remediation": "Set GHOSTCHIMERA_EXTERNAL_ISOLATION to container, vm, service-account, or sandboxed.",
            },
            {
                "name": "security_reviewed",
                "ok": self.security_reviewed,
                "detail": str(self.security_reviewed).lower(),
                "remediation": "Set GHOSTCHIMERA_SECURITY_REVIEWED=1 after deployment-level review.",
            },
            {
                "name": "human_approval_required",
                "ok": self.human_approval_required,
                "detail": str(self.human_approval_required).lower(),
                "remediation": "Set GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1 and route high-impact tool calls through approval.",
            },
            {
                "name": "trusted_inputs_only",
                "ok": self.trusted_inputs_only,
                "detail": str(self.trusted_inputs_only).lower(),
                "remediation": "Keep GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS unset for host execution.",
            },
        ]

    def require_ready(self, surface: str) -> None:
        if not self.is_production:
            return
        failures = [item["name"] for item in self.requirement_rows() if not item["ok"]]
        if failures:
            raise PermissionError(f"Production mode blocks {surface}; missing guardrails: {', '.join(failures)}")

    def reject_untrusted_task(self, task: Mapping[str, Any], surface: str) -> None:
        if not self.is_production:
            return
        if _truthy(str(task.get("untrusted", ""))) or task.get("trusted") is False:
            raise PermissionError(f"Production mode blocks untrusted {surface} on the host")

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_mode": self.deployment_mode,
            "external_isolation": self.external_isolation,
            "security_reviewed": self.security_reviewed,
            "human_approval_required": self.human_approval_required,
            "trusted_inputs_only": self.trusted_inputs_only,
            "ready": self.ready,
            "requirements": self.requirement_rows() if self.is_production else [],
        }


def production_readiness_report(guardrails: ProductionGuardrails | None = None) -> dict[str, Any]:
    active = guardrails or ProductionGuardrails.from_env()
    return {
        "ok": active.ready,
        "production_mode": active.is_production,
        "guardrails": active.to_dict(),
    }


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


__all__ = ["ProductionGuardrails", "production_readiness_report"]
