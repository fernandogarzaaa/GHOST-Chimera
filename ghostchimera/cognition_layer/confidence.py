"""Confidence type system extracted from ChimeraLang.

Defines probabilistic runtime types with strict confidence boundaries,
product-rule uncertainty combination, and memory scope tracking.
All types are stdlib-only (no MCP dependency).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, TypeVar

T = TypeVar("T")


class ConfidenceLevel(Enum):
    """Semantic confidence tiers (not arbitrary floats)."""
    HIGH = auto()       # >= 0.95 -- "Confident"
    MEDIUM = auto()     # 0.5 - 0.95 -- explorable range
    LOW = auto()        # < 0.5 -- very uncertain
    UNKNOWN = auto()    # no confidence info


class MemoryScope(Enum):
    EPHEMERAL = auto()    # dies when scope exits
    PERSISTENT = auto()   # survives across executions
    PROVISIONAL = auto()  # held until contradicted


@dataclass(slots=True)
class Confidence:
    """Numerical confidence with a source trace."""
    value: float
    source: str = "inferred"
    timestamp: float = field(default_factory=time.time)

    @property
    def level(self) -> ConfidenceLevel:
        if self.value >= 0.95:
            return ConfidenceLevel.HIGH
        if self.value >= 0.5:
            return ConfidenceLevel.MEDIUM
        if self.value > 0.0:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.UNKNOWN

    def combine(self, other: Confidence) -> Confidence:
        """Product rule combination for independent confidences.

        Averaging two 0.5 confidences gives 0.5, but independent uncertainties
        should compound -- the product p*q correctly reflects that both must hold.
        """
        product = self.value * other.value
        return Confidence(
            value=product,
            source=f"combined({self.source},{other.source})",
        )


@dataclass
class ChimeraValue:
    """Base for all probabilistic runtime values."""
    raw: Any
    confidence: Confidence
    memory_scope: MemoryScope = MemoryScope.EPHEMERAL
    trace: list[str] = field(default_factory=list)

    def _compute_fingerprint(self) -> str:
        data = f"{type(self.raw).__name__}:{self.raw}:{self.confidence.value}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    @property
    def fingerprint(self) -> str:
        """Computed on demand so it stays accurate even if confidence mutates."""
        return self._compute_fingerprint()


@dataclass
class ConfidentValue(ChimeraValue):
    """Value with >= 0.95 confidence. Assertion fails on creation if below."""

    def __post_init__(self) -> None:
        if self.confidence.value < 0.95:
            raise ConfidenceViolation(
                f"Confident requires confidence >= 0.95, got {self.confidence.value}"
            )


@dataclass
class ExploreValue(ChimeraValue):
    """Value in exploration space -- hallucination explicitly allowed."""
    exploration_budget: float = 1.0


@dataclass
class ConvergeValue(ChimeraValue):
    """Value requiring multi-branch consensus."""
    branch_values: list[ChimeraValue] = field(default_factory=list)
    consensus_method: str = "majority"


@dataclass
class ProvisionalValue(ChimeraValue):
    """Revocable value -- valid until contradicted."""
    revoked: bool = False

    def revoke(self) -> ProvisionalValue:
        return ProvisionalValue(
            raw=self.raw,
            confidence=Confidence(0.0, "revoked"),
            memory_scope=self.memory_scope,
            trace=[*self.trace, "REVOKED"],
            revoked=True,
        )


class ConfidenceViolation(Exception):
    """Raised when a confidence boundary is violated."""


class PromotionViolation(Exception):
    """Raised when an unsafe promotion (Explore -> Confident) is attempted."""


class TypeMismatch(Exception):
    """Raised when static type check fails."""
