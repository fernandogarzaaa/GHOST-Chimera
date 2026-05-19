"""Ghost-native cognition trust primitives.

This module absorbs the useful trust ideas from ChimeraLang and
chimeralang-mcp into deterministic, dependency-free Ghost Chimera code.  It is
not a ChimeraLang runtime and does not require an external MCP server.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

PROTOCOL_VERSION = "ghost-handoff-v1"


@dataclass(frozen=True)
class GhostBelief:
    """A confidence-bearing belief with uncertainty."""

    value: str
    confidence: float
    variance: float = 0.0
    evidence_count: int = 1
    source: str = "operator"

    @classmethod
    def from_confidence(
        cls,
        value: str,
        confidence: float,
        *,
        variance: float | None = None,
        evidence_count: int = 1,
        source: str = "operator",
    ) -> GhostBelief:
        confidence = _clamp01(confidence)
        count = max(1, int(evidence_count))
        derived_variance = confidence * (1.0 - confidence) / (count + 1)
        return cls(
            value=str(value),
            confidence=confidence,
            variance=max(0.0, float(variance if variance is not None else derived_variance)),
            evidence_count=count,
            source=str(source or "operator"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GhostGuardResult:
    """Result of a confidence and variance guard check."""

    passed: bool
    violation: str = ""
    confidence: float = 0.0
    variance: float = 0.0
    required_confidence: float = 0.0
    allowed_variance: float = 0.05

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GhostHandoff:
    """Tamper-evident handoff between Ghost subsystems."""

    protocol_version: str
    sender: str
    receiver: str
    summary: str
    replay_envelope: dict[str, Any]
    program_hash: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, data: str) -> GhostHandoff:
        return cls(**json.loads(data))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GhostHandoffVerification:
    accepted: bool
    failure_reason: str = ""
    program_hash: str = ""
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def guard_belief(
    belief: GhostBelief,
    *,
    max_risk: float = 0.2,
    max_variance: float = 0.05,
) -> GhostGuardResult:
    """Check whether a belief is sufficiently confident and stable."""

    required = 1.0 - _clamp01(max_risk)
    violations: list[str] = []
    if belief.confidence < required:
        violations.append(f"confidence {belief.confidence:.3f} < required {required:.3f}")
    if belief.variance > max_variance:
        violations.append(f"variance {belief.variance:.4f} > allowed {max_variance:.4f}")
    return GhostGuardResult(
        passed=not violations,
        violation="; ".join(violations),
        confidence=belief.confidence,
        variance=belief.variance,
        required_confidence=required,
        allowed_variance=max_variance,
    )


def pack_handoff(
    *,
    sender: str,
    receiver: str,
    tool: str,
    args: dict[str, Any],
    payload: dict[str, Any],
    summary_text: str,
    metadata: dict[str, Any] | None = None,
) -> GhostHandoff:
    """Create a tamper-evident handoff from a deterministic tool result."""

    envelope = _replay_envelope(tool=tool, args=args, payload=payload)
    return GhostHandoff(
        protocol_version=PROTOCOL_VERSION,
        sender=str(sender),
        receiver=str(receiver),
        summary=str(summary_text),
        replay_envelope=envelope,
        program_hash=_hash_envelope(envelope),
        payload=dict(payload),
        metadata=dict(metadata or {}),
    )


def verify_handoff(handoff: GhostHandoff) -> GhostHandoffVerification:
    """Verify version, envelope shape, hash, and payload equality."""

    if handoff.protocol_version != PROTOCOL_VERSION:
        return GhostHandoffVerification(False, f"unsupported protocol version {handoff.protocol_version!r}")
    envelope = handoff.replay_envelope
    if not isinstance(envelope, dict) or envelope.get("protocol") != PROTOCOL_VERSION:
        return GhostHandoffVerification(False, "replay envelope is not a Ghost handoff envelope")
    actual_hash = _hash_envelope(envelope)
    if actual_hash != handoff.program_hash:
        return GhostHandoffVerification(False, "program hash mismatch", program_hash=actual_hash)
    if envelope.get("payload") != handoff.payload:
        return GhostHandoffVerification(False, "payload hash mismatch against replay envelope", program_hash=actual_hash)
    return GhostHandoffVerification(True, program_hash=actual_hash, payload=dict(handoff.payload))


def summarize_operational_trace(
    *,
    goal: str,
    sources: list[str] | None = None,
    policy_decision: str = "approval_required",
    tool_candidates: list[str] | None = None,
) -> dict[str, Any]:
    """Return safe operational stages for UI display.

    This is intentionally an operational trace, not hidden chain-of-thought.
    """

    selected_sources = [str(item) for item in (sources or [])]
    tools = [str(item) for item in (tool_candidates or [])]
    stages = [
        {"stage": "goal_intake", "status": "ready", "detail": str(goal)[:240]},
        {"stage": "context_retrieval", "status": "ready" if selected_sources else "empty", "detail": selected_sources},
        {"stage": "source_selection", "status": "ready", "detail": selected_sources[:8]},
        {"stage": "policy_check", "status": policy_decision, "detail": "manual approval remains available"},
        {"stage": "tool_eligibility", "status": "ready" if tools else "none", "detail": tools[:8]},
        {"stage": "plan_draft", "status": "preview", "detail": "safe plan outline only"},
        {"stage": "approval_boundary", "status": "manual", "detail": "execution requires configured approvals"},
        {"stage": "execution_preview", "status": "preview_only", "detail": "no side effects in trace view"},
    ]
    return {
        "ok": True,
        "label": "Operational trace",
        "hidden_reasoning_exposed": False,
        "timestamp": time.time(),
        "stages": stages,
    }


def _replay_envelope(*, tool: str, args: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL_VERSION,
        "tool": str(tool),
        "args": _json_safe(args),
        "payload": _json_safe(payload),
    }


def _hash_envelope(envelope: dict[str, Any]) -> str:
    raw = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = [
    "GhostBelief",
    "GhostGuardResult",
    "GhostHandoff",
    "GhostHandoffVerification",
    "guard_belief",
    "pack_handoff",
    "summarize_operational_trace",
    "verify_handoff",
]
