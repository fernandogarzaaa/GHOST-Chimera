"""Sensitive-content guard for free-tier routing.

Free tiers (OpenRouter :free, Gemini free) may log prompts for training.
Anything flagged here never routes to a training-logging tier — it falls
through to non-logging paths or waits for a paid key. Heuristic and
fail-closed: when in doubt, it flags.
"""

from __future__ import annotations

import re

_PATTERNS = [
    # Credentials and secrets.
    r"(?i)(api[_-]?key|secret|password|passwd|pwd|token|bearer)\s*[:=]\s*\S+",
    r"(?i)sk-(live|test|ant|or-v1)[A-Za-z0-9_-]+",
    r"(?i)(gsk_|xai-|AIza)[A-Za-z0-9_.-]+",
    r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----",
    # Personal identifiers.
    r"\b\d{3}-\d{2}-\d{4}\b",  # SSN-like
    r"(?i)(social security|passport (no|number)|driver'?s license)\s*[:#]?\s*\S+",
    r"\b\d{13,19}\b",  # card-like runs
    # One-time codes / reset links (mirror of the mail filter).
    r"(?i)\b(code|otp|token|pin)\s*(?:is|:)?\s*(\b\d{4,8}\b)",
    r"https?://\S*(?:reset|recover|verify-email|magic-link|one-time)[^\s]*",
]

_COMPILED = [re.compile(pattern) for pattern in _PATTERNS]


def is_sensitive(*texts: str) -> bool:
    """True when any text looks like credentials, IDs, or one-time secrets."""
    for text in texts:
        if not text:
            continue
        lowered = str(text)
        for pattern in _COMPILED:
            if pattern.search(lowered):
                return True
    return False


def scrub_preview(text: str, *, keep: int = 120) -> str:
    """Short redacted preview for logs and UI (never the raw content)."""
    text = str(text or "")
    if len(text) <= keep:
        return text
    return text[:keep] + "…"


__all__ = ["is_sensitive", "scrub_preview"]
