"""Shared secret-redaction primitives (single source of truth).

Several modules grew their own copies of these markers, patterns, and
helpers; divergence here is how secrets leak. This module owns the canonical
definitions. Callers with narrower needs compose their marker set from
:data:`BASE_MARKERS` and pass behavioral flags instead of forking the code.
"""

from __future__ import annotations

import re
from typing import Any

BASE_MARKERS = ("token", "secret", "api_key", "apikey", "password", "credential", "authorization", "bearer")

SECRET_MARKERS = BASE_MARKERS

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?:ghp|github_pat|xoxb|xoxp)_[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{12,}", re.IGNORECASE),
)

POISON_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"exfiltrat(?:e|ion)", re.IGNORECASE),
    re.compile(r"send\s+(?:the\s+)?(?:secret|token|password|credential)", re.IGNORECASE),
    re.compile(r"call\s+(?:restricted|admin|internal)\s+tool", re.IGNORECASE),
)

RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def redact_text(
    text: str,
    *,
    patterns: tuple = SECRET_PATTERNS,
    replacement: str = "[redacted]",
) -> str:
    """Replace secret-like substrings in free text."""

    redacted = text
    for pattern in patterns:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(
    value: Any,
    *,
    markers: tuple[str, ...] = SECRET_MARKERS,
    patterns: tuple = SECRET_PATTERNS,
    redact_strings: bool = True,
    passthrough_keys: frozenset[str] | set[str] = frozenset(),
) -> Any:
    """Redact a JSON-like structure without mutating it.

    Mapping keys containing a marker are replaced (falsy values become "").
    Keys in ``passthrough_keys`` are recursed into instead. When
    ``redact_strings`` is true, free-text strings are pattern-scrubbed too.
    """

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in passthrough_keys:
                out[str(key)] = redact_value(
                    item,
                    markers=markers,
                    patterns=patterns,
                    redact_strings=redact_strings,
                    passthrough_keys=passthrough_keys,
                )
            elif any(marker in lowered for marker in markers):
                out[str(key)] = "[redacted]" if item else ""
            else:
                out[str(key)] = redact_value(
                    item,
                    markers=markers,
                    patterns=patterns,
                    redact_strings=redact_strings,
                    passthrough_keys=passthrough_keys,
                )
        return out
    if isinstance(value, list):
        return [
            redact_value(
                item,
                markers=markers,
                patterns=patterns,
                redact_strings=redact_strings,
                passthrough_keys=passthrough_keys,
            )
            for item in value
        ]
    if isinstance(value, str) and redact_strings:
        return redact_text(value, patterns=patterns)
    return value


__all__ = [
    "BASE_MARKERS",
    "POISON_PATTERNS",
    "RISK_ORDER",
    "SECRET_MARKERS",
    "SECRET_PATTERNS",
    "redact_text",
    "redact_value",
]
