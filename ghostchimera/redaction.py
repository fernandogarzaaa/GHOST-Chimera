"""Shared secret-redaction primitives (single source of truth).

Several modules grew their own copies of these markers, patterns, and
helpers; divergence here is how secrets leak. This module owns the canonical
definitions. Callers with narrower needs compose their marker set from
:data:`BASE_MARKERS` and pass behavioral flags instead of forking the code.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import math
import re
from collections import Counter
from typing import Any
from urllib.parse import unquote

BASE_MARKERS = ("token", "secret", "api_key", "apikey", "password", "credential", "authorization", "bearer")

SECRET_MARKERS = BASE_MARKERS

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?:gh[pousr]|github_pat|xoxb|xoxp)_[A-Za-z0-9_\-]{12,}"),
    # Real Slack tokens use hyphens (xoxb-123-456-abc); GitLab PATs; Stripe live/test keys.
    re.compile(r"\bxox[abposre]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{16,}"),
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
    re.compile(r"\bv1\.[A-Za-z0-9_\-]{32,}"),
)

# ``<key-ish name> = value`` / ``"password": "value"`` / ``aws_secret_access_key: value``.
# The key may be quoted and may carry a prefix/suffix (``aws_secret_access_key``,
# ``DB_PASSWORD``); the key is kept and only the value is replaced.
_SECRET_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (?<![A-Za-z0-9_.\-])
    (?P<key>["']?[A-Za-z0-9_.\-]{0,40}?
        (?:api[_-]?key|secret|password|passwd|pwd|access[_-]?token|refresh[_-]?token|auth[_-]?token
          |private[_-]?key|client[_-]?secret|session[_-]?token|access[_-]?key)
       [A-Za-z0-9_.\-]{0,40}["']?)
    (?P<sep>\s*[:=]\s*)
    (?P<quote>["']?)
    (?P<value>[^\s"',;{}\[\]]{4,})
    """
)
# ``scheme://user:password@host`` -> keep scheme and host, drop the userinfo.
_URL_USERINFO_RE = re.compile(r"(?i)(?<![a-z0-9+.\-])([a-z][a-z0-9+.\-]{0,30}://)[^\s:/@]{1,256}:[^\s@/]{1,256}@")
# Long base64/base64url runs (decoded and re-scanned) and high-entropy tokens.
_BASE64_RUN_RE = re.compile(r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{24,}={0,2}(?![A-Za-z0-9+/_\-])")
_HIGH_ENTROPY_RE = re.compile(r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{32,}={0,2}(?![A-Za-z0-9+/_\-])")

# Personal data (PII). Each entry is (label, pattern); matches become
# ``[redacted:<label>]``. Card numbers are only redacted when they pass the
# Luhn check so long numeric IDs and millisecond timestamps survive.
PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,}\b")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # Philippine mobiles: 09171234567, 0917-123-4567, (0917) 123 4567, +63 917 123 4567, 639171234567.
    (
        "phone",
        re.compile(r"(?<![\w+])(?:\+?63[\s.\-]?|\(?0)9\d{2}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\w)"),
    ),
    ("card", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")),
    ("phone", re.compile(r"(?<![\w+])(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)")),
    (
        "ip",
        re.compile(
            r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w.])"
        ),
    ),
    ("ip", re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")),
)

# Home-directory usernames: /home/<user>, /Users/<user>, C:\Users\<user>.
_HOME_DIR_RE = re.compile(r"(?i)(?P<prefix>/home/|/Users/|[A-Z]:[\\/]+Users[\\/]+)(?P<user>[^\s/\\\"'<>|:]+)")
_HOME_DIR_KEEP = frozenset({"shared", "public", "default", "all users", "[user]"})

# Hard limits for egress redaction (poweruser F5): deep nesting and huge
# strings are clipped *before* scanning so the regex work is bounded.
EGRESS_MAX_DEPTH = 32
EGRESS_MAX_STRING = 16_384


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


def redact_secrets_text(text: str) -> str:
    """Scrub every known credential shape (local + egress patterns), keep PII."""
    return _redact_secret_shapes(str(text))


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


def _iban_ok(candidate: str) -> bool:
    compact = candidate.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    try:
        number = int("".join(str(int(ch, 36)) for ch in rearranged))
    except ValueError:
        return False
    return number % 97 == 1


def _ip_redaction(match: re.Match[str]) -> str:
    text = match.group(0)
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return text
    if addr.is_loopback or addr.is_unspecified:
        return text
    return "[redacted:ip]"


def _home_dir_redaction(match: re.Match[str]) -> str:
    if match.group("user").lower() in _HOME_DIR_KEEP:
        return match.group(0)
    return f"{match.group('prefix')}[user]"


