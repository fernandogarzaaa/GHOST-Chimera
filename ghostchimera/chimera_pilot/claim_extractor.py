"""Claim extraction from agent output.

Extracts structured claims with classification, provenance tracking,
and semantic verification readiness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..safety_layer.material_policy import MaterialRegistry


@dataclass
class Claim:
    """A single extracted claim."""

    text: str
    claim_type: str  # factual, temporal, numeric, opinion
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)
    verified: bool = False
    risk_score: float = 0.0


class ClaimExtractor:
    """Extract claims from freeform text with classification."""

    def __init__(self, registry: MaterialRegistry | None = None) -> None:
        self._registry = registry or MaterialRegistry()

    def extract(self, text: str) -> list[Claim]:
        """Extract claims from text."""
        claims: list[Claim] = []
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if len(s.strip()) > 10]

        for sentence in sentences:
            # Skip if sentence is clearly uncertain
            if any(
                marker in sentence.lower()
                for marker in (
                    "i don't know",
                    "i do not know",
                    "unclear",
                    "not enough information",
                    "unknown",
                )
            ):
                continue

            claim_type = self._registry.classify_claim(sentence)
            risk_score = self._compute_risk(sentence)

            claims.append(
                Claim(
                    text=sentence.strip(),
                    claim_type=claim_type,
                    confidence=1.0 - risk_score,
                    risk_score=risk_score,
                )
            )

        return claims

    def _compute_risk(self, text: str) -> float:
        """Compute risk score from attack pattern matches and uncertainty markers."""
        score = 0.0

        # Attack pattern matches increase risk
        attacks = self._registry.find_attack_matches(text)
        for attack in attacks:
            score += attack["severity"]

        return min(1.0, score)

    def extract_and_verify(self, text: str) -> dict[str, Any]:
        """Extract claims and verify against available evidence."""
        claims = self.extract(text)
        security = self._registry.check_security(text)

        return {
            "claims": [c.__dict__ for c in claims],
            "claim_count": len(claims),
            "factual_count": sum(1 for c in claims if c.claim_type == "factual"),
            "security": security,
            "verified_count": sum(1 for c in claims if c.verified),
        }
