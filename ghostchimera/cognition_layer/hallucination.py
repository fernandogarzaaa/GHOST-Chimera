"""Hallucination detection for agent reasoning traces.

Analyzes execution gate logs and confidence-scored runtime values to detect:
- Branch divergence (branches producing wildly different results)
- Confidence anomalies (sudden drops without explanation)
- Promotion violations (Explore->Confident without gate consensus)
- Source trace gaps (values lacking provenance)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from .confidence import (
    ChimeraValue,
    ConfidentValue,
)

if TYPE_CHECKING:
    from .workspace import WorkingMemory


class HallucinationKind(Enum):
    """Types of hallucination indicators."""

    BRANCH_DIVERGENCE = auto()  # gate branches disagree significantly
    CONFIDENCE_ANOMALY = auto()  # unexplained confidence spike/drop
    PROMOTION_VIOLATION = auto()  # Explore->Confident without gate
    SOURCE_GAP = auto()  # value has no provenance trace
    FINGERPRINT_MISMATCH = auto()  # computed fingerprint doesn't match stored


@dataclass(frozen=True, slots=True)
class HallucinationFlag:
    """A single hallucination finding."""

    kind: HallucinationKind
    severity: float  # 0.0-1.0
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionReport:
    """Aggregated hallucination scan results."""

    flags: list[HallucinationFlag] = field(default_factory=list)
    values_scanned: int = 0
    gates_scanned: int = 0
    clean: bool = True

    def add(self, flag: HallucinationFlag) -> None:
        self.flags.append(flag)
        self.clean = False

    def summary(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "flags": [
                {
                    "kind": f.kind.name,
                    "severity": f.severity,
                    "description": f.description,
                }
                for f in self.flags
            ],
            "values_scanned": self.values_scanned,
            "gates_scanned": self.gates_scanned,
        }


class HallucinationDetector:
    """Scans execution results for hallucination indicators.

    Works with generic gate-log dicts and Ghost Chimera's confidence types.
    Standalone -- no MCP dependency.
    """

    def __init__(
        self,
        divergence_threshold: float = 0.3,
        confidence_spike_threshold: float = 0.4,
    ) -> None:
        self._div_threshold = divergence_threshold
        self._spike_threshold = confidence_spike_threshold

    def scan_gate_log(
        self, gate_log: dict[str, Any], report: DetectionReport
    ) -> None:
        """Analyze a single gate execution log.

        Expects a dict with keys like 'gate', 'branch_confidences',
        'result_confidence'. Generic -- does not depend on ChimeraLang types.
        """
        report.gates_scanned += 1
        confidences: list[float] = gate_log.get("branch_confidences", [])
        if not confidences:
            return

        # Branch divergence: check spread of branch confidences
        max_c = max(confidences)
        min_c = min(confidences)
        spread = max_c - min_c
        if spread > self._div_threshold:
            report.add(HallucinationFlag(
                kind=HallucinationKind.BRANCH_DIVERGENCE,
                severity=min(spread, 1.0),
                description=(
                    f"Gate '{gate_log.get('gate', '?')}' branches diverged: "
                    f"spread={spread:.3f} (threshold={self._div_threshold})"
                ),
                evidence={
                    "gate": gate_log.get("gate"),
                    "confidences": confidences,
                    "spread": spread,
                },
            ))

        # Confidence anomaly: result confidence much higher than average branch
        avg_branch = sum(confidences) / len(confidences)
        result_conf: float = gate_log.get("result_confidence", 0.0)
        spike = result_conf - avg_branch
        if spike > self._spike_threshold:
            report.add(HallucinationFlag(
                kind=HallucinationKind.CONFIDENCE_ANOMALY,
                severity=min(spike, 1.0),
                description=(
                    f"Gate '{gate_log.get('gate', '?')}' result confidence "
                    f"({result_conf:.3f}) is suspiciously higher than branch "
                    f"average ({avg_branch:.3f})"
                ),
                evidence={
                    "gate": gate_log.get("gate"),
                    "result_confidence": result_conf,
                    "avg_branch_confidence": avg_branch,
                    "spike": spike,
                },
            ))

    def scan_value(self, value: ChimeraValue, report: DetectionReport) -> None:
        """Analyze a single Ghost Chimera confidence value for hallucination indicators."""
        report.values_scanned += 1

        # Source gap: no trace at all
        if not value.trace:
            report.add(HallucinationFlag(
                kind=HallucinationKind.SOURCE_GAP,
                severity=0.5,
                description=f"Value '{value.raw}' has no provenance trace",
                evidence={"raw": value.raw, "confidence": value.confidence.value},
            ))

        # Promotion violation: ConfidentValue with low source confidence
        if isinstance(value, ConfidentValue):
            if value.confidence.source == "Explore_constructor":
                report.add(HallucinationFlag(
                    kind=HallucinationKind.PROMOTION_VIOLATION,
                    severity=0.9,
                    description="Confident value was created from Explore source",
                    evidence={"raw": value.raw, "source": value.confidence.source},
                ))

        # Fingerprint integrity
        data = f"{type(value.raw).__name__}:{value.raw}:{value.confidence.value}"
        expected_fp = hashlib.sha256(data.encode()).hexdigest()[:16]
        computed_fp = value.fingerprint if isinstance(value, ChimeraValue) else ""
        if isinstance(value, ChimeraValue) and computed_fp != expected_fp:
            report.add(HallucinationFlag(
                kind=HallucinationKind.FINGERPRINT_MISMATCH,
                severity=0.8,
                description=f"Value fingerprint mismatch (computed: {expected_fp})",
                evidence={
                    "computed": expected_fp,
                    "actual": computed_fp,
                },
            ))

    def full_scan(
        self,
        gate_logs: list[dict[str, Any]],
        emitted_values: list[ChimeraValue],
    ) -> DetectionReport:
        """Run a complete hallucination scan over an execution result.

        Accepts generic gate-log dicts and Ghost Chimera's ChimeraValue types.
        """
        report = DetectionReport()
        for gl in gate_logs:
            self.scan_gate_log(gl, report)
        for val in emitted_values:
            self.scan_value(val, report)
        return report