def redact_pii_text(text: str) -> str:
    """Replace e-mail addresses, phone numbers, SSNs, cards, IBANs, IPs and home-dir usernames."""

    redacted = text
    for label, pattern in PII_PATTERNS:
        if label == "card":
            redacted = pattern.sub(lambda m: "[redacted:card]" if _luhn_ok(m.group(0)) else m.group(0), redacted)
        elif label == "iban":
            redacted = pattern.sub(lambda m: "[redacted:iban]" if _iban_ok(m.group(0)) else m.group(0), redacted)
        elif label == "ip":
            redacted = pattern.sub(_ip_redaction, redacted)
        else:
            redacted = pattern.sub(f"[redacted:{label}]", redacted)
    return _HOME_DIR_RE.sub(_home_dir_redaction, redacted)


def _shannon_entropy(token: str) -> float:
    counts = Counter(token)
    total = len(token)
    return -sum(n / total * math.log2(n / total) for n in counts.values())


def _looks_random(token: str) -> bool:
    core = token.rstrip("=")
    if len(core) < 32 or core.count("/") > 2:
        return False
    if not (any(c.isupper() for c in core) and any(c.islower() for c in core) and any(c.isdigit() for c in core)):
        return False
    return _shannon_entropy(core) >= 4.5


def _secret_patterns_hit(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS + EGRESS_SECRET_PATTERNS) or bool(
        _SECRET_ASSIGNMENT_RE.search(text)
    )


def _decoded_secret(token: str) -> bool:
    """True when a base64/base64url run decodes to text containing a credential."""
    core = token.rstrip("=")
    if len(core) > 4096:  # a blob, not an encoded credential; keep the scan bounded
        return False
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = decoder(core + "=" * (-len(core) % 4))
        except (binascii.Error, ValueError):
            continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if decoded.isprintable() and _secret_patterns_hit(decoded):
            return True
    return False


def _redact_secret_shapes(text: str) -> str:
    redacted = _URL_USERINFO_RE.sub(r"\1[redacted]@", text)
    redacted = redact_text(redacted, patterns=SECRET_PATTERNS + EGRESS_SECRET_PATTERNS)
    redacted = _SECRET_ASSIGNMENT_RE.sub(
        lambda m: f"{m.group('key')}{m.group('sep')}{m.group('quote')}[redacted]", redacted
    )
    redacted = _BASE64_RUN_RE.sub(lambda m: "[redacted]" if _decoded_secret(m.group(0)) else m.group(0), redacted)
    redacted = _HIGH_ENTROPY_RE.sub(lambda m: "[redacted]" if _looks_random(m.group(0)) else m.group(0), redacted)
    if "%" in redacted:
        # URL-encoded credentials (``password%3Dhunter2``, ``ghp_...%0A``):
        # scan the decoded form and keep it only when that removed something.
        decoded = unquote(redacted)
        if decoded != redacted and _secret_patterns_hit(decoded):
            redacted = _redact_secret_shapes(decoded)
    return redacted


def redact_egress_text(text: str) -> str:
    """Scrub secrets and PII from one string (clipped to :data:`EGRESS_MAX_STRING`)."""
    value = str(text)
    if len(value) > EGRESS_MAX_STRING:
        value = value[:EGRESS_MAX_STRING] + "...[truncated]"
    return redact_pii_text(_redact_secret_shapes(value))


def redact_for_egress(value: Any, *, _depth: int = 0) -> Any:
    """Scrub secrets *and* PII from a JSON-like value before it leaves the host.

    Use on anything sent to a cloud model (Nebius / Nemotron), a web search
    provider (Tavily) or a tracing backend (LangSmith). Secret-marked mapping
    keys are blanked, secret-shaped substrings and PII are replaced. Nesting
    deeper than :data:`EGRESS_MAX_DEPTH` is replaced by a marker (no
    ``RecursionError``) and long strings are clipped before scanning. The
    input is never mutated.
    """

    if _depth > EGRESS_MAX_DEPTH:
        return "[redacted:depth]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_MARKERS):
                out[str(key)] = "[redacted]" if item else ""
            else:
                out[str(key)] = redact_for_egress(item, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_for_egress(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return redact_egress_text(value)
    return value


def redact_secret_values(value: Any, *, markers: tuple[str, ...] = SECRET_MARKERS, _depth: int = 0) -> Any:
    """Like :func:`redact_value` but strings get the full credential scrub (PII kept).

    For local persistence that must not hold credentials (run journals,
    exports): secret-marked keys are blanked and every string passes through
    :func:`redact_secrets_text`. Depth is capped like :func:`redact_for_egress`.
    """
    if _depth > EGRESS_MAX_DEPTH:
        return "[redacted:depth]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in markers):
                out[str(key)] = "[redacted]" if item else ""
            else:
                out[str(key)] = redact_secret_values(item, markers=markers, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_secret_values(item, markers=markers, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return redact_secrets_text(value)
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
    "redact_egress_text",
    "redact_for_egress",
    "redact_pii_text",
    "redact_secret_values",
    "redact_secrets_text",
    "redact_text",
    "redact_value",
    "scrubbed_environ",
]
