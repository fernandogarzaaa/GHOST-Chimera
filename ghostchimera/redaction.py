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

# Extra credential shapes worth scrubbing before data leaves the machine
# (cloud LLM calls, tracing). Kept separate from SECRET_PATTERNS so existing
# local redaction behaviour is unchanged.
EGRESS_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\b(?:gsk|xai|tvly|lsv2_pt|lsv2_sk|hf)_[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),  # JWT
    re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|access[_-]?token|refresh[_-]?token)\b\s*[:=]\s*[\"']?[^\s\"',;]{6,}"
    ),
)

# Personal data (PII). Each entry is (label, pattern); matches become
# ``[redacted:<label>]``. Card numbers are only redacted when they pass the
# Luhn check so long numeric IDs and millisecond timestamps survive.
PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")),
    ("phone", re.compile(r"(?<![\w+])(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)")),
)


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


def _luhn_ok(candidate: str) -> bool:
    digits = [int(ch) for ch in candidate if ch.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def redact_pii_text(text: str) -> str:
    """Replace e-mail addresses, phone numbers, SSNs and card numbers."""

    redacted = text
    for label, pattern in PII_PATTERNS:
        if label == "card":
            redacted = pattern.sub(lambda m: "[redacted:card]" if _luhn_ok(m.group(0)) else m.group(0), redacted)
        else:
            redacted = pattern.sub(f"[redacted:{label}]", redacted)
    return redacted


def redact_for_egress(value: Any) -> Any:
    """Scrub secrets *and* PII from a JSON-like value before it leaves the host.

    Use on anything sent to a cloud model (Nebius / Nemotron) or a tracing
    backend (LangSmith). Secret-marked mapping keys are blanked, secret-shaped
    substrings and PII are replaced. The input is never mutated.
    """

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_MARKERS):
                out[str(key)] = "[redacted]" if item else ""
            else:
                out[str(key)] = redact_for_egress(item)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_for_egress(item) for item in value]
    if isinstance(value, str):
        return redact_pii_text(redact_text(value, patterns=SECRET_PATTERNS + EGRESS_SECRET_PATTERNS))
    return value


def is_secret_env_key(key: str, *, markers: tuple[str, ...] = SECRET_MARKERS) -> bool:
    """True when an environment variable name looks like it holds a secret."""
    lowered = str(key).lower()
    return any(marker in lowered for marker in markers)


def scrubbed_environ(
    *,
    markers: tuple[str, ...] = SECRET_MARKERS,
    keep: frozenset[str] | set[str] = frozenset(),
) -> dict[str, str]:
    """Copy of ``os.environ`` with secret-marked variables removed.

    Use as the ``env=`` argument for any child process. Provider API keys and
    OAuth tokens applied via ``os.environ`` must never be inherited by
    spawned subprocesses; the console process itself keeps using the real
    environment. Names in ``keep`` are preserved verbatim.
    """
    import os

    return {k: v for k, v in os.environ.items() if k in keep or not is_secret_env_key(k, markers=markers)}


__all__ = [
    "BASE_MARKERS",
    "EGRESS_SECRET_PATTERNS",
    "PII_PATTERNS",
    "POISON_PATTERNS",
    "RISK_ORDER",
    "SECRET_MARKERS",
    "SECRET_PATTERNS",
    "is_secret_env_key",
    "redact_for_egress",
    "redact_pii_text",
    "redact_text",
    "redact_value",
    "scrubbed_environ",
]
