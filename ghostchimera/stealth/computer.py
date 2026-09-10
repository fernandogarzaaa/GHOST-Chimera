"""Safe Computer Use hierarchy for EVE actions."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .eve_model import WorkflowMaturity


class ComputerModality(StrEnum):
    BROWSER = "browser"
    DESKTOP = "desktop"
    VISION = "vision"


class ComputerRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


BROWSER_OPERATIONS = frozenset(
    {
        "browser.read",
        "browser.click",
        "browser.type",
        "browser.navigate",
        "browser.wait",
    }
)
DESKTOP_OPERATIONS = frozenset(
    {
        "desktop.read",
        "desktop.click",
        "desktop.type",
        "desktop.press",
        "desktop.wait",
    }
)
VISION_OPERATIONS = frozenset(
    {
        "vision.capture",
        "vision.locate",
        "vision.read",
    }
)
GENERIC_OPERATIONS = frozenset(
    {
        "ui.read",
        "ui.click",
        "ui.type",
    }
)
READ_OPERATIONS = frozenset(
    {
        "browser.read",
        "browser.wait",
        "desktop.read",
        "desktop.wait",
        "vision.capture",
        "vision.locate",
        "vision.read",
        "ui.read",
    }
)
HIGH_RISK_OPERATIONS = frozenset(
    {
        "browser.navigate",
        "desktop.press",
    }
)
_PREFERRED_MODALITIES = (
    ComputerModality.BROWSER,
    ComputerModality.DESKTOP,
    ComputerModality.VISION,
)
_TRUSTED_MATURITIES = frozenset(
    {
        WorkflowMaturity.APPROVED,
        WorkflowMaturity.AUTONOMOUS,
    }
)


def _modality_operations(modality: ComputerModality) -> frozenset[str]:
    if modality == ComputerModality.BROWSER:
        return BROWSER_OPERATIONS | GENERIC_OPERATIONS
    if modality == ComputerModality.DESKTOP:
        return DESKTOP_OPERATIONS | GENERIC_OPERATIONS
    return VISION_OPERATIONS | GENERIC_OPERATIONS


def _contains_secret(value: Any) -> bool:
    text = str(value).lower()
    return any(marker in text for marker in ("password", "secret", "token", "private_key"))


def classify_risk(operation: str, target: str, parameters: dict[str, Any]) -> ComputerRisk:
    normalized_operation = operation.strip().lower()
    if (
        normalized_operation in HIGH_RISK_OPERATIONS
        or _contains_secret(target)
        or any(_contains_secret(value) for value in parameters.values())
    ):
        return ComputerRisk.HIGH
    if normalized_operation in READ_OPERATIONS:
        return ComputerRisk.LOW
    return ComputerRisk.MEDIUM


@dataclass
class ComputerAction:
    operation: str
    target: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    modality: ComputerModality | None = None
    risk: ComputerRisk | None = None
    action_id: str = field(default_factory=lambda: f"computer-{uuid.uuid4().hex[:12]}")
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        self.operation = self.operation.strip().lower()
        self.target = self.target.strip()
        self.parameters = dict(self.parameters)
        self.context = dict(self.context)
        if not self.operation:
            raise ValueError("Computer action requires an operation")
        if isinstance(self.modality, str):
            self.modality = ComputerModality(self.modality)
        if isinstance(self.risk, str):
            self.risk = ComputerRisk(self.risk)
        if not self.idempotency_key:
            self.idempotency_key = self.action_id

    def resolved_modality(self) -> ComputerModality:
        if self.modality is not None:
            return self.modality
        if self.operation.startswith("browser."):
            return ComputerModality.BROWSER
        if self.operation.startswith("desktop."):
            return ComputerModality.DESKTOP
        if self.operation.startswith("vision."):
            return ComputerModality.VISION
        if self.operation.startswith("ui."):
            if str(self.context.get("active_url") or "").strip():
                return ComputerModality.BROWSER
            if str(self.context.get("active_application") or "").strip():
                return ComputerModality.DESKTOP
            return ComputerModality.VISION
        raise ValueError(f"Unsupported computer operation: {self.operation}")

    def resolved_risk(self) -> ComputerRisk:
        if self.risk is not None:
            return self.risk
        return classify_risk(self.operation, self.target, self.parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "idempotency_key": self.idempotency_key,
            "operation": self.operation,
            "target": self.target,
            "parameters": dict(self.parameters),
            "context": dict(self.context),
            "modality": self.resolved_modality().value,
            "risk": self.resolved_risk().value,
        }


@dataclass(frozen=True)
class ComputerApproval:
    approved_by: str
    action_id: str
    granted_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def covers(self, action: ComputerAction, *, now: float | None = None) -> bool:
        moment = now if now is not None else time.time()
        if self.action_id != action.action_id:
            return False
        return self.expires_at is None or moment <= self.expires_at


@dataclass(frozen=True)
class ComputerCapability:
    name: str = "default-deny"
    enabled: bool = False
    allowed_modalities: frozenset[ComputerModality] = frozenset({ComputerModality.BROWSER})
    allowed_operations: frozenset[str] = frozenset({"browser.read"})
    max_risk: ComputerRisk = ComputerRisk.LOW


@dataclass(frozen=True)
class ComputerUsePlan:
    action: ComputerAction
    modality: ComputerModality
    provider: str
    fallbacks: tuple[str, ...]
    risk: ComputerRisk
    maturity: WorkflowMaturity
    approval_required: bool
    executable: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "modality": self.modality.value,
            "provider": self.provider,
            "fallbacks": list(self.fallbacks),
            "risk": self.risk.value,
            "maturity": self.maturity.value,
            "approval_required": self.approval_required,
            "executable": self.executable,
            "reason": self.reason,
        }


class ComputerUseProvider(ABC):
    @property
    @abstractmethod
    def modality(self) -> ComputerModality:
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def supports(self, action: ComputerAction) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(self, action: ComputerAction, *, dry_run: bool) -> dict[str, Any]:
        raise NotImplementedError


class DelegatingComputerProvider(ComputerUseProvider):
    def __init__(
        self,
        *,
        name: str,
        modality: ComputerModality,
        executor: Any | None = None,
    ) -> None:
        self._name = name
        self._modality = modality
        self._executor = executor

    @property
    def modality(self) -> ComputerModality:
        return self._modality

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return self._executor is not None

    def supports(self, action: ComputerAction) -> bool:
        try:
            resolved = action.resolved_modality()
        except ValueError:
            return False
        if resolved != self._modality and action.operation not in GENERIC_OPERATIONS:
            return False
        return action.operation in _modality_operations(self._modality)

    def execute(self, action: ComputerAction, *, dry_run: bool) -> dict[str, Any]:
        receipt = {
            "action_id": action.action_id,
            "idempotency_key": action.idempotency_key,
            "provider": self._name,
            "modality": self._modality.value,
            "operation": action.operation,
            "dry_run": dry_run,
        }
        if dry_run:
            return {**receipt, "ok": True, "result": {"planned": True}}
        if self._executor is None:
            raise RuntimeError(f"Computer provider {self._name} is not connected")
        return {**receipt, "ok": True, "result": self._executor(action.to_dict())}


class ComputerUseManager:
    def __init__(self) -> None:
        self._providers: dict[ComputerModality, ComputerUseProvider] = {}

    def register(self, provider: ComputerUseProvider) -> None:
        self._providers[provider.modality] = provider

    def plan(
        self,
        action: ComputerAction,
        capability: ComputerCapability,
        maturity: WorkflowMaturity,
    ) -> ComputerUsePlan:
        risk = action.resolved_risk()
        if not capability.enabled:
            return self._denied(action, maturity, risk, "computer use is disabled")
        try:
            preferred = action.resolved_modality()
        except ValueError as exc:
            return self._denied(action, maturity, risk, str(exc))
        if preferred not in capability.allowed_modalities:
            return self._denied(action, maturity, risk, f"modality {preferred.value} is not permitted")
        if action.operation not in capability.allowed_operations:
            return self._denied(action, maturity, risk, f"operation {action.operation} is not permitted")
        if self._risk_rank(risk) > self._risk_rank(capability.max_risk):
            return self._denied(action, maturity, risk, f"risk {risk.value} exceeds capability")

        candidates = [preferred, *[modality for modality in _PREFERRED_MODALITIES if modality != preferred]]
        fallbacks: list[str] = []
        selected: ComputerUseProvider | None = None
        for modality in candidates:
            provider = self._providers.get(modality)
            if provider is None or not provider.supports(action):
                continue
            if selected is None and provider.is_available():
                selected = provider
            elif provider.is_available():
                fallbacks.append(provider.name)
        if selected is None:
            return self._denied(action, maturity, risk, "no available provider supports this action")

        approval_required = risk != ComputerRisk.LOW or maturity not in _TRUSTED_MATURITIES
        reason = "ready for execution" if not approval_required else "explicit approval is required"
        return ComputerUsePlan(
            action=action,
            modality=selected.modality,
            provider=selected.name,
            fallbacks=tuple(fallbacks),
            risk=risk,
            maturity=maturity,
            approval_required=approval_required,
            executable=True,
            reason=reason,
        )

    def execute(
        self,
        plan: ComputerUsePlan,
        capability: ComputerCapability,
        approval: ComputerApproval | None = None,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if not plan.executable:
            return self._receipt(plan, False, {"error": plan.reason})
        if not capability.enabled:
            return self._receipt(plan, False, {"error": "computer use is disabled"})
        provider = self._providers.get(plan.modality)
        if provider is None or provider.name != plan.provider or not provider.is_available():
            return self._receipt(plan, False, {"error": "selected provider is unavailable"})
        if plan.approval_required and (approval is None or not approval.covers(plan.action)):
            return self._receipt(plan, False, {"error": "explicit approval is required"})
        try:
            return provider.execute(plan.action, dry_run=dry_run)
        except Exception as exc:
            return self._receipt(plan, False, {"error": f"{type(exc).__name__}: {exc}"})

    def _denied(
        self,
        action: ComputerAction,
        maturity: WorkflowMaturity,
        risk: ComputerRisk,
        reason: str,
    ) -> ComputerUsePlan:
        try:
            modality = action.resolved_modality()
        except ValueError:
            modality = ComputerModality.VISION
        return ComputerUsePlan(
            action=action,
            modality=modality,
            provider="",
            fallbacks=(),
            risk=risk,
            maturity=maturity,
            approval_required=True,
            executable=False,
            reason=reason,
        )

    def _receipt(self, plan: ComputerUsePlan, ok: bool, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "action_id": plan.action.action_id,
            "idempotency_key": plan.action.idempotency_key,
            "provider": plan.provider,
            "modality": plan.modality.value,
            "operation": plan.action.operation,
            "dry_run": False,
            "ok": ok,
            "result": result,
        }

    @staticmethod
    def _risk_rank(risk: ComputerRisk) -> int:
        return {
            ComputerRisk.LOW: 0,
            ComputerRisk.MEDIUM: 1,
            ComputerRisk.HIGH: 2,
        }[risk]


__all__ = [
    "BROWSER_OPERATIONS",
    "DESKTOP_OPERATIONS",
    "VISION_OPERATIONS",
    "GENERIC_OPERATIONS",
    "ComputerAction",
    "ComputerApproval",
    "ComputerCapability",
    "ComputerModality",
    "ComputerRisk",
    "ComputerUseManager",
    "ComputerUsePlan",
    "ComputerUseProvider",
    "DelegatingComputerProvider",
    "classify_risk",
]
