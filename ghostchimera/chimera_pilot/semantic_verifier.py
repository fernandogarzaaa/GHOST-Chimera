"""Enhanced ResultVerifier with semantic verification.

Extends the existing structural verifier with:
- Confidence threshold enforcement
- Provenance requirement checks
- Claim verification against verification gold
- Hallucination detection integration
"""

from __future__ import annotations

from ..cognition_layer.hallucination import HallucinationDetector
from ..safety_layer.material_policy import MaterialRegistry
from .backends.base import ExecutionResult
from .result_envelope import ResultEnvelope
from .task_ir import TaskSpec


class SemanticVerifier:
    """Validate output semantically using confidence, provenance, and claims."""

    def __init__(
        self,
        min_confidence: float = 0.5,
        require_provenance: bool = True,
        registry: MaterialRegistry | None = None,
    ) -> None:
        self._min_confidence = min_confidence
        self._require_provenance = require_provenance
        self._registry = registry or MaterialRegistry()
        self._hallucinator = HallucinationDetector()

    def verify_confidence(self, confidence: float, task: TaskSpec) -> tuple[bool, str | None]:
        """Check confidence meets threshold."""
        required = task.constraints.get("min_confidence", self._min_confidence)
        if confidence < required:
            return False, f"confidence {confidence:.2f} below threshold {required}"
        return True, None

    def verify_provenance(self, envelope: ResultEnvelope) -> tuple[bool, str | None]:
        """Check provenance is complete."""
        if not envelope.provenance:
            return False, "no provenance in envelope"
        for entry in envelope.provenance:
            if not entry.get("step") or not entry.get("backend_id"):
                return False, f"incomplete provenance entry: {entry}"
        return True, None

    def verify_claims(self, envelope: ResultEnvelope, text: str) -> tuple[bool, list[str]]:
        """Verify claims using MaterialRegistry verification gold."""
        warnings: list[str] = []
        verified = True

        for claim in envelope.claims:
            claim_text = claim.get("claim", "")
            verdict = claim.get("verdict", "unverified")
            claim_type = self._registry.classify_claim(claim_text)

            # Check against verification gold
            for gold in self._registry._patterns:
                constraints = gold.get("constraints", {})
                if claim_type == "factual" and constraints.get("require_sources") and not envelope.provenance:
                    warnings.append(f"factual claim lacks source: {claim_text[:80]}")
                    verified = False

            # Check for unsupported claims
            if verdict == "unsupported":
                warnings.append(f"unsupported claim: {claim_text[:80]}")
                verified = False

        return verified, warnings

    def verify_hallucination(self, text: str, envelope: ResultEnvelope) -> tuple[bool, list[str]]:
        """Run hallucination detection on output."""
        warnings: list[str] = []

        # Scan for confidence anomalies and attack pattern terms
        if envelope.confidence is not None and envelope.confidence > 0.9:
            for attack in self._registry.attack_patterns:
                for term in attack.get("match_terms", []):
                    if term.lower() in text.lower():
                        warnings.append(f"high confidence but attack term found: {term}")

        return len(warnings) == 0, warnings

    def verify(self, task: TaskSpec, result: ExecutionResult,
               envelope: ResultEnvelope | None = None) -> tuple[bool, str | None, list[str]]:
        """Run all semantic verification checks."""
        all_ok = True
        errors: list[str] = []
        warnings: list[str] = []

        # Confidence check
        if envelope is not None and envelope.confidence is not None:
            ok, err = self.verify_confidence(envelope.confidence, task)
            if not ok:
                errors.append(err or "confidence check failed")
                all_ok = False

        # Provenance check
        if self._require_provenance and envelope is not None:
            ok, err = self.verify_provenance(envelope)
            if not ok:
                errors.append(err or "provenance check failed")
                all_ok = False

        # Claim verification
        if envelope is not None and envelope.claims:
            ok, warns = self.verify_claims(envelope, result.output)
            if not ok:
                all_ok = False
            warnings.extend(warns)

        # Hallucination check
        if envelope is not None and envelope.confidence is not None:
            ok, warns = self.verify_hallucination(result.output, envelope)
            if not ok:
                warnings.extend(warns)
                all_ok = False

        return all_ok, "; ".join(errors) if errors else None, warnings
